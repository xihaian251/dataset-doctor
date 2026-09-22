"""Leakage-first rules on the modalities V0.1 supports.

Spec test coverage: TEST 1 (identical image across splits), TEST 2 (same bytes, other
filename), TEST 3 (same filename, other bytes), TEST 4 (identical bytes, different
label), TEST 5/6 (entity leakage and its absence), TEST 19 (identical content on two
paths under full fingerprinting), TEST 31 (near-duplicate threshold boundary).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from conftest import IMAGE_CONFIG, TABULAR_CONFIG, row

from dataset_doctor.models import AuditStatus, EvalSafety, FormalImpact, Severity

pytest.importorskip("imagehash", reason="DD004 needs the optional `image` extra")


def test_test01_identical_image_in_train_and_test_is_critical(
    tabular: Any, images: Any, pattern: Any, run_audit: Any
) -> None:
    tile = pattern(11)
    root = images("dup_cross", train={"bruise": [tile]}, test={"bruise": [tile.copy()]})
    result = run_audit(root)

    findings = result.by_rule("DD003")
    assert findings, "an image present in both splits must be reported"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].formal_impact is FormalImpact.BLOCKING
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID
    assert result.exit_code() == 1


def test_test02_same_bytes_under_different_names_still_detected(images: Any, pattern: Any, run_audit: Any) -> None:
    tile = pattern(21)
    root = images("dup_names", train={"bruise": [tile]}, test={"scar": [tile.copy()]})
    result = run_audit(root)

    assert [finding.target_split for finding in result.by_rule("DD003")] == ["train"]
    assert result.by_rule("DD003")[0].severity is Severity.CRITICAL


def test_test03_same_filename_different_bytes_is_not_a_duplicate(images: Any, pattern: Any, run_audit: Any) -> None:
    root = images(
        "same_name",
        train={"bruise": [pattern(31), pattern(32)]},
        test={"bruise": [pattern(33), pattern(34)]},
    )
    result = run_audit(root)

    assert result.by_rule("DD003") == []
    assert result.rule("DD003").status is AuditStatus.PASS


def test_test04_identical_content_with_conflicting_labels_is_critical(
    images: Any, pattern: Any, run_audit: Any
) -> None:
    tile = pattern(41)
    root = images(
        "label_conflict",
        train={"bruise": [tile]},
        test={"scar": [tile.copy()], "crack": [pattern(42)]},
    )
    result = run_audit(root)

    findings = result.by_rule("DD009")
    assert findings and findings[0].severity is Severity.CRITICAL
    assert findings[0].metadata["scope"] == "cross_split"
    assert "bruise" in str(findings[0].evidence) and "scar" in str(findings[0].evidence)


def test_conflicting_labels_inside_the_evaluation_split_stay_blocking(
    images: Any, pattern: Any, run_audit: Any
) -> None:
    """No training copy, so it is not contamination - but the score itself is unusable."""
    tile = pattern(43)
    root = images(
        "label_conflict_eval",
        train={"crack": [pattern(45)]},
        test={"bruise": [tile], "scar": [tile.copy()]},
    )
    result = run_audit(root)

    findings = result.by_rule("DD009")
    assert findings and findings[0].severity is Severity.HIGH
    assert findings[0].metadata["scope"] == "within_split"
    assert findings[0].formal_impact is FormalImpact.BLOCKING
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID


def test_conflicting_labels_inside_train_alone_are_label_noise_not_leakage(
    images: Any, pattern: Any, run_audit: Any
) -> None:
    """Spec prohibition: a data-quality problem must not be priced as evaluation invalidation.

    Same deterministic evidence as TEST 4, different consequence - nothing crosses a split
    boundary, so the tool reports it and leaves the formal verdict alone.
    """
    tile = pattern(46)
    root = images(
        "label_conflict_train", train={"bruise": [tile], "scar": [tile.copy()]}, test={"crack": [pattern(47)]}
    )
    result = run_audit(root)

    findings = result.by_rule("DD009")
    assert findings and findings[0].severity is Severity.MEDIUM
    assert findings[0].metadata["scope"] == "within_split"
    assert findings[0].formal_impact is FormalImpact.POTENTIAL
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_INVALID


def test_test05_shared_entity_across_splits_is_critical(tabular: Any, run_audit: Any) -> None:
    train = [row(f"r{i:03d}", f"p{i % 5:02d}", index=i) for i in range(40)]
    test = [row(f"t{i:03d}", f"p{i % 5:02d}", index=40 + i) for i in range(20)]
    result = run_audit(tabular("entity_leak", train=train, test=test))

    findings = result.by_rule("DD005")
    assert findings, "the same patient in train and test is the classic leakage case"
    assert findings[0].severity is Severity.CRITICAL
    assert findings[0].evidence["entities"] == 5
    assert findings[0].affected_count == 60


def test_test06_disjoint_entities_are_not_flagged(tabular: Any, run_audit: Any) -> None:
    """Different patients either side of the boundary: entities repeat, but never across splits."""
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)]
    test = [row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i) for i in range(20)]
    result = run_audit(tabular("entity_clean", train=train, test=test))

    assert result.by_rule("DD005") == []
    assert result.rule("DD005").status is AuditStatus.PASS
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_SAFE


def test_a_row_unique_group_column_is_an_advisory_not_a_leakage_finding(tabular: Any, run_audit: Any) -> None:
    """Every entity appears once, so cross-split leakage is undetectable through this column.

    That is worth one line of advice - the user probably named a row id where they meant a
    patient id - but it cannot raise a leakage verdict on a dataset with nothing shared.
    """
    train = [row(f"r{i:03d}", f"p{i:02d}", index=i) for i in range(40)]
    test = [row(f"t{i:03d}", f"q{i:02d}", index=40 + i) for i in range(20)]
    result = run_audit(tabular("entity_unique", train=train, test=test))

    findings = result.by_rule("DD005")
    assert findings, "the declared group column being row-unique is still worth one line"
    assert [finding for finding in findings if finding.severity.rank >= Severity.MEDIUM.rank] == []
    assert findings[0].formal_impact is FormalImpact.NONE
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_INVALID


def test_rows_without_declared_groups_leave_the_entity_rule_not_run(tabular: Any, run_audit: Any) -> None:
    config = "dataset:\n  type: tabular\nlabels:\n  column: target\npolicies: {}\n"
    train = [row(f"r{i:03d}", f"p{i:02d}", index=i) for i in range(20)]
    test = [row(f"t{i:03d}", f"p{i:02d}", index=20 + i) for i in range(20)]
    result = run_audit(tabular("entity_undeclared", config=config, train=train, test=test))

    outcome = result.rule("DD005")
    assert outcome.status is AuditStatus.NOT_RUN
    assert outcome.skip_reason, "a rule that could not run has to say why"
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_SAFE


def test_test19_identical_bytes_on_two_paths_have_two_sample_ids(
    tabular: Any, images: Any, pattern: Any, run_audit: Any
) -> None:
    """Full fingerprinting keeps path identity; content identity is DD003's job."""
    tile = pattern(51)
    root = images("dual_paths", train={"bruise": [tile]}, test={"bruise": [tile.copy()]})
    full = run_audit(root, fingerprint="full")
    metadata = run_audit(root, fingerprint="metadata")

    ids = {record.sample_id for record in full.manifest.records}
    assert len(ids) == 2, "two files are two samples even when their bytes match"
    assert full.by_rule("DD003"), "and the duplicate is still reported"
    assert metadata.rule("DD003").status is AuditStatus.UNSUPPORTED
    assert "metadata" in metadata.rule("DD003").skip_reason


def test_test31_near_duplicate_boundary_is_the_threshold_itself(images: Any, pattern: Any, run_audit: Any) -> None:
    """The same pair, audited twice with the threshold one bit apart."""
    base = pattern(61)
    distance, partner = _partner_at_small_distance(base, pattern)
    if distance is None:
        pytest.skip("no deterministic perturbation of this tile lands inside the tested band")

    at_boundary = run_audit(
        images(
            "boundary_at",
            config=_near_duplicate_config(distance),
            train={"bruise": [base]},
            test={"bruise": [partner]},
        )
    )
    below = run_audit(
        images(
            "boundary_below",
            config=_near_duplicate_config(distance - 1),
            train={"bruise": [base]},
            test={"bruise": [partner]},
        )
    )

    assert at_boundary.by_rule("DD004"), f"a pair exactly {distance} bits apart passes a threshold of {distance}"
    assert at_boundary.by_rule("DD004")[0].evidence["hamming_threshold"] == distance
    assert below.by_rule("DD004") == [], "one bit tighter must stop reporting it - the knob is the policy"


def _near_duplicate_config(threshold: int) -> str:
    return (
        "dataset:\n  type: image\nlabels:\n  source: directory\n"
        f"policies:\n  near_duplicate:\n    enabled: true\n    hamming_threshold: {threshold}\n"
    )


def _partner_at_small_distance(base: np.ndarray, pattern: Any) -> tuple[int | None, np.ndarray]:
    """Deterministically find a brightened block whose pHash sits 1-8 bits away.

    Random tiles are useless here: two independent 8x8 noise images are ~20 bits apart, so a
    sweep over seeds never lands in the band the threshold knob lives in. A local brightness
    offset does, and it is the perturbation a real near-duplicate pair looks like.
    """
    import imagehash
    from PIL import Image

    base_image = Image.fromarray(base.astype(np.uint8), mode="RGB").resize((32, 32), Image.NEAREST)
    base_hash = imagehash.phash(base_image)
    source = np.array(base_image)
    for delta in (2, 3, 5, 8, 12, 20, 40):
        for block in range(16):
            candidate = source.copy()
            y, x = (block // 4) * 8, (block % 4) * 8
            candidate[y : y + 8, x : x + 8] = np.clip(candidate[y : y + 8, x : x + 8].astype(int) + delta, 0, 255)
            candidate = candidate.astype(np.uint8)
            distance = int(base_hash - imagehash.phash(Image.fromarray(candidate)))
            if 1 <= distance <= 8:
                return distance, candidate
    return None, base


def test_corrupt_and_empty_images_are_reported_not_silently_skipped(
    images: Any, pattern: Any, run_audit: Any, tmp_path: Path
) -> None:
    """TEST 13 and TEST 14."""
    root = images("broken", train={"bruise": [pattern(71), pattern(72)]}, test={"bruise": [pattern(73)]})
    (root / "train" / "bruise" / "truncated.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"junk" * 8)
    (root / "train" / "bruise" / "empty.png").write_bytes(b"")

    result = run_audit(root)
    findings = result.by_rule("DD016")
    assert findings, "unreadable files are a finding, not a skipped sample"
    assert {Path(path).name for path in findings[0].location.paths} == {"truncated.png", "empty.png"}
    assert result.identity.num_samples == 5


def test_metadata_mode_calls_integrity_a_lower_bound_not_a_count(images: Any, pattern: Any, run_audit: Any) -> None:
    """`--fingerprint metadata` never opens pixels, so a zero-byte file is the only corruption
    it can see. Reporting that as "1 of 1" overstates both the rate and the coverage; the
    denominator is the dataset and the answer is INCONCLUSIVE (AGENTS.md: no silent PASS).
    """

    root = images("partial", train={"bruise": [pattern(71), pattern(72), pattern(73)]}, test={"bruise": [pattern(74)]})
    (root / "train" / "bruise" / "truncated.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"junk" * 8)
    (root / "train" / "bruise" / "empty.png").write_bytes(b"")

    cheap = run_audit(root, fingerprint="metadata").by_rule("DD016")[0]
    assert cheap.status is AuditStatus.INCONCLUSIVE
    assert cheap.evidence["enumerated"] == 6 and cheap.evidence["not_decoded"] == 5
    assert cheap.evidence["broken"] == 1, "a truncated file needs a decode attempt to be seen"
    assert "lower bound" in cheap.description and cheap.limitations

    full = run_audit(root).by_rule("DD016")[0]
    assert full.status is AuditStatus.WARNING and full.evidence["not_decoded"] == 0
    assert full.evidence["broken"] == 2


def test_a_non_numeric_leak_candidate_reports_mutual_info_without_an_auc(tabular: Any, run_audit: Any) -> None:
    """A categorical culprit has no rank scale: the finding must not pretend there is one.

    This path used to format ``AUC=None`` into the description and crash on it. The column
    is deliberately imperfect - a clean bijection would be caught by the deterministic
    branch above it and the heuristic branch would never run.
    """

    def make(prefix: str, offset: int, count: int) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for index in range(offset, offset + count):
            base = row(f"{prefix}{index:03d}", f"p{index // 8:02d}", index=index)
            base["ward"] = "ICU" if base["target"] or index % 7 == 0 else "GENERAL"
            rows.append(base)
        return rows

    root = tabular("categorical_leak", train=make("r", 0, 40), test=make("t", 40, 20))

    result = run_audit(root)

    candidates = [finding for finding in result.by_rule("DD007") if "ward" in (finding.location.columns or [])]
    assert candidates, "a column that decides the label is a candidate even without a rank scale"
    finding = candidates[0]
    assert finding.evidence["single_feature_auc"] is None
    assert finding.evidence["normalized_mutual_info"] > 0.6
    assert "None" not in finding.description
    assert "not defined for a non-numeric column" in finding.description
    assert finding.status is AuditStatus.WARNING
    assert finding.formal_impact is FormalImpact.POTENTIAL


# ------------------------------------------------------------ DD008 identifier leakage
_DD008_COLUMNS = [
    "record_id",
    "patient_id",
    "age",
    "sex",
    "bmi",
    "value",
    "target",
    "external_uuid",
    "checksum",
    "session_id",
]


def _dd008_rows(count: int, prefix: str, offset: int) -> list[dict[str, Any]]:
    """Unique id-shaped and id-neutral columns, plus a dead-end that is named like an id.

    bmi/value are deliberately repeated: a near-unique *feature* column would turn the
    assertion set into "everything gets flagged" and prove nothing about the threshold.
    """
    rows: list[dict[str, Any]] = []
    for index in range(offset, offset + count):
        base = row(f"{prefix}{index:03d}", f"p{index // 8:02d}", index=index)
        base["bmi"] = round(20.0 + (index % 12) * 0.5, 2)
        base["value"] = index % 17
        base["external_uuid"] = f"{index:08d}-uuid"
        base["checksum"] = f"{(index * 2654435761) % (1 << 32):08x}"
        base["session_id"] = f"s{index % 6}"
        rows.append(base)
    return rows


def test_dd008_a_near_unique_undeclared_column_is_an_identifier_candidate(tabular: Any, run_audit: Any) -> None:
    root = tabular(
        "identifier_leak",
        columns=_DD008_COLUMNS,
        train=_dd008_rows(40, "r", 0),
        test=_dd008_rows(20, "t", 40),
    )

    result = run_audit(root)
    by_column = {finding.location.columns[0]: finding for finding in result.by_rule("DD008")}

    assert set(by_column) == {"external_uuid", "checksum"}, f"unexpected candidate set {sorted(by_column)}"
    assert by_column["external_uuid"].severity is Severity.MEDIUM, "the name says identifier"
    assert by_column["checksum"].severity is Severity.LOW, "only the cardinality says identifier"
    assert "session_id" not in by_column, "an id-named column with 6 levels is not near-unique"
    for finding in by_column.values():
        assert finding.status is AuditStatus.WARNING
        assert finding.formal_impact is FormalImpact.POTENTIAL
        assert finding.evidence["threshold"] == 0.98
        assert finding.evidence["unique_ratio"] == 1.0
    assert len([f for f in result.by_rule("DD008") if f.location.columns[0] == "external_uuid"]) == 1, (
        "one column must produce one finding across splits, not one per split"
    )


def test_dd008_declared_keys_are_resolved_not_re_judged(tabular: Any, run_audit: Any) -> None:
    """record_id and patient_id are near-unique too - declaring them moves them to identity."""
    root = tabular(
        "identifier_declared",
        config=TABULAR_CONFIG.replace("id_columns: [record_id]", "id_columns: [record_id, patient_id]"),
        columns=["record_id", "patient_id", "age", "sex", "bmi", "value", "target"],
        train=[row(f"r{i:03d}", f"p{i:03d}", index=i) for i in range(40)],
        test=[row(f"t{i:03d}", f"t{i:03d}", index=i + 40) for i in range(20)],
    )

    result = run_audit(root)
    flagged = {finding.location.columns[0] for finding in result.by_rule("DD008")}
    assert "record_id" not in flagged and "patient_id" not in flagged
    assert flagged == {"bmi", "value"}, "the genuinely near-unique feature columns stay candidates"


# ------------------------------------------------- fingerprint mode: sampled
def test_fingerprint_sampled_declares_its_coverage_and_is_deterministic(
    images: Any, pattern: Any, run_audit: Any
) -> None:
    config = IMAGE_CONFIG + "sampling:\n  fraction: 0.5\n"
    tiles = {seed: pattern(seed) for seed in range(1, 21)}
    root = images(
        "sampled_run",
        config=config,
        train={
            "bruise": [tiles[s] for s in range(1, 11)],
            "scar": [tiles[s] for s in range(11, 16)],
        },
        test={"bruise": [tiles[s] for s in range(16, 21)]},
    )

    first = run_audit(root, fingerprint="sampled")
    assert first.manifest.sample_fraction == 0.5
    assert first.identity.fingerprint_mode.value == "sampled"

    hashed = [record for record in first.manifest.records if record.metadata.get("hash_sampled")]
    assert 0 < len(hashed) < len(first.manifest.records), "the subset must be a real subset"
    assert all(record.sha256 for record in hashed)
    assert all(record.sha256 is None for record in first.manifest.records if record not in hashed)

    text = " ".join(first.report.limitations)
    assert "sampled" in text and "50.0%" in text and "seed" in text

    second = run_audit(root, fingerprint="sampled")
    assert second.identity.manifest_hash == first.identity.manifest_hash, (
        "sampled hashing is keyed on (seed, sample id): two runs must select the same subset"
    )


# ------------------------------------------------- imagehash absence fallback
def test_dd004_without_imagehash_is_inconclusive_and_the_rest_still_runs(
    images: Any, pattern: Any, run_audit: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The optional extra degrades one rule, not the audit.

    Blocking the import is done via sys.modules so the exact-duplicate control (DD003)
    in the same fixture proves the degradation is scoped to DD004.
    """
    import sys

    monkeypatch.setitem(sys.modules, "imagehash", None)
    base = pattern(61)
    near = np.clip(base.astype(int) + 3, 0, 255).astype(np.uint8)
    root = images(
        "no_imagehash",
        train={"bruise": [base, pattern(63)]},
        test={"bruise": [near, base.copy()]},
    )

    result = run_audit(root)
    outcome = result.rule("DD004")
    assert outcome is not None and outcome.status is AuditStatus.INCONCLUSIVE
    assert "imagehash" in (outcome.skip_reason or "")
    assert "not a PASS" in (outcome.skip_reason or "")

    assert result.by_rule("DD003"), "byte-exact leakage must still be caught with imagehash gone"
