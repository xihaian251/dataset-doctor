"""DD001 identity, DD002 split integrity, DD014 schema drift, DD020 provenance,
DD021 PII exposure.

These are the structural rules: they do not measure statistics, they check whether
the dataset is even the shape the experiment assumes. A missing test split, two
splits pointing at the same folder, or a column that is a float in train and a
string in test all invalidate comparisons for reasons no accuracy number will
reveal (spec sections 26-28 of the split-integrity family).
"""

from __future__ import annotations

import re
from typing import Any

from ..models import (
    AuditStatus,
    Category,
    Confidence,
    EvidenceType,
    FormalImpact,
    Severity,
    SplitRole,
)
from .context import AuditContext, NotApplicable, build_finding


def detect_identity(ctx: AuditContext) -> list[Any]:
    """DD001 always reports one INFO finding: the factual baseline every other rule cites."""
    identity = ctx.identity
    return [
        build_finding(
            ctx,
            rule_id="DD001",
            sequence=1,
            title=f"Dataset identified: {identity.dataset_id}",
            category=Category.IDENTITY,
            severity=Severity.INFO,
            status=AuditStatus.PASS,
            evidence_type=EvidenceType.DETERMINISTIC,
            confidence=Confidence.HIGH,
            formal_impact=FormalImpact.NONE,
            affected_count=identity.num_samples,
            description=(
                f"{identity.num_samples} samples of type {identity.dataset_type.value}; "
                f"splits {identity.split_sizes}; {len(identity.classes)} class(es); "
                f"fingerprint mode {identity.fingerprint_mode.value}."
            ),
            why_it_matters=(
                "Every other finding cites sample ids from this manifest. Without a recorded identity and "
                "manifest hash, a published number cannot be tied back to the bytes that produced it."
            ),
            evidence={
                "dataset_id": identity.dataset_id,
                "manifest_hash": identity.manifest_hash,
                "config_hash": identity.config_hash,
                "schema": identity.schema,
                "file_extensions": identity.file_extensions,
                "split_sizes": identity.split_sizes,
                "class_count": len(identity.classes),
                "inference_notes": list(identity.metadata.get("inference_notes", [])),
                "adapter_notes": list(identity.metadata.get("adapter_notes", [])),
            },
            recommended_action=(
                "Nothing to fix: this is the baseline. Commit dataset-doctor.yaml and the manifest so a "
                "reviewer can reproduce it."
            ),
            metadata={"scope": "dataset"},
        )
    ]


def detect_split_integrity(ctx: AuditContext) -> list[Any]:
    findings: list[Any] = []
    sequence = 1
    names = ctx.split_names()
    specs = {split.name: split for split in ctx.spec.splits}

    if len(names) < 2:
        findings.append(
            build_finding(
                ctx,
                rule_id="DD002",
                sequence=sequence,
                title=f"Only {len(names)} split(s) detected",
                category=Category.SPLIT_INTEGRITY,
                severity=Severity.HIGH,
                status=AuditStatus.INCONCLUSIVE,
                evidence_type=EvidenceType.DETERMINISTIC,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL,
                description=(
                    "The layout produced a single split named "
                    f"'{names[0] if names else '-'}', so no train/val/test comparison is possible."
                ),
                why_it_matters=(
                    "Cross-split leakage (duplicates, entity reuse, temporal order) is exactly what this "
                    "tool is for, and it cannot be answered from one split. A PASS here would be false."
                ),
                evidence={"splits": names, "inference_notes": list(ctx.spec.inference_notes)},
                recommended_action=(
                    "Declare the layout explicitly in dataset-doctor.yaml (`splits: {train: ..., test: ...}`) "
                    "or point the tool at the parent directory that contains them."
                ),
                metadata={"scope": "splits", "reason": "single_split"},
            )
        )
        sequence += 1

    sizes = ctx.identity.split_sizes
    for name in names:
        if sizes.get(name, 0) == 0:
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD002",
                    sequence=sequence,
                    title=f"Split '{name}' is empty",
                    category=Category.SPLIT_INTEGRITY,
                    severity=Severity.HIGH,
                    status=AuditStatus.FAIL,
                    formal_impact=FormalImpact.BLOCKING,
                    source_split=name,
                    description=(f"{specs[name].path} was discovered as a split but contributed 0 samples."),
                    why_it_matters=(
                        "An empty evaluation split silently turns a metric into a training metric. Loaders "
                        "often fall back to whatever is left rather than raising."
                    ),
                    evidence={"path": specs[name].path, "kind": specs[name].kind},
                    metadata={"scope": "splits", "reason": "empty_split"},
                )
            )
            sequence += 1

    for warning in _path_collisions(ctx):
        findings.append(
            build_finding(
                ctx,
                rule_id="DD002",
                sequence=sequence,
                title=warning["title"],
                category=Category.SPLIT_INTEGRITY,
                severity=Severity.CRITICAL,
                status=AuditStatus.FAIL,
                formal_impact=FormalImpact.BLOCKING,
                source_split=warning["a"],
                target_split=warning["b"],
                description=warning["description"],
                why_it_matters=(
                    "If the same directory serves two roles, every sample in it is by definition in both "
                    "splits: the evaluation measures the training set."
                ),
                evidence=warning["evidence"],
                metadata={"scope": "cross_split", "reason": "shared_path"},
            )
        )
        sequence += 1

    if len(names) >= 2 and not ctx.splits_with_role(SplitRole.TEST):
        findings.append(
            build_finding(
                ctx,
                rule_id="DD002",
                sequence=sequence,
                title="No split recognised as a test/evaluation split",
                category=Category.SPLIT_INTEGRITY,
                severity=Severity.MEDIUM,
                status=AuditStatus.INCONCLUSIVE,
                confidence=Confidence.MEDIUM,
                formal_impact=FormalImpact.POTENTIAL,
                description=("Splits found: " + ", ".join(f"{name} ({ctx.role_of(name).value})" for name in names)),
                why_it_matters=(
                    "Leakage severity is ranked by which boundary it crosses. With no split named like "
                    "test/eval, the tool cannot tell which side is the holdout, so train/val-style findings "
                    "stay at HIGH rather than CRITICAL."
                ),
                evidence={"roles": {name: ctx.role_of(name).value for name in names}},
                recommended_action="Name the holdout split, or map roles in dataset-doctor.yaml.",
                metadata={"scope": "splits", "reason": "no_test_role"},
            )
        )
    return findings


def _path_collisions(ctx: AuditContext) -> list[dict[str, Any]]:
    from pathlib import Path

    # A split column means every role is read out of the same file on purpose. Calling that
    # a shared path would report the declared layout as the bug it is designed to avoid.
    if ctx.spec.split_column:
        return []

    resolved: dict[str, list[str]] = {}
    for split in ctx.spec.splits:
        try:
            key = str(Path(split.path).expanduser().resolve())
        except OSError:
            key = str(split.path)
        resolved.setdefault(key, []).append(split.name)
    out: list[dict[str, Any]] = []
    for key, names in sorted(resolved.items()):
        if len(names) > 1:
            first, second = names[0], names[1]
            out.append(
                {
                    "title": f"Splits {first} and {second} point at the same path",
                    "a": first,
                    "b": second,
                    "description": f"Both '{first}' and '{second}' resolve to {key}.",
                    "evidence": {"path": key, "splits": names},
                }
            )
    return out


def detect_schema_drift(ctx: AuditContext) -> list[Any]:
    """DD014: column presence, dtype, and categorical-level mismatches between splits."""
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("schema drift compares table columns; this is an image dataset", "UNSUPPORTED")
    schema_item = ctx.config.policies.item("schema_drift")
    if not schema_item.enabled:
        raise NotApplicable("policy schema_drift.enabled = false", "NOT_RUN")
    if len(ctx.tables) < 2:
        raise NotApplicable("schema drift needs at least two splits", "NOT_RUN")
    frames = {name: frame for name, frame in ctx.tables.items() if not frame.empty}
    if len(frames) < 2:
        raise NotApplicable("fewer than two splits contain readable data", "NOT_RUN")

    reference = sorted(frames)[0]
    reference_frame = frames[reference]
    findings: list[Any] = []
    sequence = 1

    for split, frame in sorted(frames.items()):
        if split == reference:
            continue
        missing = [str(c) for c in reference_frame.columns if c not in frame.columns]
        extra = [str(c) for c in frame.columns if c not in reference_frame.columns]
        if missing or extra:
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD014",
                    sequence=sequence,
                    title=f"Schema mismatch between {reference} and {split}",
                    category=Category.SCHEMA,
                    severity=Severity.HIGH,
                    status=AuditStatus.FAIL,
                    formal_impact=FormalImpact.BLOCKING,
                    source_split=reference,
                    target_split=split,
                    columns=missing + extra,
                    description=(
                        f"{len(missing)} column(s) present in {reference} but not {split}"
                        + (f": {', '.join(missing[:10])}" if missing else "")
                        + f"; {len(extra)} column(s) only in {split}"
                        + (f": {', '.join(extra[:10])}" if extra else "")
                        + "."
                    ),
                    why_it_matters=(
                        "A model matrix built from one split cannot be built from the other. Depending on the "
                        "loader this surfaces as a crash, or worse as a silently dropped column."
                    ),
                    evidence={"reference": reference, "missing_in_target": missing, "extra_in_target": extra},
                    metadata={"scope": "column", "kind": "presence"},
                )
            )
            sequence += 1

    dtype_conflicts = _dtype_conflicts(ctx, frames)
    if dtype_conflicts:
        findings.append(
            build_finding(
                ctx,
                rule_id="DD014",
                sequence=sequence,
                title=f"Column dtype differs across splits ({len(dtype_conflicts)} column(s))",
                category=Category.SCHEMA,
                severity=Severity.HIGH,
                status=AuditStatus.FAIL,
                formal_impact=FormalImpact.BLOCKING,
                columns=[str(row["column"]) for row in dtype_conflicts],
                description="; ".join(
                    f"{row['column']}: " + ", ".join(f"{s}={t}" for s, t in sorted(row["types"].items()))
                    for row in dtype_conflicts[:10]
                ),
                why_it_matters=(
                    "The same column parsed as float in train and string in test changes what the encoder "
                    "does at evaluation time - typically producing an untrained category bucket for every "
                    "numeric value."
                ),
                evidence={"columns": dtype_conflicts[:50]},
                limitations=[
                    "dtype here is the loader's inference, not a stored schema. Mixed but parseable columns "
                    "can show as string in one split and numeric in another."
                ],
                metadata={"scope": "column", "kind": "dtype"},
            )
        )
        sequence += 1

    level_findings = _category_drift(ctx, frames, sequence)
    findings.extend(level_findings)
    return findings


def _dtype_conflicts(ctx: AuditContext, frames: dict[str, Any]) -> list[dict[str, Any]]:
    per_column: dict[str, dict[str, str]] = {}
    for split, frame in frames.items():
        for column in frame.columns:
            per_column.setdefault(str(column), {})[split] = _describe(frame[column])
    out = []
    for column, types in sorted(per_column.items()):
        distinct = set(types.values())
        if len(distinct) > 1 and "mixed" not in distinct:
            out.append({"column": column, "types": types})
    return out


def _describe(series: Any) -> str:
    from ..adapters.tabular import describe_dtype

    try:
        return describe_dtype(series)
    except Exception:
        return "unknown"


def _category_drift(ctx: AuditContext, frames: dict[str, Any], sequence: int) -> list[Any]:
    if not ctx.config.policies.item("category_drift").enabled:
        return []
    train_names = [name for name in frames if ctx.role_of(name) is SplitRole.TRAIN] or [sorted(frames)[0]]
    eval_names = [name for name in frames if ctx.role_of(name) in (SplitRole.TEST, SplitRole.VAL)]
    if not eval_names:
        return []
    train = frames[train_names[0]]
    findings: list[Any] = []
    skipped: set[str] = set()
    for split in sorted(eval_names):
        frame = frames[split]
        unseen: dict[str, list[str]] = {}
        for column in [c for c in train.columns if c in frame.columns]:
            if str(column) in ctx.numeric_columns():
                continue
            try:
                levels = set(train[column].astype(str).unique())
                seen = set(frame[column].astype(str).unique())
            except Exception:
                continue
            if _identifier_like(str(column), seen, len(frame), ctx):
                # A per-row key is *expected* to be unseen in test; flagging it is noise
                # that buries the categorical drift people actually need to see.
                skipped.add(str(column))
                continue
            new = sorted(seen - levels)
            if new:
                unseen[str(column)] = new
        if unseen:
            total_new = sum(len(v) for v in unseen.values())
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD014",
                    sequence=sequence,
                    title=f"Unseen categories in {split}",
                    category=Category.SCHEMA,
                    severity=Severity.MEDIUM,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.POTENTIAL,
                    source_split=train_names[0],
                    target_split=split,
                    columns=list(unseen),
                    description=(
                        f"{total_new} category value(s) appear in {split} but never in {train_names[0]} "
                        f"across {len(unseen)} column(s)."
                    ),
                    why_it_matters=(
                        "A categorical encoder fitted on train has no representation for these values. They "
                        "land in an unknown bucket, so whatever they predict is decided by the encoder's "
                        "fallback, not by training."
                    ),
                    evidence={
                        "columns": {column: values[:20] for column, values in sorted(unseen.items())},
                        "identifier_columns_skipped": sorted(skipped),
                    },
                    metadata={"scope": "column", "kind": "category_levels"},
                )
            )
            sequence += 1
    return findings


IDENTIFIER_UNIQUE_RATIO = 0.9
MIN_ROWS_FOR_UNIQUE_RATIO = 10


def _identifier_like(column: str, seen: set[str], n_rows: int, ctx: AuditContext) -> bool:
    """True when a column holds per-row keys rather than categories.

    Declared id/group columns always qualify. Otherwise the column must be near-unique
    inside this frame, which is what an identifier looks like; the row floor stops a
    three-row split from being called an id column.
    """
    if column in {*ctx.spec.id_columns, *ctx.spec.group_columns}:
        return True
    if n_rows < MIN_ROWS_FOR_UNIQUE_RATIO:
        return False
    return len(seen) / n_rows > IDENTIFIER_UNIQUE_RATIO


def detect_provenance(ctx: AuditContext) -> list[Any]:
    provenance = ctx.config.provenance
    missing = [
        key
        for key, value in (
            ("source", provenance.source),
            ("version", provenance.version),
            ("license", provenance.license),
            ("download_date", provenance.download_date),
        )
        if not value
    ]
    if provenance.is_empty:
        return [
            build_finding(
                ctx,
                rule_id="DD020",
                sequence=1,
                title="No provenance declared",
                category=Category.PROVENANCE,
                severity=Severity.LOW,
                status=AuditStatus.WARNING,
                formal_impact=FormalImpact.NONE,
                confidence=Confidence.HIGH,
                description=(
                    "dataset-doctor.yaml carries no provenance block: source, version, licence and "
                    "acquisition date are unknown."
                ),
                why_it_matters=(
                    "Without provenance, 'the same dataset' is only a fingerprint match. Two downloads of a "
                    "public benchmark can differ by revision, and licence terms cannot be checked at all."
                ),
                evidence={"missing": ["source", "version", "license", "download_date"]},
                recommended_action="Fill in the provenance block, even for a well-known public benchmark.",
                metadata={"scope": "config"},
            )
        ]
    if not missing:
        return []
    return [
        build_finding(
            ctx,
            rule_id="DD020",
            sequence=1,
            title="Partial provenance",
            category=Category.PROVENANCE,
            severity=Severity.INFO,
            status=AuditStatus.PASS,
            formal_impact=FormalImpact.NONE,
            confidence=Confidence.HIGH,
            description=f"Provenance declared but incomplete; missing: {', '.join(missing)}.",
            why_it_matters="Version and licence gaps are the ones that bite when a result is re-checked.",
            evidence={"declared": provenance.model_dump(exclude_none=True), "missing": missing},
            metadata={"scope": "config"},
        )
    ]


_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"^[^@\s]{1,64}@[^@\s]{2,}\.", re.IGNORECASE),
    "phone_like": re.compile(r"^\+?[0-9][0-9\s().-]{7,14}$"),
    "national_id_like": re.compile(r"^\d{6}[-+]?\d{4}$|^\d{9,11}$"),
}

#: ``phone_like`` deliberately accepts dashes and spaces, which is also what a date looks
#: like. Without this veto every timestamp column in a clinical cohort - the most common
#: column in exactly the datasets this tool exists for - is reported as personal data.
_DATE_SHAPED = re.compile(r"^\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|^\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}$")


def _looks_like(kind: str, value: str) -> bool:
    if kind == "phone_like" and _DATE_SHAPED.match(value):
        return False
    return bool(_PII_PATTERNS[kind].match(value))


def detect_pii(ctx: AuditContext) -> list[Any]:
    """DD021. Values are never copied into the report - only counts (spec sections 94-95)."""
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("PII scanning covers table columns", "UNSUPPORTED")
    item = ctx.config.policies.item("pii_scan")
    if not item.enabled:
        raise NotApplicable("policy pii_scan.enabled = false", "NOT_RUN")
    threshold = float(item.extra_settings().get("min_match_ratio", 0.05))
    findings: list[Any] = []
    sequence = 1
    seen: set[tuple[str, str]] = set()
    for split, frame in sorted(ctx.tables.items()):
        if frame.empty:
            continue
        for column in frame.columns:
            name = str(column)
            series = frame[column].dropna().astype(str)
            if series.empty:
                continue
            for kind in _PII_PATTERNS:
                matches = int(sum(1 for value in series if _looks_like(kind, value.strip())))
                ratio = matches / len(series)
                if matches == 0 or ratio < threshold:
                    continue
                if (name, kind) in seen:
                    continue
                seen.add((name, kind))
                findings.append(
                    build_finding(
                        ctx,
                        rule_id="DD021",
                        sequence=sequence,
                        title=f"POTENTIAL_PII_COLUMN: '{name}' looks like {kind}",
                        category=Category.PRIVACY,
                        severity=Severity.MEDIUM,
                        status=AuditStatus.WARNING,
                        evidence_type=EvidenceType.HEURISTIC,
                        confidence=Confidence.LOW,
                        formal_impact=FormalImpact.NONE,
                        affected_count=matches,
                        source_split=split,
                        columns=[name],
                        description=(
                            f"{matches} of {len(series)} non-null values in '{name}' ({ratio:.1%}) match a "
                            f"{kind} pattern."
                        ),
                        why_it_matters=(
                            "Pattern matching cannot tell a phone number from an encoded identifier. It is "
                            "flagged because reports and shared datasets tend to carry these columns further "
                            "than intended, not because the audit asserts they are personal data."
                        ),
                        evidence={
                            "column": name,
                            "pattern": kind,
                            "matching_rows": matches,
                            "non_null_rows": len(series),
                            "match_ratio": round(ratio, 4),
                            "values_shown": False,
                        },
                        limitations=[
                            "No raw values are included in this report by design. Verify in place.",
                            "False positives are common: any digit string of the right length matches 'phone_like'.",
                        ],
                        recommended_action=(
                            f"Confirm with the data owner whether '{name}' is personal data; tokenise or drop "
                            "it before the dataset or this report leaves the lab."
                        ),
                        metadata={"scope": "column", "candidate": True},
                    )
                )
                sequence += 1
    return findings
