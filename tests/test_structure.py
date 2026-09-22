"""Structure, labels and distribution rules: the false-positive side of the contract.

Every rule here has two directions that must both hold - a fault that is present gets
reported, and a fault that is merely *possible* (small splits, a long tail that is the
whole point of the dataset) does not silently become a verdict. Where the spec forces a
choice it is registered as an A-number in PROJECT_STATE.md, and the test says so.

Spec test coverage: TEST 7 (1% minority reported), TEST 8 (long-tail preset + suppression),
TEST 9 (train/test feature shift measured), TEST 10 (identical distributions not over-flagged),
TEST 11 (missing column), TEST 12 (dtype drift), TEST 28 (NaN category), TEST 29 (empty
dataset fails safe), TEST 30 (train only is INCONCLUSIVE), TEST 32 (suppression reason kept).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import TABULAR_CONFIG, row, write_rows

from dataset_doctor.errors import DatasetDoctorError
from dataset_doctor.models import AuditStatus, EvalSafety, FormalImpact, Severity

COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]


def _root(tmp_path: Path, name: str, config: str = TABULAR_CONFIG) -> Path:
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")
    return root


def _suppress_config(reason: str) -> str:
    """TABULAR_CONFIG plus a top-level ``suppress:`` block.

    Suppression is deliberately a dataset-level declaration rather than a field inside a
    policy block: it silences a rule for this dataset for a stated human reason, and the
    reason is mandatory.
    """
    quoted = reason.replace("'", "''")
    return TABULAR_CONFIG + f"suppress:\n  - rule: DD011\n    reason: '{quoted}'\n"


def test_test11_a_column_present_in_train_and_absent_in_test_is_found(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "missing_column")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)
    test_rows = [
        {k: v for k, v in row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i).items() if k != "bmi"} for i in range(20)
    ]
    write_rows(root / "test.csv", test_rows, [column for column in COLUMNS if column != "bmi"])

    result = run_audit(root)
    findings = result.by_rule("DD014")

    assert findings, "a schema that differs across the split boundary is not a detail"
    assert "bmi" in str(findings[0].evidence)
    assert findings[0].severity is Severity.HIGH
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_SAFE


def test_test12_a_column_that_changed_dtype_is_found(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "dtype_drift")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)
    test_rows = [dict(row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i)) for i in range(20)]
    for record in test_rows:
        record["value"] = f"v-{record['value']}"
    write_rows(root / "test.csv", test_rows, COLUMNS)

    result = run_audit(root)
    findings = result.by_rule("DD014")

    dtype_findings = [finding for finding in findings if "dtype" in finding.title.lower()]
    assert dtype_findings, f"numeric-vs-text drift must be reported, got {[f.title for f in findings]}"
    assert "value" in str(dtype_findings[0].evidence)


def test_test07_a_one_percent_class_is_reported_as_imbalance_without_invalidating_anything(
    tmp_path: Path, run_audit: Any
) -> None:
    """Spec section 223: class imbalance is a data-quality issue, not an evaluation-validity one."""
    root = _root(tmp_path, "imbalanced")
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i, target=1 if i < 3 else 0) for i in range(300)]
    test = [row(f"t{i:03d}", f"q{i // 4:02d}", index=300 + i, target=1 if i < 3 else 0) for i in range(100)]
    write_rows(root / "train.csv", train, COLUMNS)
    write_rows(root / "test.csv", test, COLUMNS)

    result = run_audit(root)
    findings = result.by_rule("DD011")

    assert findings, "a 1% minority is exactly what DD011 exists to say out loud"
    assert findings[0].formal_impact is not FormalImpact.BLOCKING
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_INVALID
    assert min(findings[0].evidence["class_counts"].values()) == 6
    assert 0.005 <= findings[0].evidence["minority_share"] <= 0.02


def test_test08_and_32_a_suppressed_rule_keeps_its_reason_in_the_report(tmp_path: Path, run_audit: Any) -> None:
    """Suppression is a documented judgement, so the reason must survive into report.json.

    No shipped preset suppresses DD011 (the presets tune thresholds, not silence), which is
    why the suppression is declared explicitly here rather than reached through a preset.
    """
    config = _suppress_config("long tail is the subject")

    def build(name: str, with_policy: bool) -> Path:
        root = _root(tmp_path, name, config if with_policy else TABULAR_CONFIG)
        train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i, target=1 if i < 5 else 0) for i in range(200)]
        test = [row(f"t{i:03d}", f"q{i // 4:02d}", index=200 + i, target=1 if i < 5 else 0) for i in range(60)]
        write_rows(root / "train.csv", train, COLUMNS)
        write_rows(root / "test.csv", test, COLUMNS)
        return root

    unsuppressed = run_audit(build("plain", with_policy=False))
    assert unsuppressed.by_rule("DD011"), "the fixture must actually contain the imbalance being suppressed"

    result = run_audit(build("suppressed", with_policy=True))

    outcome = result.rule("DD011")
    assert outcome.status is AuditStatus.SUPPRESSED
    assert "long tail" in (outcome.suppression_reason or "")
    assert result.by_rule("DD011") == [], "a suppressed rule must not also emit findings"
    payload = result.report.model_dump(mode="json")
    stored = next(item for item in payload["rule_outcomes"] if item["rule_id"] == "DD011")
    assert stored["status"] == "SUPPRESSED"
    assert "long tail" in stored["suppression_reason"]


def test_a_suppression_without_a_reason_is_refused(tmp_path: Path, run_audit: Any) -> None:
    config = TABULAR_CONFIG + "suppress:\n  - rule: DD011\n    reason: '   '\n"
    root = _root(tmp_path, "bad_suppression", config)
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)
    write_rows(root / "test.csv", [row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i) for i in range(20)], COLUMNS)

    with pytest.raises(DatasetDoctorError):
        run_audit(root)


def test_test28_nan_values_in_a_category_are_counted_not_crashed(tmp_path: Path, run_audit: Any) -> None:
    """Empty cells in a text column are the classic way a naive audit dies or lies."""
    root = _root(tmp_path, "nan_category")
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)]
    test = [row(f"t{i:03d}", f"q{i // 4:02d}", index=40 + i) for i in range(20)]
    for record in train[::3]:
        record["sex"] = ""
    write_rows(root / "train.csv", train, COLUMNS)
    write_rows(root / "test.csv", test, COLUMNS)

    result = run_audit(root)

    assert result.identity.num_samples == 60
    missing = [finding for finding in result.report.findings if finding.rule_id in {"DD015", "DD011", "DD010"}]
    assert missing, "the blank cells have to be attributed somewhere rather than dropped"
    assert "sex" in str([finding.location.columns for finding in missing])


def test_test29_an_empty_dataset_fails_with_a_message_not_a_traceback(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "empty")

    with pytest.raises(DatasetDoctorError) as excinfo:
        run_audit(root)

    assert str(root) in str(excinfo.value) or "No samples" in str(excinfo.value)


def test_test29b_a_header_only_table_is_audited_without_inventing_samples(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "header_only")
    write_rows(root / "train.csv", [], COLUMNS)
    write_rows(root / "test.csv", [], COLUMNS)

    with pytest.raises(DatasetDoctorError):
        run_audit(root)


def test_test30_a_train_only_dataset_can_never_be_called_safe(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "train_only")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)], COLUMNS)

    result = run_audit(root)

    assert result.report.eval_safety is EvalSafety.INCONCLUSIVE
    assert result.report.eval_safety_reasons, "INCONCLUSIVE without a reason would be a shrug"


def test_test09_a_shifted_feature_is_measured_with_effect_size(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "shifted")
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(120)]
    test = [row(f"t{i:03d}", f"q{i // 4:02d}", index=120 + i, bmi=45.0 + (i % 7) * 0.5) for i in range(60)]
    write_rows(root / "train.csv", train, COLUMNS)
    write_rows(root / "test.csv", test, COLUMNS)

    result = run_audit(root)
    findings = [finding for finding in result.by_rule("DD012") if finding.source_split == "train"]

    assert findings
    shifted = {row["column"]: row for row in findings[0].evidence["top_shifts"]}
    assert "bmi" in shifted, f"the planted shift must be named, got {sorted(shifted)}"
    assert abs(shifted["bmi"]["std_mean_diff"]) > 1.0
    assert shifted["bmi"]["psi_trigger_usable"] is True


def test_test10_identical_distributions_are_not_flagged_in_volume(tmp_path: Path, run_audit: Any) -> None:
    """The other half of TEST 9: the same thresholds on data with nothing wrong with it.

    Two splits of 120 and 60 rows drawn from the same deterministic generator differ by
    sampling noise alone. A tool that reports five columns here teaches the user to ignore it.
    """
    root = _root(tmp_path, "identical")
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(120)], COLUMNS)
    write_rows(root / "test.csv", [row(f"t{i:03d}", f"q{i // 4:02d}", index=120 + i) for i in range(60)], COLUMNS)

    result = run_audit(root)
    flagged = [finding for finding in result.by_rule("DD012") if finding.severity.rank >= Severity.MEDIUM.rank]

    assert flagged == []
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_INVALID


# ------------------------------------------------------- DD002: how splits may be laid out
def test_dd002_two_declared_splits_pointing_at_one_file_is_a_blocking_configuration(
    tmp_path: Path, run_audit: Any
) -> None:
    root = _root(tmp_path, "same_path")
    rows = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)]
    write_rows(root / "cohort.csv", rows, COLUMNS)
    (root / "dataset-doctor.yaml").write_text(
        "dataset:\n  type: tabular\nsplits:\n  train: cohort.csv\n  test: cohort.csv\npolicies: {}\n",
        encoding="utf-8",
    )

    result = run_audit(root)
    collisions = [finding for finding in result.by_rule("DD002") if finding.metadata.get("reason") == "shared_path"]

    assert collisions, "one file serving both roles means the evaluation set is the training set"
    assert collisions[0].severity is Severity.CRITICAL
    assert collisions[0].formal_impact is FormalImpact.BLOCKING


def test_dd002_a_split_read_from_a_column_is_not_reported_as_a_shared_path(tmp_path: Path, run_audit: Any) -> None:
    """One file holding every split is a layout, not the fault DD002 exists to catch.

    ``temporal.split_column`` exists for exactly this shape, so treating its shared path
    as a collision reported the declared fix as the bug.
    """
    root = _root(
        tmp_path,
        "split_column",
        "dataset:\n  type: tabular\nlabels:\n  column: target\ngroups:\n  columns: [patient_id]\n"
        "id_columns: [record_id]\ntemporal:\n  column: collected_at\n  split_column: split\npolicies: {}\n",
    )
    rows: list[dict[str, Any]] = []
    for index in range(40):
        base = row(f"r{index:03d}", f"p{index // 8:02d}", index=index)
        base["collected_at"] = f"2024-{index % 12 + 1:02d}-{index % 27 + 1:02d}"
        base["split"] = "train" if index < 30 else "test"
        rows.append(base)
    write_rows(root / "cohort.csv", rows, [*COLUMNS, "collected_at", "split"])

    result = run_audit(root)

    assert result.identity.split_sizes == {"train": 30, "test": 10}
    assert [finding for finding in result.by_rule("DD002") if finding.metadata.get("reason") == "shared_path"] == []


# ------------------------------------------------------------------- DD021: PII candidates
def test_dd021_an_iso_date_column_is_not_called_a_phone_number(tmp_path: Path, run_audit: Any) -> None:
    """The pattern that catches '13800138000' also catches '2024-01-15'.

    Both halves are in one fixture on purpose: the phone column is the control that proves
    the date veto did not simply switch the rule off.
    """
    root = _root(tmp_path, "pii")
    rows: list[dict[str, Any]] = []
    for index in range(40):
        base = row(f"r{index:03d}", f"p{index // 8:02d}", index=index)
        base["collected_at"] = f"202{index % 4}-{index % 12 + 1:02d}-{index % 27 + 1:02d}"
        base["contact"] = f"1380013{index:04d}"
        rows.append(base)
    columns = [*COLUMNS, "collected_at", "contact"]
    write_rows(root / "train.csv", rows[:30], columns)
    write_rows(root / "test.csv", rows[30:], columns)

    result = run_audit(root)
    hits = {(finding.evidence["column"], finding.evidence["pattern"]) for finding in result.by_rule("DD021")}

    assert ("contact", "phone_like") in hits, f"the control must still fire, got {sorted(hits)}"
    assert ("collected_at", "phone_like") not in hits


def _pii_config_rows(root: Path, matches: dict[int, str]) -> list[str]:
    """Train rows 0-39 plus a ``contact`` column holding phone-like values at ``matches``.

    40 rows with 2 planted values is exactly the 0.05 default ratio, so the same
    fixture answers "does the boundary fire?" and "does one fewer match stay quiet?"
    """
    columns = [*COLUMNS, "contact"]
    rows: list[dict[str, Any]] = []
    for index in range(40):
        base = row(f"r{index:03d}", f"p{index // 8:02d}", index=index)
        base["contact"] = matches.get(index, "masked")
        rows.append(base)
    write_rows(root / "train.csv", rows[:30], columns)
    write_rows(root / "test.csv", rows[30:], columns)
    return columns


def test_dd021_the_min_match_ratio_boundary_is_inclusive_and_wired(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "pii_boundary")
    _pii_config_rows(root, {5: "13800138000", 19: "13800138001"})

    hits = {(f.evidence["column"], f.evidence["pattern"]) for f in run_audit(root).by_rule("DD021")}
    assert ("contact", "phone_like") in hits, "2/40 matches hits the 0.05 threshold from above"

    quiet_root = _root(
        tmp_path,
        "pii_boundary_raised",
        TABULAR_CONFIG.replace(
            "policies: {}",
            "policies:\n  pii_scan:\n    min_match_ratio: 0.1",
        ),
    )
    _pii_config_rows(quiet_root, {5: "13800138000", 19: "13800138001"})
    assert run_audit(quiet_root).by_rule("DD021") == [], "min_match_ratio must be policy-wired"

    below_root = _root(tmp_path, "pii_below")
    _pii_config_rows(below_root, {5: "13800138000"})
    low = run_audit(below_root).by_rule("DD021")
    assert [f for f in low if f.evidence["column"] == "contact"] == [], "1/40 is below 0.05"


def test_dd021_reports_one_finding_per_column_and_pattern_across_splits(tmp_path: Path, run_audit: Any) -> None:
    """A17: the ``seen`` set attributes a shared column to one split; the ratio is per split.

    '2 of 10' must not silently become '2 of 40' - the number in the report is the
    number one reviewer will check in one file.
    """
    columns = [*COLUMNS, "contact"]
    root = tmp_path / "pii_shared"
    root.mkdir(parents=True, exist_ok=True)
    for split_name, count, hits in (("train", 20, (3, 11)), ("test", 10, (2, 7))):
        rows: list[dict[str, Any]] = []
        for index in range(count):
            base = row(f"{split_name[0]}{index:03d}", f"{split_name[0]}p{index // 8:02d}", index=index)
            base["contact"] = f"1380013{index:04d}" if index in hits else "masked"
            rows.append(base)
        write_rows(root / f"{split_name}.csv", rows, columns)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")

    phone_findings = [
        finding
        for finding in run_audit(root).by_rule("DD021")
        if finding.evidence["pattern"] == "phone_like" and finding.evidence["column"] == "contact"
    ]
    assert len(phone_findings) == 1, f"the dedup must collapse the second split, got {len(phone_findings)}"
    only = phone_findings[0]
    assert only.source_split == "test", "attribution goes to the first split scanned (alphabetical)"
    assert only.evidence["matching_rows"] == 2
    assert only.evidence["non_null_rows"] == 10, "the ratio is per split, not pooled across them"


def test_dd021_disabled_is_not_run_and_never_a_silent_pass(tmp_path: Path, run_audit: Any) -> None:
    root = _root(
        tmp_path,
        "pii_off",
        TABULAR_CONFIG.replace(
            "policies: {}",
            "policies:\n  pii_scan:\n    enabled: false",
        ),
    )
    _pii_config_rows(root, {5: "13800138000", 19: "13800138001"})

    outcome = run_audit(root).rule("DD021")
    assert outcome is not None and outcome.status is AuditStatus.NOT_RUN
    assert outcome.skip_reason == "policy pii_scan.enabled = false"


# ------------------------------------------------------------------ DD013: label shift
def _label_split(target_ones: int, count: int, prefix: str, start: int) -> list[dict[str, Any]]:
    return [
        row(f"{prefix}{i:03d}", f"{prefix}p{i // 8:02d}", index=start + i, target=1 if i < target_ones else 0)
        for i in range(count)
    ]


def test_dd013_a_shifted_test_label_distribution_is_measured_with_effect_size(tmp_path: Path, run_audit: Any) -> None:
    """train 30/30 vs test 3/17: TV distance 0.350, straight past the HIGH floor of 0.30."""
    root = _root(tmp_path, "label_shift")
    write_rows(root / "train.csv", _label_split(30, 60, "t", 0), COLUMNS)
    write_rows(root / "test.csv", _label_split(17, 20, "e", 60), COLUMNS)

    findings = run_audit(root).by_rule("DD013")
    assert len(findings) == 1
    shift = findings[0]
    assert shift.severity is Severity.HIGH
    assert shift.status is AuditStatus.WARNING
    assert shift.formal_impact is FormalImpact.POTENTIAL
    assert (shift.source_split, shift.target_split) == ("train", "test")
    assert shift.evidence["tv_distance"] == pytest.approx(0.35, abs=1e-4)
    assert shift.evidence["threshold"] == 0.05
    top = shift.evidence["largest_movers"][0]
    assert top["class"] == "1" and top["train_share"] == 0.5 and top["test_share"] == 0.85


def test_dd013_a_small_shift_is_low_and_respects_a_raised_threshold(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "label_drift_small")
    write_rows(root / "train.csv", _label_split(25, 50, "t", 0), COLUMNS)
    write_rows(root / "test.csv", _label_split(29, 50, "e", 50), COLUMNS)

    findings = run_audit(root).by_rule("DD013")
    assert len(findings) == 1 and findings[0].severity is Severity.LOW, "TV 0.08 sits in [0.05, 0.15)"

    strict_root = _root(
        tmp_path,
        "label_drift_strict",
        TABULAR_CONFIG.replace(
            "policies: {}",
            "policies:\n  label_shift:\n    min_tv_distance: 0.1",
        ),
    )
    write_rows(strict_root / "train.csv", _label_split(25, 50, "t", 0), COLUMNS)
    write_rows(strict_root / "test.csv", _label_split(29, 50, "e", 50), COLUMNS)
    assert run_audit(strict_root).by_rule("DD013") == [], "min_tv_distance must be policy-wired"


# ------------------------------------------------------------------ DD020: provenance
def test_dd020_undeclared_provenance_is_advisory_and_what_is_declared_is_reported(
    tmp_path: Path, run_audit: Any
) -> None:
    root = _root(tmp_path, "prov_none")
    write_rows(root / "train.csv", _label_split(15, 30, "t", 0), COLUMNS)
    write_rows(root / "test.csv", _label_split(5, 10, "e", 30), COLUMNS)

    findings = run_audit(root).by_rule("DD020")
    assert len(findings) == 1
    assert findings[0].severity is Severity.LOW
    assert findings[0].status is AuditStatus.WARNING
    assert findings[0].formal_impact is FormalImpact.NONE, "provenance never invalidates an evaluation"
    assert findings[0].evidence["missing"] == ["source", "version", "license", "download_date"]

    full_root = _root(
        tmp_path,
        "prov_full",
        TABULAR_CONFIG + "provenance:\n"
        "  source: internal-export\n"
        "  version: '1.2'\n"
        "  license: CC-BY-4.0\n"
        "  download_date: '2026-05-01'\n",
    )
    write_rows(full_root / "train.csv", _label_split(15, 30, "t", 0), COLUMNS)
    write_rows(full_root / "test.csv", _label_split(5, 10, "e", 30), COLUMNS)
    assert run_audit(full_root).by_rule("DD020") == []

    partial_root = _root(tmp_path, "prov_partial", TABULAR_CONFIG + "provenance:\n  source: internal-export\n")
    write_rows(partial_root / "train.csv", _label_split(15, 30, "t", 0), COLUMNS)
    write_rows(partial_root / "test.csv", _label_split(5, 10, "e", 30), COLUMNS)
    partial = run_audit(partial_root).by_rule("DD020")
    assert len(partial) == 1
    assert partial[0].severity is Severity.INFO and partial[0].status is AuditStatus.PASS
    assert partial[0].evidence["missing"] == ["version", "license", "download_date"]
    assert partial[0].evidence["declared"] == {"source": "internal-export"}


# ------------------------------------------------------------------ DD017: image properties
def _tone_tiles(seed_base: int, count: int, shade: str) -> list[Any]:
    import numpy as np

    tiles = []
    for index in range(count):
        rng = np.random.default_rng(seed_base + index)
        pixels = rng.integers(0, 256, (8, 8), dtype=np.uint8)[..., None].repeat(3, axis=2)
        if shade == "dark":
            pixels = (pixels * 0.25).astype(np.uint8)
        else:
            pixels = np.clip(pixels.astype(int) + 150, 0, 255).astype(np.uint8)
        tiles.append(pixels)
    return tiles


def test_dd017_a_brighter_test_split_is_reported_as_property_shift(images: Any, run_audit: Any) -> None:
    root = images(
        "props_shift", train={"bruise": _tone_tiles(101, 8, "dark")}, test={"bruise": _tone_tiles(201, 8, "bright")}
    )

    result = run_audit(root)
    findings = result.by_rule("DD017")
    assert len(findings) == 1
    shift = findings[0]
    assert shift.status is AuditStatus.WARNING
    assert shift.formal_impact is FormalImpact.POTENTIAL, (
        "a preprocessing artefact is task judgement, not a blocked eval"
    )
    assert shift.evidence["min_std_mean_diff"] == 0.5
    props = {row["property"]: row for row in shift.evidence["properties"]}
    assert "brightness" in props, f"expected brightness in the shifted set, got {sorted(props)}"
    assert abs(props["brightness"]["std_mean_diff"]) >= 1.5
    assert shift.severity is Severity.MEDIUM
    assert result.rule("DD021").status is AuditStatus.UNSUPPORTED, "PII scanning covers table columns"


def test_dd017_without_decoded_pixels_answers_inconclusive_not_safe(images: Any, run_audit: Any) -> None:
    root = images(
        "props_meta", train={"bruise": _tone_tiles(301, 8, "dark")}, test={"bruise": _tone_tiles(401, 8, "bright")}
    )

    outcome = run_audit(root, fingerprint="metadata").rule("DD017")
    assert outcome is not None and outcome.status is AuditStatus.INCONCLUSIVE
    assert "full" in (outcome.skip_reason or ""), "the message must point at the fix"


def test_dd017_is_unsupported_on_tabular_data(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "props_tabular")
    write_rows(root / "train.csv", _label_split(15, 30, "t", 0), COLUMNS)
    write_rows(root / "test.csv", _label_split(5, 10, "e", 30), COLUMNS)
    assert run_audit(root).rule("DD017").status is AuditStatus.UNSUPPORTED


# ------------------------------------------------------------------ DD001: identity
def test_dd001_asserts_the_identity_baseline_every_other_finding_cites(tmp_path: Path, run_audit: Any) -> None:
    root = _root(tmp_path, "identity")
    write_rows(root / "train.csv", _label_split(15, 30, "t", 0), COLUMNS)
    write_rows(root / "test.csv", _label_split(5, 10, "e", 30), COLUMNS)

    result = run_audit(root)
    findings = result.by_rule("DD001")
    assert len(findings) == 1, "exactly one informational identity finding"
    only = findings[0]
    assert only.severity is Severity.INFO and only.status is AuditStatus.PASS
    assert only.formal_impact is FormalImpact.NONE
    assert only.evidence["dataset_id"] == result.identity.dataset_id
    assert only.evidence["split_sizes"] == {"train": 30, "test": 10}
    assert len(only.evidence["manifest_hash"]) == 32
