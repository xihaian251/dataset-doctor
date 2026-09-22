"""Core data model for Dataset Doctor.

Design rule (docs/adr/0004-risk-severity.md): a *fact* is produced by a detector,
a *verdict* is produced by the rule engine against a policy. These two never mix in
one object, which is why ``AuditFinding`` carries both ``status`` and ``formal_impact``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


class Severity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return _SEVERITY_RANK[self]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Severity):
            return NotImplemented
        return self.rank < other.rank


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.INFO: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}


class AuditStatus(str, Enum):
    """Outcome of a single rule execution.

    ``INCONCLUSIVE`` is the mandatory answer when evidence is missing: a silent
    PASS is prohibited (AGENTS.md), and "no finding" is only reportable as PASS
    when the detector actually covered the data it claims to cover.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    INCONCLUSIVE = "INCONCLUSIVE"
    NOT_RUN = "NOT_RUN"
    UNSUPPORTED = "UNSUPPORTED"
    SUPPRESSED = "SUPPRESSED"


class EvidenceType(str, Enum):
    """How a finding was derived. Surfaced in every report (spec section 112)."""

    DETERMINISTIC = "DETERMINISTIC"
    HEURISTIC = "HEURISTIC"
    STATISTICAL = "STATISTICAL"


class FormalImpact(str, Enum):
    """Does this class of problem invalidate a *formal evaluation*?

    This axis is the project's core scientific distinction (spec section 221):
    a data quality issue and an evaluation validity issue are not the same thing.
    """

    NONE = "NONE"
    POTENTIAL = "POTENTIAL"
    BLOCKING = "BLOCKING"


class EvalSafety(str, Enum):
    FORMAL_EVAL_SAFE = "FORMAL_EVAL_SAFE"
    FORMAL_EVAL_RISKY = "FORMAL_EVAL_RISKY"
    FORMAL_EVAL_INVALID = "FORMAL_EVAL_INVALID"
    INCONCLUSIVE = "INCONCLUSIVE"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Category(str, Enum):
    IDENTITY = "IDENTITY"
    SPLIT_INTEGRITY = "SPLIT_INTEGRITY"
    DUPLICATE = "DUPLICATE"
    LEAKAGE = "LEAKAGE"
    LABEL = "LABEL"
    DISTRIBUTION = "DISTRIBUTION"
    SCHEMA = "SCHEMA"
    INTEGRITY = "INTEGRITY"
    VERSIONING = "VERSIONING"
    PROVENANCE = "PROVENANCE"
    PRIVACY = "PRIVACY"


class DatasetType(str, Enum):
    AUTO = "auto"
    TABULAR = "tabular"
    IMAGE = "image"


class FingerprintMode(str, Enum):
    METADATA = "metadata"
    FULL = "full"
    SAMPLED = "sampled"


class SplitRole(str, Enum):
    TRAIN = "train"
    VAL = "val"
    TEST = "test"
    UNKNOWN = "unknown"


class BaseModel_(BaseModel):
    # `schema` is a mandated report field name (spec section 12); the shadow warning is
    # silenced at import time in dataset_doctor_audit/__init__.py rather than renamed.
    model_config = ConfigDict(extra="forbid", validate_assignment=False, frozen=False)


class SplitSpec(BaseModel_):
    name: str
    path: str
    role: SplitRole = SplitRole.UNKNOWN
    kind: str = "directory"  # directory | file
    sample_count: int | None = None


class DatasetSpec(BaseModel_):
    """What the user pointed us at, plus what we inferred about it."""

    root: str
    dataset_type: DatasetType = DatasetType.AUTO
    resolved_type: DatasetType | None = None
    splits: list[SplitSpec] = Field(default_factory=list)
    label_column: str | None = None
    label_source: str | None = None  # column | directory | none
    group_columns: list[str] = Field(default_factory=list)
    temporal_column: str | None = None
    split_column: str | None = None
    id_columns: list[str] = Field(default_factory=list)
    inference_notes: list[str] = Field(default_factory=list)


class SampleRecord(BaseModel_):
    """One row of the manifest: one file (image) or one table row (tabular)."""

    sample_id: str
    relative_path: str
    split: str
    label: str | None = None
    size: int | None = None
    mtime: float | None = None
    sha256: str | None = None
    row_sha256: str | None = None
    phash: str | None = None
    groups: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetManifest(BaseModel_):
    schema_version: str = SCHEMA_VERSION
    root: str
    mode: FingerprintMode = FingerprintMode.FULL
    sample_fraction: float = 1.0
    seed: int = 1337
    created_at: datetime = Field(default_factory=utcnow)
    records: list[SampleRecord] = Field(default_factory=list)

    def by_split(self) -> dict[str, list[SampleRecord]]:
        out: dict[str, list[SampleRecord]] = {}
        for rec in self.records:
            out.setdefault(rec.split, []).append(rec)
        return dict(sorted(out.items()))


class DatasetIdentity(BaseModel_):
    dataset_id: str
    created_at: datetime = Field(default_factory=utcnow)
    root_path: str
    dataset_type: DatasetType
    num_samples: int
    split_sizes: dict[str, int]
    classes: list[str]
    class_counts: dict[str, int]
    # The report contract calls this `schema`; pydantic reserves that name for its
    # deprecated JSON-Schema method, which this field shadows on purpose.
    schema: dict[str, str] = Field(default_factory=dict)  # type: ignore[assignment]
    file_extensions: dict[str, int] = Field(default_factory=dict)
    manifest_hash: str
    config_hash: str
    fingerprint_mode: FingerprintMode = FingerprintMode.FULL
    metadata: dict[str, Any] = Field(default_factory=dict)


class FindingLocation(BaseModel_):
    """Where a finding lives, so a human can go look at it."""

    kind: str = "samples"  # samples | columns | files
    sample_ids: list[str] = Field(default_factory=list)
    paths: list[str] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    truncated: bool = False


class AuditFinding(BaseModel_):
    """The atomic unit of output. Field set is frozen by spec section 5."""

    finding_id: str
    rule_id: str
    title: str
    category: Category
    severity: Severity
    confidence: Confidence
    status: AuditStatus
    evidence_type: EvidenceType
    formal_impact: FormalImpact
    description: str
    why_it_matters: str
    affected_samples: list[str] = Field(default_factory=list)
    affected_count: int = 0
    affected_ratio: float | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
    recommended_action: str = ""
    auto_fix_available: bool = False
    source_split: str | None = None
    target_split: str | None = None
    location: FindingLocation = Field(default_factory=FindingLocation)
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RuleOutcome(BaseModel_):
    """Per-rule bookkeeping, including rules that produced nothing."""

    rule_id: str
    name: str
    status: AuditStatus
    finding_count: int = 0
    highest_severity: Severity | None = None
    suppression_reason: str | None = None
    skip_reason: str | None = None
    duration_ms: int = 0


class AuditSummary(BaseModel_):
    total_findings: int = 0
    by_severity: dict[str, int] = Field(default_factory=dict)
    by_status: dict[str, int] = Field(default_factory=dict)
    by_category: dict[str, int] = Field(default_factory=dict)
    blocking_findings: int = 0
    suppressed_rules: list[str] = Field(default_factory=list)
    not_run_rules: list[str] = Field(default_factory=list)


class AuditReport(BaseModel_):
    schema_version: str = SCHEMA_VERSION
    tool_version: str
    generated_at: datetime = Field(default_factory=utcnow)
    duration_ms: int = 0
    identity: DatasetIdentity
    config_hash: str = ""
    policy_preset: str = "standard"
    eval_safety: EvalSafety = EvalSafety.INCONCLUSIVE
    eval_safety_reasons: list[str] = Field(default_factory=list)
    summary: AuditSummary = Field(default_factory=AuditSummary)
    rule_outcomes: list[RuleOutcome] = Field(default_factory=list)
    findings: list[AuditFinding] = Field(default_factory=list)
    methodology: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    coverage: dict[str, Any] = Field(default_factory=dict)

    def counts(self) -> dict[Severity, int]:
        out = dict.fromkeys(Severity, 0)
        for f in self.findings:
            out[f.severity] += 1
        return out


class AuditRule(BaseModel_):
    """Registry entry. Detector generates facts; the rule engine assigns risk."""

    rule_id: str
    name: str
    description: str
    category: Category
    default_severity: Severity
    formal_impact: FormalImpact
    applies_to: list[DatasetType] = Field(default_factory=lambda: [DatasetType.TABULAR, DatasetType.IMAGE])
    requires: list[str] = Field(default_factory=list)
    evidence_type: EvidenceType = EvidenceType.DETERMINISTIC
    false_positive_notes: str = ""
    remediation: str = ""
    implemented: bool = False
    doc_path: str = ""


class SnapshotRecord(BaseModel_):
    sample_id: str
    relative_path: str
    split: str
    label: str | None = None
    size: int | None = None
    sha256: str | None = None
    row_sha256: str | None = None
    # Features only (no label, no id, no split). Diff needs all three digests to keep
    # "the answer changed" and "the observation changed" on separate axes.
    feature_sha256: str | None = None
    groups: dict[str, str] = Field(default_factory=dict)


class DatasetSnapshot(BaseModel_):
    """Lightweight by construction: never copies data (spec section 67)."""

    schema_version: str = SCHEMA_VERSION
    name: str
    created_at: datetime = Field(default_factory=utcnow)
    identity: DatasetIdentity
    fingerprint_mode: FingerprintMode
    records: list[SnapshotRecord] = Field(default_factory=list)
    findings_digest: dict[str, Any] = Field(default_factory=dict)
    source_report: str | None = None


class DiffSummary(BaseModel_):
    added: int = 0
    removed: int = 0
    modified: int = 0
    moved_between_splits: int = 0
    changed_labels: int = 0
    changed_metadata: int = 0
    new_findings: int = 0
    resolved_findings: int = 0
    new_duplicate_pairs: int = 0
    resolved_duplicate_pairs: int = 0
    new_leakage: int = 0
    resolved_leakage: int = 0


class DatasetDiff(BaseModel_):
    schema_version: str = SCHEMA_VERSION
    created_at: datetime = Field(default_factory=utcnow)
    left: str
    right: str
    left_identity: DatasetIdentity | None = None
    right_identity: DatasetIdentity | None = None
    comparable: bool = True
    not_comparable_reason: str | None = None
    summary: DiffSummary = Field(default_factory=DiffSummary)
    added_samples: list[str] = Field(default_factory=list)
    removed_samples: list[str] = Field(default_factory=list)
    modified_samples: list[dict[str, Any]] = Field(default_factory=list)
    moved_samples: list[dict[str, Any]] = Field(default_factory=list)
    relabeled_samples: list[dict[str, Any]] = Field(default_factory=list)
    finding_changes: list[dict[str, Any]] = Field(default_factory=list)
    eval_safety_change: dict[str, Any] = Field(default_factory=dict)
