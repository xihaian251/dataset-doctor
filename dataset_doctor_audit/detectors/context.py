"""Shared detector context and finding-construction helpers.

Detectors must not invent severities: they report a measured fact plus evidence, and
``rules.apply_policy`` decides the risk (spec section 107).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import MAX_EVIDENCE_SAMPLES, Config
from ..models import (
    AuditFinding,
    AuditStatus,
    Category,
    Confidence,
    DatasetIdentity,
    DatasetManifest,
    DatasetSpec,
    DatasetType,
    EvidenceType,
    FindingLocation,
    FormalImpact,
    SampleRecord,
    Severity,
    SplitRole,
)


class NotApplicable(Exception):
    """The rule cannot run on this dataset (missing config, wrong modality)."""

    def __init__(self, reason: str, status: str = "NOT_RUN") -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status


class InsufficientEvidence(Exception):
    """The rule ran but could not gather enough evidence to answer. Never a PASS."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass
class AuditContext:
    root: Path
    config: Config
    spec: DatasetSpec
    manifest: DatasetManifest
    identity: DatasetIdentity
    adapter: Any
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    baseline: Any = None  # DatasetDiff against a snapshot, when --baseline was given

    # ------------------------------------------------------------------ helpers
    @property
    def records(self) -> list[SampleRecord]:
        return self.manifest.records

    @property
    def dataset_type(self) -> DatasetType:
        return self.identity.dataset_type

    @cached_property
    def _display_ids(self) -> dict[str, str]:
        """Hashed sample id -> something a reviewer can open without re-running the tool.

        The declared id column wins because it is the id the user's own tables use; the
        file plus row index is the fallback that still points at a concrete line.
        """
        out: dict[str, str] = {}
        for record in self.manifest.records:
            external = record.metadata.get("external_id")
            row_index = record.metadata.get("row_index")
            if external:
                out[record.sample_id] = f"{record.relative_path}::{external}"
            elif row_index is not None:
                out[record.sample_id] = f"{record.relative_path}#row={row_index}"
            else:
                out[record.sample_id] = record.relative_path or record.sample_id
        return out

    def display_id(self, sample_id: str) -> str:
        return self._display_ids.get(sample_id, sample_id)

    def by_split(self) -> dict[str, list[SampleRecord]]:
        return self.manifest.by_split()

    def split_names(self) -> list[str]:
        return [split.name for split in self.spec.splits]

    def role_of(self, split: str) -> SplitRole:
        for item in self.spec.splits:
            if item.name == split:
                return item.role
        return SplitRole.UNKNOWN

    def splits_with_role(self, *roles: SplitRole) -> list[str]:
        return [name for name in self.split_names() if self.role_of(name) in roles]

    def cross_split_pairs(self) -> list[tuple[str, str]]:
        """Pairs ordered so the most damaging combination is reported first.

        train<->test outranks train<->val outranks val<->test (spec section 21); an
        unrecognised split sorts after all three.
        """
        names = self.split_names()
        pairs: list[tuple[tuple[int, int, int], tuple[str, str]]] = []
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                a, b = names[i], names[j]
                pairs.append(((_pair_rank(a, b), _name_rank(a), _name_rank(b)), (a, b)))
        return [pair for _, pair in sorted(pairs, key=lambda item: item[0])]

    def needs_splits(self, minimum: int = 2) -> None:
        if len(self.split_names()) < minimum:
            raise InsufficientEvidence(
                f"Only {len(self.split_names())} split detected; this rule needs at least {minimum} "
                "to compare anything. Declare `splits:` in dataset-doctor.yaml."
            )

    def needs_content_hashes(self) -> None:
        if self.manifest.mode.value == "metadata":
            raise NotApplicable(
                "fingerprint mode is 'metadata': file contents were not hashed",
                status="UNSUPPORTED",
            )

    def hashed_records(self) -> list[SampleRecord]:
        return [record for record in self.records if record.sha256 or record.row_sha256]

    def table(self, split: str) -> pd.DataFrame | None:
        return self.tables.get(split)

    def numeric_columns(self) -> list[str]:
        if not self.tables:
            return []
        combined = (
            pd.concat([frame for frame in self.tables.values() if not frame.empty], ignore_index=True)
            if any(not frame.empty for frame in self.tables.values())
            else pd.DataFrame()
        )
        return [str(column) for column in combined.select_dtypes(include=["number", "bool"]).columns]

    def categorical_columns(self, max_levels: int = 200) -> list[str]:
        if not self.tables:
            return []
        out: list[str] = []
        sample = next(iter(self.tables.values()))
        for column in sample.columns:
            if str(column) in self.numeric_columns():
                continue
            try:
                levels = sample[column].astype(str).nunique(dropna=True)
            except Exception:
                continue
            if levels <= max_levels:
                out.append(str(column))
        return out

    def feature_columns(self) -> list[str]:
        """Columns a model would actually see: no label, no ids, no split column."""
        skip = {self.spec.split_column, self.label_column(), *self.spec.id_columns, *self.spec.group_columns}
        union: set[str] = set()
        for frame in self.tables.values():
            union.update(str(column) for column in frame.columns)
        return sorted(column for column in union if column not in skip)

    def label_column(self) -> str | None:
        return getattr(self.adapter, "label_column", None) or self.spec.label_column

    def time_column(self) -> str | None:
        return self.spec.temporal_column

    def group_column_available(self) -> list[str]:
        if not self.spec.group_columns:
            return []
        available: set[str] = set()
        for frame in self.tables.values():
            available.update(str(column) for column in frame.columns)
        if not available:
            available = set(self.identity.schema)
        return [column for column in self.spec.group_columns if column in available]


def _pair_rank(a: str, b: str) -> int:
    roles = {role_of_name(a), role_of_name(b)}
    if roles == {SplitRole.TRAIN, SplitRole.TEST}:
        return 0
    if SplitRole.TEST in roles and SplitRole.VAL in roles:
        return 1
    if SplitRole.TRAIN in roles:
        return 2
    if SplitRole.TEST in roles:
        return 3
    return 5


def role_of_name(name: str) -> SplitRole:
    from ..config import role_for

    return role_for(name)


def _name_rank(name: str) -> int:
    return {"train": 0, "val": 1, "test": 2}.get(name, 3)


def build_finding(
    ctx: AuditContext,
    *,
    rule_id: str,
    sequence: int,
    title: str,
    category: Category,
    severity: Severity,
    status: AuditStatus,
    description: str,
    why_it_matters: str,
    evidence_type: EvidenceType = EvidenceType.DETERMINISTIC,
    confidence: Confidence = Confidence.HIGH,
    formal_impact: FormalImpact = FormalImpact.POTENTIAL,
    affected: list[str] | None = None,
    affected_count: int | None = None,
    evidence: dict[str, Any] | None = None,
    columns: list[str] | None = None,
    paths: list[str] | None = None,
    source_split: str | None = None,
    target_split: str | None = None,
    recommended_action: str = "",
    auto_fix_available: bool = False,
    limitations: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> AuditFinding:
    affected = list(affected or [])
    total = ctx.identity.num_samples or 0
    count = affected_count if affected_count is not None else len(affected)
    shown = [ctx.display_id(sample_id) for sample_id in affected[:MAX_EVIDENCE_SAMPLES]]
    location = FindingLocation(
        kind="columns" if columns and not affected else "samples",
        sample_ids=shown,
        paths=(paths or [])[:MAX_EVIDENCE_SAMPLES],
        columns=(columns or [])[:MAX_EVIDENCE_SAMPLES],
        truncated=len(affected) > MAX_EVIDENCE_SAMPLES or len(paths or []) > MAX_EVIDENCE_SAMPLES,
    )
    from ..rules import rule_for

    rule = rule_for(rule_id)
    return AuditFinding(
        finding_id=f"{rule_id}-{sequence:04d}",
        rule_id=rule_id,
        title=title,
        category=category,
        severity=severity,
        confidence=confidence,
        status=status,
        evidence_type=evidence_type,
        formal_impact=formal_impact,
        description=description,
        why_it_matters=why_it_matters,
        affected_samples=shown,
        affected_count=count,
        affected_ratio=(count / total) if total else None,
        evidence=evidence or {},
        recommended_action=recommended_action or rule.remediation,
        auto_fix_available=auto_fix_available,
        source_split=source_split,
        target_split=target_split,
        location=location,
        limitations=limitations or [],
        metadata=metadata or {},
    )
