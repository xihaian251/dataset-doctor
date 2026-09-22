"""Re-splitting: the one place the tool writes data, and the fix DD005 recommends.

The spec's loop is Detect -> Explain -> Quantify -> Trace -> Recommend, and the recommendation
for entity leakage is this command. So the tests here are not about arithmetic, they are about
the two promises that make the recommendation safe to follow: an entity never lands in two
splits, and nothing the user already had is overwritten.

Spec coverage: the group-aware half of TEST 1-6 (leakage created by a row-wise shuffle and
removed by a grouped one), plus the no-overwrite prohibition in spec section 229.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from conftest import TABULAR_CONFIG, row, write_rows

from dataset_doctor_audit import audit_dataset
from dataset_doctor_audit.errors import SplitError
from dataset_doctor_audit.splitting import SplitRequest, split_dataset

COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]


@pytest.fixture
def pooled(tmp_path: Path) -> Path:
    """A table where patients recur, and eight rows appear twice.

    This is the shape that makes a naive shuffle leak: the same `patient_id` on both sides
    of any row-wise boundary, and byte-identical rows sitting in two files already.
    """
    root = tmp_path / "pooled"
    root.mkdir(parents=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 6:02d}", index=i) for i in range(60)], COLUMNS)
    leaked = [row(f"r{i:03d}", f"p{i // 6:02d}", index=i) for i in range(8)]
    write_rows(
        root / "test.csv", leaked + [row(f"t{i:03d}", f"p{20 + i // 6:02d}", index=60 + i) for i in range(40)], COLUMNS
    )
    return root


def _split(source: Path, output: Path, **kwargs: Any) -> Any:
    return split_dataset(SplitRequest(source=source, output=output, **kwargs))


def _rows_by_split(output: Path) -> dict[str, pd.DataFrame]:
    return {path.stem: pd.read_csv(path) for path in sorted(output.glob("*.csv"))}


# --------------------------------------------------------------- the leakage guarantee
def test_a_grouped_split_keeps_every_entity_on_one_side_of_the_boundary(pooled: Path, tmp_path: Path) -> None:
    output = tmp_path / "grouped"
    result = _split(
        pooled, output, group_by="patient_id", stratify="target", ratios={"train": 0.6, "val": 0.2, "test": 0.2}
    )

    frames = _rows_by_split(output)
    assert set(frames) == {"train", "val", "test"}
    assert result.rows == 108
    seen: dict[str, set[str]] = {name: set(frame["patient_id"]) for name, frame in frames.items()}
    overlap = {
        f"{a} & {b}": sorted(seen[a] & seen[b])
        for a in ("train", "val", "test")
        for b in ("train", "val", "test")
        if a < b
    }
    assert all(overlap[pair] == [] for pair in overlap), f"an entity crossed the boundary: {overlap}"
    assert sum(len(frame) for frame in frames.values()) == 108, "no row may be dropped by the split"


def test_a_row_wise_split_of_the_same_data_does_leak_and_the_tool_says_so(pooled: Path, tmp_path: Path) -> None:
    """The counterfactual that makes the previous test mean something.

    Without `--group-by` this is a shuffle, and the audit of the result must report entity
    leakage across the boundary - otherwise "group-aware" would be an unverifiable claim.
    """
    output = tmp_path / "shuffled"
    result = _split(pooled, output, ratios={"train": 0.6, "test": 0.4}, seed=7)

    assert any("ungrouped" in note or "plain row shuffle" in note for note in result.notes)
    audit = audit_dataset(output)
    crossing = [
        finding
        for finding in audit.by_rule("DD005") + audit.by_rule("DD003")
        if finding.metadata.get("scope") == "cross_split"
    ]
    assert crossing, "a row-wise shuffle of recurring patients must be caught"
    assert audit.report.eval_safety.value == "FORMAL_EVAL_INVALID"


def test_the_grouped_output_of_the_same_data_passes_the_leakage_rules(pooled: Path, tmp_path: Path) -> None:
    """The last step of the loop: does the problem actually disappear after the fix?

    `dedupe=True` is part of this: the eight byte-identical rows are still inside one split
    after grouping, and an exact duplicate in train is a quality problem the audit would keep
    reporting. Removing them is the honest way to end up with a clean verdict.
    """
    output = tmp_path / "fixed"
    result = _split(
        pooled,
        output,
        group_by="patient_id",
        stratify="target",
        dedupe=True,
        ratios={"train": 0.6, "val": 0.2, "test": 0.2},
    )
    assert result.duplicates_removed == 8

    audit = audit_dataset(output)
    assert audit.by_rule("DD003") == []
    assert [f for f in audit.by_rule("DD005") if f.metadata.get("scope") == "cross_split"] == []
    assert audit.report.eval_safety.value != "FORMAL_EVAL_INVALID"
    assert audit.identity.num_samples == 100


# ----------------------------------------------------------------- reproducibility
def test_the_seed_fully_determines_the_assignment(pooled: Path, tmp_path: Path) -> None:
    kwargs = {"group_by": "patient_id", "ratios": {"train": 0.6, "test": 0.4}}
    first = _split(pooled, tmp_path / "a", **kwargs)
    second = _split(pooled, tmp_path / "b", **kwargs)
    other = _split(pooled, tmp_path / "c", **{**kwargs, "seed": 1234})

    assert first.manifest["seed"] == second.manifest["seed"]
    for name in ("train", "test"):
        left = pd.read_csv(first.output / f"{name}.csv")
        right = pd.read_csv(second.output / f"{name}.csv")
        assert left["record_id"].tolist() == right["record_id"].tolist()
    different = pd.read_csv(other.output / "test.csv")["record_id"].tolist()
    assert different != pd.read_csv(first.output / "test.csv")["record_id"].tolist()


def test_the_manifest_is_enough_to_review_and_reproduce_the_split(pooled: Path, tmp_path: Path) -> None:
    result = _split(pooled, tmp_path / "out", group_by="patient_id", ratios={"train": 0.7, "test": 0.3})
    stored = json.loads((result.output / "split-manifest.json").read_text(encoding="utf-8"))

    for key in ("seed", "ratios", "strategy", "source", "split_sizes", "entity_split_sizes", "files", "notes"):
        assert key in stored, key
    assert stored["strategy"].startswith("grouped")
    assert sum(stored["split_sizes"].values()) == 108
    assert stored["split_sizes"] == result.split_sizes
    hashed = {item["path"]: item["sha256"] for item in stored["files"] if item["kind"] == "file"}
    assert hashed.get("train.csv"), "a manifest without hashes proves nothing"


def test_ratios_that_no_entity_partition_can_hit_are_flagged_not_rounded(tmp_path: Path) -> None:
    """One 40-row patient in a 60-row pool cannot sit on both sides of a 50/50 cut.

    The entity counts land almost evenly, so an entity-only tolerance would let this claim to
    be exact while the *rows* came out 11/49. That is the case this flag exists for.
    """
    root = tmp_path / "lopsided"
    root.mkdir()
    rows = [row(f"g{i:03d}", "p00", index=i) for i in range(40)]
    rows += [row(f"s{i:03d}", f"p{1 + i:02d}", index=40 + i) for i in range(20)]
    write_rows(root / "pool.csv", rows, COLUMNS)

    result = _split(root, tmp_path / "out", group_by="patient_id", ratios={"train": 0.5, "test": 0.5})

    assert result.split_sizes in ({"train": 11, "test": 49}, {"train": 49, "test": 11})
    assert result.approximate is True
    assert result.strategy.endswith("(APPROXIMATE)")
    assert any("APPROXIMATE" in note or "percentage points" in note for note in result.notes)
    assert result.manifest["ratio_deviation_rows"] > 0.3


def test_stratification_keeps_both_classes_present_in_every_split(pooled: Path, tmp_path: Path) -> None:
    output = tmp_path / "stratified"
    result = _split(
        pooled, output, group_by="patient_id", stratify="target", ratios={"train": 0.6, "val": 0.2, "test": 0.2}
    )

    for name, counts in result.class_counts.items():
        assert set(counts) == {"0", "1"}, f"{name} lost a class: {counts}"
        assert min(counts.values()) > 0


# ------------------------------------------------------------- the no-overwrite rules
def test_an_existing_non_empty_directory_is_refused_and_left_untouched(tmp_path: Path, pooled: Path) -> None:
    output = tmp_path / "precious"
    output.mkdir()
    keep = output / "notes.md"
    keep.write_text("do not lose me", encoding="utf-8")

    with pytest.raises(SplitError) as excinfo:
        _split(pooled, output, group_by="patient_id")

    assert "overwrit" in str(excinfo.value).lower() or "non-empty" in str(excinfo.value)
    assert keep.read_text(encoding="utf-8") == "do not lose me"
    assert list(output.glob("*.csv")) == []


def test_a_split_that_would_come_out_empty_fails_before_anything_is_written(pooled: Path, tmp_path: Path) -> None:
    """Two ratios with 100 entities is fine; the same ratios on four entities are not."""
    tiny = tmp_path / "tiny"
    tiny.mkdir()
    write_rows(
        tiny / "pool.csv",
        [row(f"r{i:03d}", f"p{i // 20:02d}", index=i) for i in range(8)],
        COLUMNS,
    )
    output = tmp_path / "never"

    with pytest.raises(SplitError):
        _split(tiny, output, group_by="patient_id", ratios={"train": 0.8, "val": 0.1, "test": 0.1})

    assert not output.exists() or list(output.iterdir()) == []


def test_grouping_by_a_column_that_is_not_there_is_refused(pooled: Path, tmp_path: Path) -> None:
    with pytest.raises(SplitError) as excinfo:
        _split(pooled, tmp_path / "x", group_by="not_a_column")

    assert "not_a_column" in str(excinfo.value)


def test_the_source_directory_is_not_modified(pooled: Path, tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in pooled.glob("*.csv")}

    _split(pooled, tmp_path / "out", group_by="patient_id", ratios={"train": 0.6, "test": 0.4})

    assert {path.name: path.read_bytes() for path in pooled.glob("*.csv")} == before


# ------------------------------------------------------------------- config carriage
def test_the_declared_fields_travel_with_the_split(pooled: Path, tmp_path: Path) -> None:
    """An output directory that lost `groups.columns` would audit as if patient_id were noise."""
    output = tmp_path / "out"
    _split(pooled, output, group_by="patient_id", stratify="target", ratios={"train": 0.6, "test": 0.4})

    carried = (output / "dataset-doctor.yaml").read_text(encoding="utf-8")
    assert "patient_id" in carried and "target" in carried

    audit = audit_dataset(output)
    assert audit.rule("DD005") is not None
    assert audit.rule("DD005").status.value != "NOT_RUN", "the carried config must keep DD005 measurable"
