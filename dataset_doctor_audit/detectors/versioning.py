"""DD018 version drift and DD019 split drift, derived from a snapshot diff.

These rules only exist when the user supplies a baseline (`audit --baseline ds_x` or
`dataset-doctor-audit diff`). The distinction that matters: additions and removals are
routine maintenance, while a sample that *moved into the test split* is the classic
way for a published number to improve without the model improving (spec sections
64, 130).
"""

from __future__ import annotations

from typing import Any

from ..models import (
    AuditStatus,
    Category,
    Confidence,
    DatasetDiff,
    EvidenceType,
    FormalImpact,
    Severity,
)
from .context import AuditContext, NotApplicable, build_finding


def _locator(ctx: AuditContext, row: dict[str, Any]) -> str:
    """A human-openable reference for a diff row.

    Content-paired rows carry the *baseline* id under ``sample_id``, which this run's manifest
    cannot resolve, so the current-side id is preferred when the diff recorded one.
    """
    return ctx.display_id(str(row.get("current_sample_id") or row.get("sample_id")))


def detect_version_drift(ctx: AuditContext) -> list[Any]:
    diff: DatasetDiff | None = ctx.baseline
    if diff is None:
        raise NotApplicable("no baseline snapshot was supplied (--baseline)", "NOT_RUN")
    if not diff.comparable:
        return [
            build_finding(
                ctx,
                rule_id="DD018",
                sequence=1,
                title="Baseline snapshot not comparable",
                category=Category.VERSIONING,
                severity=Severity.MEDIUM,
                status=AuditStatus.INCONCLUSIVE,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.NONE,
                description=(
                    f"{diff.left} and {diff.right} cannot be diffed sample-for-sample: {diff.not_comparable_reason}"
                ),
                why_it_matters=(
                    "Version drift is measured by matching samples. If the join key differs (different "
                    "fingerprint mode, different schema), every sample looks added-and-removed and the "
                    "result is meaningless rather than merely noisy."
                ),
                evidence={
                    "left": diff.left,
                    "right": diff.right,
                    "reason": diff.not_comparable_reason,
                },
                recommended_action=(
                    "Re-create the baseline with the same fingerprint mode and config, or diff two snapshots "
                    "taken with `dataset-doctor-audit snapshot`."
                ),
                metadata={"scope": "dataset"},
            )
        ]

    findings: list[Any] = []
    summary = diff.summary
    changed_any = any(
        getattr(summary, name)
        for name in (
            "added",
            "removed",
            "modified",
            "moved_between_splits",
            "changed_labels",
            "changed_metadata",
        )
    )
    if not changed_any:
        return findings

    findings.append(
        build_finding(
            ctx,
            rule_id="DD018",
            sequence=1,
            title=f"Dataset changed since baseline ({diff.left} -> {diff.right})",
            category=Category.VERSIONING,
            severity=Severity.MEDIUM
            if (summary.added + summary.removed + summary.modified) / max(ctx.identity.num_samples, 1) >= 0.05
            else Severity.LOW,
            status=AuditStatus.WARNING,
            evidence_type=EvidenceType.DETERMINISTIC,
            confidence=Confidence.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            affected_count=summary.added + summary.removed + summary.modified,
            description=(
                f"Added {summary.added}, removed {summary.removed}, modified {summary.modified}, "
                f"relabelled {summary.changed_labels}, moved between splits {summary.moved_between_splits}."
            ),
            why_it_matters=(
                "A metric computed on v1 and a metric computed on v2 answer different questions. Version "
                "drift is the reason 'I re-ran the same experiment and got a different number' usually has "
                "a data explanation."
            ),
            evidence={
                "left": diff.left,
                "right": diff.right,
                "added": [ctx.display_id(str(sample)) for sample in diff.added_samples[:50]],
                "removed": [ctx.display_id(str(sample)) for sample in diff.removed_samples[:50]],
                "modified": [ctx.display_id(str(sample)) for sample in diff.modified_samples[:20]],
                "relabelled": [{**row, "sample": _locator(ctx, row)} for row in diff.relabeled_samples[:20]],
                "finding_changes": diff.finding_changes[:20],
            },
            limitations=[
                "Removed samples are identified by content hash only: they exist in the baseline, so this "
                "run has no row path or id column to resolve them against.",
                "Finding-level change tracking (`finding_changes`) is empty during an audit, because the "
                "diff is computed before this run's rules have produced findings. Compare two audited "
                "snapshots with `dataset-doctor-audit diff <a.json> <b.json>` for new/resolved findings.",
            ],
            recommended_action=(
                "Record the dataset version next to every published number, then re-run the baseline "
                "experiment if the comparison matters."
            ),
            metadata={"scope": "dataset"},
        )
    )

    if diff.moved_samples:
        into_test = [row for row in diff.moved_samples if row.get("to") == "test"]
        out_of_test = [row for row in diff.moved_samples if row.get("from") == "test"]
        findings.append(
            build_finding(
                ctx,
                rule_id="DD019",
                sequence=2,
                title=f"{len(diff.moved_samples)} sample(s) moved between splits",
                category=Category.VERSIONING,
                severity=Severity.CRITICAL if into_test else Severity.HIGH,
                status=AuditStatus.FAIL,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.BLOCKING,
                affected=[str(row.get("sample_id")) for row in diff.moved_samples],
                affected_count=len(diff.moved_samples),
                description=(
                    "; ".join(
                        f"{_locator(ctx, row)} {row.get('from')} -> {row.get('to')}" for row in diff.moved_samples[:10]
                    )
                    + "."
                ),
                why_it_matters=(
                    f"{len(into_test)} sample(s) entered the test split and {len(out_of_test)} left it. Any "
                    "metric from before the move was computed on a different evaluation set, so improvement "
                    "across the two runs is not attributable to the model."
                ),
                evidence={
                    "moves": [{**row, "sample": _locator(ctx, row)} for row in diff.moved_samples[:50]],
                    "into_test": len(into_test),
                    "out_of_test": len(out_of_test),
                },
                recommended_action=(
                    "Re-run the evaluation on one fixed split assignment, or publish the split manifest "
                    "hash alongside the number."
                ),
                metadata={"scope": "cross_split"},
            )
        )

    if diff.relabeled_samples:
        findings.append(
            build_finding(
                ctx,
                rule_id="DD019",
                sequence=3,
                title=f"{len(diff.relabeled_samples)} label(s) changed between versions",
                category=Category.VERSIONING,
                severity=Severity.HIGH,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL,
                affected=[str(row.get("sample_id")) for row in diff.relabeled_samples],
                affected_count=len(diff.relabeled_samples),
                description="; ".join(
                    f"{_locator(ctx, row)}: {row.get('from')} -> {row.get('to')}" for row in diff.relabeled_samples[:10]
                )
                + ".",
                why_it_matters=(
                    "Label corrections are legitimate maintenance, but a relabel that touches evaluation "
                    "samples changes what the score means; a relabel that follows model inspection is "
                    "training-set leakage through the annotation pipeline."
                ),
                evidence={"changes": [{**row, "sample": _locator(ctx, row)} for row in diff.relabeled_samples[:50]]},
                metadata={"scope": "samples"},
            )
        )
    return findings
