"""DD005 cross-split locators name the rows they claim to.

Found by the second real-world acceptance (UCI HAR): 0.1.0 emitted
``affected_sample_ids`` as ``f"{split}:{range(count)}"`` sequences - plain
counter positions unrelated to where the entity's rows actually sit. On a
fixture whose entity rows are scattered, every pointer named the wrong row,
and the [:200] cut carried no truncation flag. These tests pin both halves.
"""

from __future__ import annotations

from typing import Any

from conftest import row

from dataset_doctor_audit.models import FormalImpact, Severity


def _audit_scattered_leak(tabular: Any, run_audit: Any) -> tuple[Any, Any]:
    # Entity "7" sits at train rows 1 and 3 (not 0 and 1) and test row 2.
    train = [
        row("r0", "5"),
        row("r1", "7"),
        row("r2", "6"),
        row("r3", "7"),
        row("r4", "8"),
    ]
    test = [row("r5", "9"), row("r6", "11"), row("r7", "7"), row("r8", "12")]
    root = tabular("dd005_scattered", train=train, test=test)
    return root, run_audit(root)


def test_test05_locator_names_the_rows_that_hold_the_entity(tabular: Any, run_audit: Any) -> None:
    _, result = _audit_scattered_leak(tabular, run_audit)
    findings = result.by_rule("DD005")
    assert findings, "a shared entity must be reported"
    finding = findings[0]
    assert finding.severity is Severity.CRITICAL
    assert finding.formal_impact is FormalImpact.BLOCKING
    ids = finding.metadata["affected_sample_ids"]
    assert sorted(ids) == ["test:2", "train:1", "train:3"]
    assert finding.metadata["affected_sample_ids_truncated"] is False


def test_locator_ids_point_at_rows_a_reviewer_can_open(tabular: Any, run_audit: Any) -> None:
    """Every emitted locator must actually carry the leaked entity."""
    import pandas as pd

    root, result = _audit_scattered_leak(tabular, run_audit)
    finding = result.by_rule("DD005")[0]
    for locator in finding.metadata["affected_sample_ids"]:
        split, index = locator.split(":")
        frame = pd.read_csv(root / f"{split}.csv")
        assert str(frame["patient_id"].iloc[int(index)]) == "7", locator


def test_truncation_is_declared_not_silent(tabular: Any, run_audit: Any) -> None:
    # 150 train rows + 100 test rows of one entity = 250 affected > 200 kept.
    train = [row(f"t{i:03d}", "leaky", index=i) for i in range(150)]
    test = [row(f"e{i:03d}", "leaky", index=500 + i) for i in range(100)]
    other = [row("x0", "clean-one"), row("x1", "clean-two")]
    root = tabular("dd005_trunc", train=train + other, test=test)
    result = run_audit(root)
    finding = result.by_rule("DD005")[0]
    assert finding.affected_count == 250
    ids = finding.metadata["affected_sample_ids"]
    assert len(ids) == 200
    assert finding.metadata["affected_sample_ids_truncated"] is True
