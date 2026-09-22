"""DD016 corrupt / unreadable samples.

For images this is a decode attempt (spec section 48); for tables it is a parse
attempt, which the adapter already recorded. The rule never repairs anything: a
corrupt file inside the evaluation split changes *what is measured*, which is why
concentration in test is escalated over raw count (spec section 130).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..models import (
    AuditStatus,
    Category,
    Confidence,
    DatasetType,
    EvidenceType,
    FormalImpact,
    Severity,
    SplitRole,
)
from .context import AuditContext, InsufficientEvidence, build_finding


def detect_corrupt_samples(ctx: AuditContext) -> list[Any]:
    if ctx.dataset_type is DatasetType.IMAGE:
        return _from_images(ctx)
    return _from_tables(ctx)


def _from_images(ctx: AuditContext) -> list[Any]:
    decoded = [record for record in ctx.records if "corrupt" in record.metadata]
    if not decoded:
        raise InsufficientEvidence(
            "No image was decoded, so integrity cannot be asserted. Re-run with "
            "`--fingerprint full` (metadata mode deliberately skips pixel access)."
        )
    broken = [record for record in decoded if record.metadata.get("corrupt")]
    if not broken:
        return []
    #: Zero-byte files are caught by size alone; a truncated JPEG needs a decode attempt.
    #: Under metadata fingerprint mode the second kind stays invisible, so the count below
    #: is a lower bound and the rule may not answer as if it had covered every file.
    undecoded = sum(1 for record in ctx.records if record.metadata.get("inspected") is False)
    partial = undecoded > 0

    by_split: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in broken:
        by_split[record.split].append(
            {
                "sample_id": record.sample_id,
                "path": record.relative_path,
                "size": record.size,
                "reason": record.metadata.get("error") or "unreadable",
            }
        )
    eval_splits = sorted(split for split in by_split if ctx.role_of(split) in (SplitRole.TEST, SplitRole.VAL))
    rate = len(broken) / max(len(ctx.records), 1)
    severity = Severity.HIGH if eval_splits or (not partial and rate >= 0.01) else Severity.MEDIUM
    if eval_splits:
        status = AuditStatus.FAIL
    elif partial:
        status = AuditStatus.INCONCLUSIVE
    else:
        status = AuditStatus.WARNING
    return [
        build_finding(
            ctx,
            rule_id="DD016",
            sequence=1,
            title=f"Unreadable or corrupt images: {len(broken)} of {len(ctx.records)}",
            category=Category.INTEGRITY,
            severity=severity,
            status=status,
            evidence_type=EvidenceType.DETERMINISTIC,
            confidence=Confidence.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            affected=[record.sample_id for record in broken],
            affected_count=len(broken),
            paths=[record.relative_path for record in broken],
            description=(
                f"{len(broken)} file(s) failed Pillow verification (truncated, zero-byte or unsupported)"
                + (f", and {undecoded} more were never opened, so this is a lower bound" if partial else "")
                + ". Per split: "
                + ", ".join(f"{split}={len(rows)}" for split, rows in sorted(by_split.items()))
                + (f". Affected evaluation split(s): {', '.join(eval_splits)}." if eval_splits else ".")
            ),
            why_it_matters=(
                "Loaders typically skip or raise nondeterministically. If the skipped files sit in the test "
                "split, the denominator of the published metric is a different set than the one declared."
            )
            if eval_splits
            else (
                "Corrupt files reduce the effective sample count and, if a loader aborts on the first bad "
                "file, stop iteration early without a warning."
            ),
            evidence={
                "enumerated": len(ctx.records),
                "decoded": len(decoded),
                "not_decoded": undecoded,
                "broken": len(broken),
                "by_split": {split: len(rows) for split, rows in sorted(by_split.items())},
                "examples": [row for rows in by_split.values() for row in rows[:20]],
            },
            limitations=(
                [
                    f"{undecoded} of {len(ctx.records)} file(s) were not opened (`--fingerprint metadata` reads "
                    "sizes only), so a truncated or unsupported image among them would not appear here. Re-run "
                    "with `--fingerprint full` for a complete answer."
                ]
                if partial
                else []
            ),
            recommended_action=(
                "Re-download or re-export the listed files; if any sit in the evaluation split, rebuild that "
                "split and re-run the metric."
            ),
            metadata={"scope": "files"},
        )
    ]


def _from_tables(ctx: AuditContext) -> list[Any]:
    unreadable = list(getattr(ctx.adapter, "unreadable", []))
    if not unreadable:
        return []
    affected_splits = {name for name in (_split_of(ctx, item) for item in unreadable) if name}
    touches_eval = any(ctx.role_of(split) in (SplitRole.TEST, SplitRole.VAL) for split in affected_splits)
    severity = Severity.HIGH if touches_eval else Severity.MEDIUM
    empty_frames = [split for split, frame in ctx.tables.items() if frame.empty]
    return [
        build_finding(
            ctx,
            rule_id="DD016",
            sequence=1,
            title=f"Unreadable table file(s): {len(unreadable)}",
            category=Category.INTEGRITY,
            severity=severity,
            status=AuditStatus.WARNING,
            evidence_type=EvidenceType.DETERMINISTIC,
            confidence=Confidence.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            paths=[str(item.get("path", "")) for item in unreadable],
            affected_count=len(unreadable),
            description="; ".join(f"{item.get('path')} - {item.get('reason')}" for item in unreadable[:20]),
            why_it_matters=(
                "A split whose file failed to parse contributes zero rows. The audit then measures a smaller "
                "dataset than the layout claims, and the report itself is the only place that says so."
            ),
            evidence={
                "files": [
                    {"path": str(item.get("path")), "reason": str(item.get("reason"))} for item in unreadable[:50]
                ],
                "empty_splits": sorted(str(split) for split in empty_frames),
            },
            recommended_action="Fix the file or drop it from the declared splits, then re-audit.",
            metadata={"scope": "files"},
        )
    ]


def _split_of(ctx: AuditContext, item: dict[str, Any]) -> str:
    path = str(item.get("path", ""))
    for split in ctx.spec.splits:
        if path.startswith(str(split.path)):
            return split.name
    return ""
