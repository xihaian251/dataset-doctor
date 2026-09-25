"""DD005/DD006 must not turn "nothing was measurable" into "checked and clean".

Found by the third real-world acceptance (UCI Online Retail II, 1,067,371 rows, 22.77 % of
them with no CustomerID). Released 0.1.0 skipped entity values it could not use without
counting them, and skipped a time column that never parsed at all, so both rules answered
PASS on data they had not compared - and the verdict printed FORMAL_EVAL_SAFE. The
absent-column path already said "This is not a PASS."; these paths now say the same thing.
"""

from __future__ import annotations

from typing import Any

from conftest import row

from dataset_doctor_audit.models import AuditStatus, EvalSafety, FormalImpact, Severity

GROUPS_ONLY = """\
dataset:
  type: tabular
groups:
  columns: [patient_id]
id_columns: [record_id]
policies: {}
"""

TEMPORAL_ONLY = """\
dataset:
  type: tabular
temporal:
  column: measured_at
  train_before_test: true
policies: {}
"""


def test_group_column_with_no_usable_values_is_not_a_pass(tabular: Any, run_audit: Any) -> None:
    train = [row(f"t{i}", "", index=i) for i in range(8)]
    test = [row(f"e{i}", "", index=100 + i) for i in range(6)]
    root = tabular("dd005_zero_coverage", config=GROUPS_ONLY, train=train, test=test)
    result = run_audit(root)

    outcome = result.rule("DD005")
    assert outcome is not None
    assert outcome.status is AuditStatus.INCONCLUSIVE
    findings = result.by_rule("DD005")
    assert findings, "an unmeasurable entity column has to be reported, not hidden"
    finding = findings[0]
    assert finding.formal_impact is FormalImpact.BLOCKING
    assert finding.evidence["rows_checked"] == 0
    assert finding.evidence["rows_without_entity"] == 14
    # the whole point: zero evidence may not certify a formal evaluation
    assert result.report.eval_safety is not EvalSafety.FORMAL_EVAL_SAFE


def test_partial_entity_coverage_is_stated_on_the_clean_branch(tabular: Any, run_audit: Any) -> None:
    train = [row(f"t{i}", f"p{i % 2}", index=i) for i in range(8)] + [
        row(f"tb{i}", "", index=200 + i) for i in range(4)
    ]
    test = [row(f"e{i}", f"q{i}", index=100 + i) for i in range(8)] + [
        row(f"eb{i}", "", index=300 + i) for i in range(4)
    ]
    covered = tabular("dd005_full", config=GROUPS_ONLY, train=train[:8], test=test[:8])
    partial = tabular("dd005_partial", config=GROUPS_ONLY, train=train, test=test)

    full_result = run_audit(covered)
    assert full_result.by_rule("DD005") == [], "a disjoint, fully covered group column stays clean"

    result = run_audit(partial)
    findings = result.by_rule("DD005")
    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity is Severity.LOW
    assert finding.formal_impact is FormalImpact.NONE
    assert finding.status is AuditStatus.WARNING
    assert finding.evidence["group_column_rows"] == 24
    assert finding.evidence["rows_without_entity"] == 8
    assert finding.evidence["entity_coverage_ratio"] == 0.6667
    assert "proven" in finding.why_it_matters.lower() or "weaker" in finding.why_it_matters.lower()
    # disclosing the gap must not manufacture a risk verdict: the advisory is honest about the
    # limit without asserting a leakage that was not observed, so it cannot steer the verdict.
    assert not any("DD005" in reason for reason in result.report.eval_safety_reasons)


def test_entity_leakage_finding_keeps_its_counts_and_adds_coverage(tabular: Any, run_audit: Any) -> None:
    train = [row(f"t{i}", "shared" if i < 3 else f"p{i}", index=i) for i in range(10)] + [
        row(f"tb{i}", "", index=400 + i) for i in range(5)
    ]
    test = [row(f"e{i}", "shared" if i < 2 else f"q{i}", index=100 + i) for i in range(10)] + [
        row(f"eb{i}", "", index=500 + i) for i in range(5)
    ]
    root = tabular("dd005_leak_with_gaps", config=GROUPS_ONLY, train=train, test=test)
    result = run_audit(root)
    finding = next(f for f in result.by_rule("DD005") if f.status is AuditStatus.FAIL)
    assert finding.severity is Severity.CRITICAL
    assert finding.formal_impact is FormalImpact.BLOCKING
    # the confirmed overlap and the coverage limit are both in the same finding
    assert finding.evidence["entities"] == 1
    assert finding.evidence["rows_without_entity"] == 10
    assert finding.evidence["entity_coverage_ratio"] == 0.6667
    assert "cannot be attributed" in finding.description
    assert result.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID


def test_time_column_that_never_parses_is_not_a_pass(tabular: Any, run_audit: Any) -> None:
    def timed(record_id: str, when: str, index: int) -> dict[str, Any]:
        base = row(record_id, f"p{index}", index=index)
        base["measured_at"] = when
        return base

    train = [timed(f"t{i}", "not-a-date", i) for i in range(6)]
    test = [timed(f"e{i}", "also-not-a-date", 100 + i) for i in range(6)]
    root = tabular("dd006_unparseable", config=TEMPORAL_ONLY, train=train, test=test)
    result = run_audit(root)

    outcome = result.rule("DD006")
    assert outcome is not None
    assert outcome.status is AuditStatus.INCONCLUSIVE
    findings = result.by_rule("DD006")
    assert findings, "an unmeasurable temporal boundary has to be reported, not hidden in a skip reason"
    # BLOCKING + INCONCLUSIVE is exactly the input the verdict treats as "flagged as potentially
    # invalidating, not confirmed", so an unmeasurable boundary can no longer read as a clean check.
    # The end-to-end verdict gate is asserted on the DD005 zero-coverage case above; on this tiny
    # fixture DD007/DD012 also stand between it and SAFE.
    assert findings[0].formal_impact is FormalImpact.BLOCKING
    assert findings[0].status is AuditStatus.INCONCLUSIVE
    assert "not a PASS" in findings[0].description
    assert findings[0].evidence["parseable_timestamps"] == 0


def test_temporal_boundary_that_only_one_side_can_answer_is_not_a_pass(tabular: Any, run_audit: Any) -> None:
    """Train parses, test does not: there is no pair to compare, so ordering is unknown."""

    def timed(record_id: str, when: str, index: int) -> dict[str, Any]:
        base = row(record_id, f"p{index}", index=index)
        base["measured_at"] = when
        return base

    train = [timed(f"t{i}", f"2020-01-{i + 1:02d} 08:00", i) for i in range(6)]
    test = [timed(f"e{i}", "also-not-a-date", 100 + i) for i in range(6)]
    root = tabular("dd006_test_side_unparseable", config=TEMPORAL_ONLY, train=train, test=test)
    result = run_audit(root)

    outcome = result.rule("DD006")
    assert outcome is not None
    assert outcome.status is AuditStatus.INCONCLUSIVE
    assert result.by_rule("DD006"), "one-sided evidence must not be printed as a clean check"


def test_partially_parseable_time_column_still_reaches_a_verdict(tabular: Any, run_audit: Any) -> None:
    """One bad timestamp is a limitation, not a refusal: the comparison still runs."""

    def timed(record_id: str, when: str, index: int) -> dict[str, Any]:
        base = row(record_id, f"p{index}", index=index)
        base["measured_at"] = when
        return base

    train = [timed(f"t{i}", f"2020-01-{i + 1:02d} 08:00", i) for i in range(5)] + [timed("tbad", "unreadable", 90)]
    test = [timed(f"e{i}", f"2021-01-{i + 1:02d} 08:00", 100 + i) for i in range(5)]
    root = tabular("dd006_mostly_parseable", config=TEMPORAL_ONLY, train=train, test=test)
    result = run_audit(root)
    outcome = result.rule("DD006")
    assert outcome is not None
    assert outcome.status is AuditStatus.PASS
    assert result.by_rule("DD006") == []
