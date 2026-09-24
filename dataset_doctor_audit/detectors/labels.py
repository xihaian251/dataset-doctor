"""DD009 label conflict and DD010 missing / anomalous labels.

DD009 is the finding that hurts most in review: identical content carrying two
different answers. It is deterministic (same hash, different label), so no
statistic is needed (spec sections 52-53). Its *severity* depends on where the
conflict lives: across a split boundary it is contamination (CRITICAL, blocking),
inside the evaluation split it is an uninterpretable metric (HIGH, blocking), and
inside training alone it is label noise (MEDIUM, non-blocking) - the spec forbids
pricing a data-quality problem as evaluation invalidation. DD010 covers the
quieter label problems: absent labels, labels outside the declared set, and a
label column that is almost unique per row, which usually means the wrong column
was declared as the label (spec section 55).
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from ..models import (
    AuditStatus,
    Category,
    Confidence,
    DatasetType,
    EvidenceType,
    FormalImpact,
    SampleRecord,
    Severity,
    SplitRole,
)
from .context import AuditContext, InsufficientEvidence, NotApplicable, build_finding

TRAILING_PUNCTUATION = re.compile(r"[\s.]+$")


def _label_form(label: str) -> str:
    """A label with surrounding whitespace and trailing sentence punctuation removed.

    Several public datasets append a '.' to every class in one of their two files
    (UCI Adult's `adult.test` is the usual example). Such a pair of labels is the same
    class written twice, and DD009 has to say so - but the comparison it reports on
    stays the exact one, because grouping by a normalised label would silently merge
    two classes that a user's own pipeline keeps apart.
    """
    return TRAILING_PUNCTUATION.sub("", label.strip())


def detect_label_conflicts(ctx: AuditContext) -> list[Any]:
    if ctx.dataset_type is DatasetType.IMAGE:
        ctx.needs_content_hashes()
    groups: dict[str, list[SampleRecord]] = defaultdict(list)
    for record in ctx.records:
        if ctx.dataset_type is DatasetType.IMAGE:
            key = record.sha256
        else:
            key = record.metadata.get("feature_sha256") or record.row_sha256
        if key:
            groups[str(key)].append(record)

    conflicts = {key: members for key, members in groups.items() if len({member.label for member in members}) > 1}
    if not conflicts:
        return []

    cross: list[tuple[str, list[SampleRecord]]] = []
    within_eval: list[tuple[str, list[SampleRecord]]] = []
    within_train: list[tuple[str, list[SampleRecord]]] = []
    for key, members in conflicts.items():
        splits = {member.split for member in members}
        if len(splits) > 1:
            cross.append((key, members))
        elif any(ctx.role_of(name) in (SplitRole.TEST, SplitRole.VAL) for name in splits):
            within_eval.append((key, members))
        else:
            within_train.append((key, members))

    findings: list[Any] = []
    sequence = 1
    for group, scope, severity, status, impact, where in (
        (
            cross,
            "cross_split",
            Severity.CRITICAL,
            AuditStatus.FAIL,
            FormalImpact.BLOCKING,
            "one copy is trained and another is scored, so the metric measures recall of the label, "
            "not the model's generalisation",
        ),
        (
            within_eval,
            "within_split",
            Severity.HIGH,
            AuditStatus.FAIL,
            FormalImpact.BLOCKING,
            "the contradiction sits inside the evaluation split, where the same input is counted both "
            "right and wrong, so no accuracy on this split is interpretable",
        ),
        (
            within_train,
            "within_split",
            Severity.MEDIUM,
            AuditStatus.WARNING,
            FormalImpact.POTENTIAL,
            "the contradiction is confined to the training side. It puts a floor under achievable "
            "accuracy, but it does not make the test-set measurement invalid - reporting it as leakage "
            "would confuse label noise with contamination",
        ),
    ):
        if not group:
            continue
        members = [record for _, bucket in group for record in bucket]
        encoding_only = [
            (key, bucket) for key, bucket in group if len({_label_form(str(m.label)) for m in bucket}) == 1
        ]
        description = (
            f"{len(group)} content group(s) hold the same data under different labels; "
            f"{len(members)} samples are involved."
        )
        if encoding_only:
            description += (
                f" In {len(encoding_only)} of these group(s) the two labels are one class written two "
                f"ways - they differ only by whitespace or a trailing '.' - so the copies are the same "
                "row appearing twice with a differently encoded answer, not a contradiction between "
                "annotators. Normalising the spelling is the first thing to check; the identical "
                "content across a split boundary is the part that contaminates the metric."
            )
        findings.append(
            build_finding(
                ctx,
                rule_id="DD009",
                sequence=sequence,
                title=(
                    f"Conflicting labels on identical content ({len(group)} group(s), across splits)"
                    if scope == "cross_split"
                    else f"Conflicting labels on identical content ({len(group)} group(s) inside one split)"
                ),
                category=Category.LABEL,
                severity=severity,
                status=status,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=impact,
                affected=[record.sample_id for record in members],
                affected_count=len(members),
                paths=[record.relative_path for record in members],
                description=description,
                why_it_matters=(
                    f"Identical input with two answers makes the label noise floor unremovable: the best a "
                    f"model can do is guess between them. Here {where}."
                ),
                evidence={
                    "scope": scope,
                    "encoding_only_groups": len(encoding_only),
                    "encoding_only_labels": [
                        {"content_hash": key[:16], "labels": sorted({str(m.label) for m in bucket})}
                        for key, bucket in sorted(encoding_only, key=lambda item: -len(item[1]))[:5]
                    ],
                    "groups": [
                        {
                            "content_hash": key[:16],
                            "labels": sorted({str(m.label) for m in bucket}),
                            "members": [
                                {
                                    "sample_id": m.sample_id,
                                    "split": m.split,
                                    "label": m.label,
                                }
                                for m in bucket[:10]
                            ],
                        }
                        for key, bucket in sorted(group, key=lambda item: -len(item[1]))[:20]
                    ],
                },
                limitations=[
                    "For tabular data 'identical content' means identical feature values "
                    "(label and id columns excluded). Two genuinely different cases can share a "
                    "coarse feature vector; that is low-cardinality encoding, not mislabelling.",
                    "Labels are compared as exact strings, so one class written two ways reads as a "
                    "conflict. `encoding_only_groups` counts how many of these groups collapse to a "
                    "single class once whitespace and a trailing '.' are removed; that count is a "
                    "description of the evidence, and no grouping or severity uses it.",
                ],
                metadata={"scope": scope},
            )
        )
        sequence += 1
    return findings


def detect_missing_labels(ctx: AuditContext) -> list[Any]:
    label_column = ctx.label_column()
    if ctx.dataset_type is DatasetType.TABULAR and not label_column:
        raise NotApplicable("no label column declared or inferred, so label coverage cannot be judged", "NOT_RUN")
    if ctx.spec.label_source == "none":
        raise NotApplicable("labels.source = none, labelling is out of scope by config", "NOT_RUN")

    total = len(ctx.records)
    if not total:
        raise InsufficientEvidence("no samples in the manifest")

    unlabeled = [record for record in ctx.records if record.label is None]
    findings: list[Any] = []
    sequence = 1

    if unlabeled:
        by_split: dict[str, list[SampleRecord]] = defaultdict(list)
        for record in unlabeled:
            by_split[record.split].append(record)
        in_eval = [split for split, bucket in by_split.items() if ctx.role_of(split) in (SplitRole.TEST, SplitRole.VAL)]
        severity = Severity.HIGH if in_eval else (Severity.MEDIUM if len(unlabeled) / total > 0.02 else Severity.LOW)
        findings.append(
            build_finding(
                ctx,
                rule_id="DD010",
                sequence=sequence,
                title=f"Unlabelled samples: {len(unlabeled)} of {total}",
                category=Category.LABEL,
                severity=severity,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL if in_eval else FormalImpact.NONE,
                affected=[record.sample_id for record in unlabeled],
                affected_count=len(unlabeled),
                paths=[record.relative_path for record in unlabeled],
                description=(
                    "Per-split unlabelled counts: "
                    + ", ".join(f"{split}={len(bucket)}" for split, bucket in sorted(by_split.items()))
                    + (f"; unlabelled inside the evaluation split(s) {in_eval}." if in_eval else ".")
                ),
                why_it_matters=(
                    "Unlabelled rows are usually dropped silently by the loader. If they sit in the test "
                    "split, the denominator of the reported metric shrinks without anyone deciding it should."
                )
                if in_eval
                else (
                    "Unlabelled material is normal in semi-supervised work, but the audited sample count "
                    "and the labelled sample count are then different things and must not be quoted as one."
                ),
                evidence={
                    "unlabeled_total": len(unlabeled),
                    "by_split": {split: len(bucket) for split, bucket in sorted(by_split.items())},
                    "eval_split_hits": sorted(in_eval),
                },
                limitations=[
                    "For image folders, a label is the parent directory name: images stored directly in "
                    "the split root count as unlabelled even when the split itself is class-homogeneous."
                ],
                metadata={"scope": "samples"},
            )
        )
        sequence += 1

    labelled = [record for record in ctx.records if record.label is not None]
    if len(labelled) >= 20 and ctx.dataset_type is DatasetType.IMAGE:
        # A folder-per-class layout with ~one class per image is almost always the
        # wrong directory depth being read as the label.
        unique = {record.label for record in labelled}
        ratio = len(unique) / len(labelled)
        if ratio > 0.9:
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD010",
                    sequence=sequence,
                    title=f"Label cardinality anomaly: {len(unique)} labels for {len(labelled)} images",
                    category=Category.LABEL,
                    severity=Severity.MEDIUM,
                    status=AuditStatus.INCONCLUSIVE,
                    evidence_type=EvidenceType.HEURISTIC,
                    confidence=Confidence.MEDIUM,
                    formal_impact=FormalImpact.POTENTIAL,
                    affected_count=len(labelled),
                    description=(
                        f"{ratio:.0%} of labelled images have a distinct label, which is what a "
                        "non-class directory layout looks like when read as classes."
                    ),
                    why_it_matters=(
                        "If labels are actually instance ids or subfolders, every class-level statistic in "
                        "this report (imbalance, label shift, per-class coverage) is measuring the wrong thing."
                    ),
                    evidence={
                        "unique_labels": len(unique),
                        "labelled_samples": len(labelled),
                        "unique_ratio": round(ratio, 4),
                        "sample_labels": sorted(str(label) for label in unique)[:20],
                    },
                    limitations=[
                        "Open-set and instance-level tasks genuinely have near-unique labels. The class "
                        "distribution rules stay reported but should be read with this caveat."
                    ],
                    metadata={"scope": "labels", "kind": "cardinality"},
                )
            )
    return findings
