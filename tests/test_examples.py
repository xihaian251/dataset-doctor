"""The checked-in example datasets are a regression contract, not documentation.

``examples/RESULTS.md`` records what the tool said once. These tests make the rest of the
repository keep that promise: the controls stay quiet and each isolated fault still lights
up its own rule. They run against the committed fixtures, so a detector that drifts fails
here before it fails a README claim.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from dataset_doctor_audit import audit_dataset
from dataset_doctor_audit.models import EvalSafety, FormalImpact

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"

pytestmark = pytest.mark.skipif(not EXAMPLES.is_dir(), reason="example fixtures are not present")


def _audit(name: str) -> Any:
    return audit_dataset(EXAMPLES / name)


@pytest.mark.parametrize("name", ["safe_tabular", "safe_image"])
def test_a_control_fixture_stays_out_of_the_verdict_business(name: str) -> None:
    """Nothing is planted here, so every finding is a false positive by definition."""
    result = _audit(name)

    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_SAFE
    assert [
        finding
        for finding in result.report.findings
        if finding.formal_impact is FormalImpact.BLOCKING and finding.status.value in {"FAIL", "WARNING"}
    ] == []


def test_the_fixture_collection_covers_both_modalities_and_every_headline_rule() -> None:
    """The collection would stop being useful if someone deleted half of it."""
    built = {path.name for path in EXAMPLES.iterdir() if (path / "dataset-doctor.yaml").exists()}

    assert built == {
        "safe_tabular",
        "unsafe_duplicate",
        "unsafe_group_leakage",
        "unsafe_label_conflict",
        "unsafe_target_leakage",
        "shifted_tabular",
        "leaky_patient_dataset",
        "safe_image",
        "unsafe_image_duplicate",
        "unsafe_near_duplicate",
        "unsafe_image_label_conflict",
        "corrupt_image",
        "leaky_image_dataset",
    }


def test_shared_entities_are_found_without_any_row_being_a_duplicate() -> None:
    """The flagship claim: leakage a dedup pass cannot see."""
    result = _audit("unsafe_group_leakage")

    assert result.by_rule("DD003") == [], "no row in this fixture is an exact duplicate"
    entities = result.by_rule("DD005")
    assert entities, "four patients appear on both sides of the boundary"
    assert entities[0].formal_impact is FormalImpact.BLOCKING


def test_distribution_shift_is_reported_as_a_risk_and_not_as_a_blocked_evaluation() -> None:
    """A data quality issue must not be dressed up as an evaluation validity issue."""
    result = _audit("shifted_tabular")

    shifted = result.by_rule("DD012")
    assert shifted, "the test population was rebuilt to be measurably different"
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_RISKY
    assert result.by_rule("DD003") == []
    assert result.by_rule("DD005") == []
    assert result.exit_code() == 0, "shift alone must not fail a CI gate that leakage would fail"


def test_an_fdr_flag_never_lands_on_another_columns_evidence() -> None:
    """Benjamini-Hochberg runs over p-values in column order while the evidence rows are
    sorted by effect size, so the two orders have to be reconciled deliberately.

    A slip of one index calls a column significant on another column's p-value, which is the
    kind of wrong number that survives review forever because it looks like a statistic.
    """
    result = _audit("shifted_tabular")

    finding = result.by_rule("DD012")[0]
    rows = [row for row in finding.evidence["top_shifts"] if "ks_pvalue" in row]
    assert len(rows) >= 2, "the correction needs more than one column to mean anything"
    alpha = finding.evidence["thresholds"]["fdr_alpha"]
    for row in rows:
        assert row["fdr_significant"] is (row["adjusted_pvalue"] <= alpha), f"{row['column']} contradicts itself"
    flags = [row["fdr_significant"] for row in sorted(rows, key=lambda row: row["ks_pvalue"])]
    assert flags == sorted(flags, reverse=True), "a weaker p-value cannot be significant while a stronger one is not"
    assert any(flags) and not all(flags), "this fixture needs one significant and one underpowered column"


def test_the_perceptual_hash_finds_a_pair_that_no_checksum_can_see() -> None:
    result = _audit("unsafe_near_duplicate")

    assert result.by_rule("DD003") == [], "the pairs differ at the byte level by construction"
    assert result.by_rule("DD004"), "only a perceptual hash can report this"


def test_a_conflicting_label_on_identical_content_is_a_blocking_finding() -> None:
    result = _audit("unsafe_label_conflict")

    conflicts = result.by_rule("DD009")
    assert conflicts
    assert conflicts[0].formal_impact is FormalImpact.BLOCKING
    assert conflicts[0].evidence["groups"], "the conflicting groups must be listed, not counted only"


def test_the_mixed_clinical_fixture_catches_the_temporal_inversion_too() -> None:
    """Train collected in 2026 scored on test collected in 2024, and DD006 has to say so."""
    result = _audit("leaky_patient_dataset")

    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID
    assert result.by_rule("DD006")
    assert result.exit_code() == 1


def test_the_example_build_script_still_produces_the_whole_collection(tmp_path: Path) -> None:
    """``examples/build.py`` regenerates ``RESULTS.md``; a broken builder must fail loudly.

    It writes fixtures into a temporary directory, so the committed bytes are never at
    risk, but every builder in the file still has to run end to end.
    """
    import subprocess
    import sys

    outcome = subprocess.run(
        [sys.executable, str(EXAMPLES / "build.py"), "--output", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert outcome.returncode == 0, outcome.stderr[-2000:]

    built = {path.name for path in tmp_path.iterdir() if (path / "dataset-doctor.yaml").exists()}
    committed = {path.name for path in EXAMPLES.iterdir() if (path / "dataset-doctor.yaml").exists()}
    assert built == committed, "the builder must reproduce exactly the checked-in collection"
