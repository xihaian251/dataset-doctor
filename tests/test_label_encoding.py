"""One class written two ways is not a label conflict.

Found by the first real-world acceptance run (UCI Adult, published 0.1.0): the two
official files spell their classes differently - `<=50K` in `adult.data`, `<=50K.` in
`adult.test` - and that single punctuation difference reached the report as a CRITICAL
label conflict, a HIGH "label distribution shift" of 1.000 and an MEDIUM schema drift,
while the cross-split duplication it was hiding went unreported.

These tests pin the *claims*, not the verdict: severity, status and formal impact are
asserted unchanged, because neutralising a false statement must not neutralise a real
one. Spec TEST register: this file adds no TEST id; it guards the wording of DD009 and
DD013 evidence.
"""

from __future__ import annotations

from typing import Any

from dataset_doctor_audit.models import AuditStatus, EvalSafety, FormalImpact, Severity

CONFIG = """\
dataset:
  type: tabular
labels:
  column: income
id_columns: [row_id]
policies: {}
"""

COLUMNS = ["row_id", "age", "income"]


def rec(row_id: str, age: int, income: str) -> dict[str, Any]:
    return {"row_id": row_id, "age": age, "income": income}


def one_class_two_ways(tabular: Any, run_audit: Any) -> Any:
    """Ten rows repeated across the split boundary as `x` / `x.`, plus one real conflict."""
    train = [rec(f"tr{i:03d}", i, "a" if i % 2 == 0 else "b") for i in range(1, 11)]
    train.append(rec("tr011", 11, "b"))
    test = [rec(f"te{i:03d}", i, "a." if i % 2 == 0 else "b.") for i in range(1, 11)]
    test.append(rec("te011", 11, "a."))
    return run_audit(tabular("encoding", config=CONFIG, columns=COLUMNS, train=train, test=test))


def test_punctuation_only_label_difference_is_called_an_encoding_difference(tabular: Any, run_audit: Any) -> None:
    result = one_class_two_ways(tabular, run_audit)

    conflicts = result.by_rule("DD009")
    assert len(conflicts) == 1
    finding = conflicts[0]
    assert "11 content group(s)" in finding.description
    assert "10 of these group(s)" in finding.description
    assert "one class written two ways" in finding.description
    assert finding.evidence["encoding_only_groups"] == 10
    pairs = {tuple(entry["labels"]) for entry in finding.evidence["encoding_only_labels"]}
    assert pairs, "the evidence names the spellings it judged equivalent"
    assert pairs <= {("a", "a."), ("b", "b.")}, "only punctuation may be called punctuation"
    assert ("a.", "b") not in pairs, "the real conflict is not one of them"


def test_an_encoding_difference_still_blocks_the_evaluation_with_the_same_severity(
    tabular: Any, run_audit: Any
) -> None:
    """The wording is the fix. Nothing about the consequence may soften.

    The copies genuinely cross the split boundary and the test labels genuinely do not
    match the training vocabulary, so the evaluation stays invalid; saying *why* changed.
    """
    result = one_class_two_ways(tabular, run_audit)

    finding = result.by_rule("DD009")[0]
    assert finding.severity is Severity.CRITICAL
    assert finding.status is AuditStatus.FAIL
    assert finding.formal_impact is FormalImpact.BLOCKING
    assert finding.metadata["scope"] == "cross_split"
    assert finding.affected_count == 22
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID
    assert result.exit_code() == 1


def test_a_real_conflict_is_not_relabelled_as_an_encoding_difference(tabular: Any, run_audit: Any) -> None:
    train = [rec(f"tr{i:03d}", i, "a") for i in range(1, 6)]
    test = [rec(f"te{i:03d}", i, "b") for i in range(1, 6)]
    result = run_audit(tabular("genuine", config=CONFIG, columns=COLUMNS, train=train, test=test))

    conflicts = result.by_rule("DD009")
    assert conflicts, "the same features under 'a' and 'b' is a conflict on any reading"
    assert all("one class written two ways" not in finding.description for finding in conflicts)
    assert sum(finding.evidence["encoding_only_groups"] for finding in conflicts) == 0


def test_disjoint_label_vocabularies_are_reported_as_a_vocabulary_difference(tabular: Any, run_audit: Any) -> None:
    result = one_class_two_ways(tabular, run_audit)

    shifts = result.by_rule("DD013")
    assert len(shifts) == 1
    finding = shifts[0]
    assert "total variation 1.000" in finding.description
    assert "No label value appears in both splits" in finding.description
    assert finding.evidence["common_support_classes"] == 0
    assert finding.severity is Severity.HIGH, "the number stays, only its interpretation changes"
    assert finding.formal_impact is FormalImpact.POTENTIAL


def test_a_shift_between_shared_classes_keeps_the_plain_claim(tabular: Any, run_audit: Any) -> None:
    train = [rec(f"tr{i:03d}", i, "a" if i % 2 == 0 else "b") for i in range(1, 41)]
    test = [rec(f"te{i:03d}", i, "a" if i % 4 else "b") for i in range(41, 61)]
    result = run_audit(tabular("shared", config=CONFIG, columns=COLUMNS, train=train, test=test))

    shifts = result.by_rule("DD013")
    assert len(shifts) == 1
    finding = shifts[0]
    assert "No label value appears in both splits" not in finding.description
    assert finding.evidence["common_support_classes"] == 2
