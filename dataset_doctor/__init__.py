"""Dataset Doctor — local-first ML dataset reliability and leakage auditing.

The public surface is deliberately small: build a report, or diff two datasets.
"""

from __future__ import annotations

import warnings

# The field name `schema` is mandated by the data model contract (spec section 12);
# pydantic only warns because it shadows a deprecated base-class method. This filter
# must be installed before the models are imported, i.e. before the warning fires.
warnings.filterwarnings("ignore", message=r'Field name "schema" in "DatasetIdentity" shadows .* parent')

from .audit import (
    AuditResult,
    ScanResult,
    audit_dataset,
    diff_targets,
    fingerprint_dataset,
    load_config,
    scan,
    snapshot_dataset,
)
from .models import (
    AuditFinding,
    AuditReport,
    AuditRule,
    AuditStatus,
    Category,
    Confidence,
    DatasetDiff,
    DatasetIdentity,
    DatasetManifest,
    DatasetSnapshot,
    DatasetSpec,
    EvalSafety,
    EvidenceType,
    FormalImpact,
    SampleRecord,
    Severity,
    SplitSpec,
)

__version__ = "0.1.0"

__all__ = [
    "AuditFinding",
    "AuditReport",
    "AuditResult",
    "AuditRule",
    "AuditStatus",
    "Category",
    "Confidence",
    "DatasetDiff",
    "DatasetIdentity",
    "DatasetManifest",
    "DatasetSnapshot",
    "DatasetSpec",
    "EvalSafety",
    "EvidenceType",
    "FormalImpact",
    "SampleRecord",
    "ScanResult",
    "Severity",
    "SplitSpec",
    "__version__",
    "audit_dataset",
    "diff_targets",
    "fingerprint_dataset",
    "load_config",
    "scan",
    "snapshot_dataset",
]
