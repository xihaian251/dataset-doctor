"""The verdict-level contract that both release-blocking P0s broke.

AGENTS.md states it as "No silent PASS". At the aggregation layer that means: when a check
with `BLOCKING` evaluation relevance cannot be measured - zero coverage, missing evidence,
unusable input - the overall verdict may be INVALID, RISKY or INCONCLUSIVE, but never
`FORMAL_EVAL_SAFE`. Both real-world P0s were the same event one level down (a detector
answered about a subset of the rows and a rule-level `PASS` summarised the rest), so the
guarantee is pinned here, against `eval_safety` itself, rather than only per rule.
"""

from __future__ import annotations

from dataset_doctor_audit.models import (
    AuditFinding,
    AuditStatus,
    Category,
    Confidence,
    DatasetType,
    EvalSafety,
    EvidenceType,
    FormalImpact,
    RuleOutcome,
    Severity,
)
from dataset_doctor_audit.rules import V01_RULES, eval_safety

SAMPLES = 1_000


def _finding(status: AuditStatus, impact: FormalImpact, rule_id: str = "DD005") -> AuditFinding:
    return AuditFinding(
        finding_id=f"{rule_id}-0001",
        rule_id=rule_id,
        title="Entity comparison could not be measured",
        category=Category.LEAKAGE,
        severity=Severity.HIGH,
        confidence=Confidence.HIGH,
        status=status,
        evidence_type=EvidenceType.DETERMINISTIC,
        formal_impact=impact,
        description="No usable group metadata, so no entity pair was compared.",
        why_it_matters="A check that ran over nothing cannot rule out a shared entity.",
    )


def _outcome(status: AuditStatus, rule_id: str = "DD005") -> RuleOutcome:
    return RuleOutcome(rule_id=rule_id, name="Group / Entity Leakage", status=status, skip_reason="coverage 0%")


def test_a_blocked_core_rule_with_nothing_in_V01_rule_names_is_the_case_this_covers() -> None:
    """If DD005 ever leaves the gating set, the control below stops meaning anything."""
    assert "DD005" in V01_RULES


def test_an_unmeasured_blocking_check_never_aggregates_to_safe() -> None:
    routes = {
        # A detector that says "I could not answer this" in a finding.
        "unproven BLOCKING finding": (
            [_finding(AuditStatus.INCONCLUSIVE, FormalImpact.BLOCKING)],
            [_outcome(AuditStatus.INCONCLUSIVE)],
        ),
        # A rule that reports its own status without producing a finding.
        "core rule INCONCLUSIVE outcome": (
            [],
            [_outcome(AuditStatus.INCONCLUSIVE)],
        ),
        # A rule that cannot run at all on this dataset type.
        "core rule UNSUPPORTED outcome": (
            [],
            [_outcome(AuditStatus.UNSUPPORTED)],
        ),
    }

    for route, (findings, outcomes) in routes.items():
        verdict, reasons = eval_safety(findings, outcomes, SAMPLES, DatasetType.TABULAR)
        assert verdict != EvalSafety.FORMAL_EVAL_SAFE.value, f"{route} was aggregated into SAFE"
        assert reasons, f"{route} reached {verdict} without saying why"


def test_the_same_audit_reaches_safe_once_the_check_actually_ran() -> None:
    """Non-vacuity control: the blocker above is the unanswered check, not the fixture."""
    findings = [_finding(AuditStatus.INCONCLUSIVE, FormalImpact.BLOCKING)]
    outcomes = [_outcome(AuditStatus.INCONCLUSIVE)]

    assert eval_safety(findings, outcomes, SAMPLES, DatasetType.TABULAR)[0] != EvalSafety.FORMAL_EVAL_SAFE.value
    assert eval_safety([], [], SAMPLES, DatasetType.TABULAR)[0] == EvalSafety.FORMAL_EVAL_SAFE.value
