"""Configuration: ``dataset-doctor.yaml`` loading, presets, policies, suppression.

Everything a verdict depends on is part of ``config_hash``, so a report can be
re-derived from (dataset bytes, config) alone. Defaults live in one place because
docs/METHODOLOGY.md has to document each of them.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import ConfigError
from .models import DatasetSpec, DatasetType, FingerprintMode, Severity, SplitRole, SplitSpec

DEFAULT_IGNORE = [
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "__pycache__",
    ".dataset-doctor",
    ".ipynb_checkpoints",
    ".DS_Store",
    "Thumbs.db",
    "*.tmp",
    "*.part",
    "*.partial",
    "desktop.ini",
]

MAX_EVIDENCE_SAMPLES = 50
"""Evidence lists are capped; the full set stays recomputable from the manifest."""


class PolicyItem(BaseModel):
    """One policy knob block. Unknown keys are collected, never silently dropped."""

    model_config = ConfigDict(extra="allow")

    enabled: bool = True
    severity: Severity | None = None

    def extra_settings(self) -> dict[str, Any]:
        return dict(self.model_extra or {})


class Policies(BaseModel):
    model_config = ConfigDict(extra="allow")

    exact_duplicate: PolicyItem = Field(default_factory=PolicyItem)
    near_duplicate: PolicyItem = Field(default_factory=PolicyItem)
    group_leakage: PolicyItem = Field(default_factory=PolicyItem)
    entity_leakage: PolicyItem = Field(default_factory=PolicyItem)
    temporal_leakage: PolicyItem = Field(default_factory=PolicyItem)
    target_leakage: PolicyItem = Field(default_factory=PolicyItem)
    identifier_leakage: PolicyItem = Field(default_factory=PolicyItem)
    label_conflict: PolicyItem = Field(default_factory=PolicyItem)
    missing_labels: PolicyItem = Field(default_factory=PolicyItem)
    label_cardinality: PolicyItem = Field(default_factory=PolicyItem)
    class_imbalance: PolicyItem = Field(default_factory=PolicyItem)
    label_shift: PolicyItem = Field(default_factory=PolicyItem)
    feature_shift: PolicyItem = Field(default_factory=PolicyItem)
    image_property_shift: PolicyItem = Field(default_factory=PolicyItem)
    schema_drift: PolicyItem = Field(default_factory=PolicyItem)
    category_drift: PolicyItem = Field(default_factory=PolicyItem)
    missingness_shift: PolicyItem = Field(default_factory=PolicyItem)
    outlier: PolicyItem = Field(default_factory=PolicyItem)
    corrupt_sample: PolicyItem = Field(default_factory=PolicyItem)
    split_integrity: PolicyItem = Field(default_factory=PolicyItem)
    dataset_identity: PolicyItem = Field(default_factory=PolicyItem)
    version_drift: PolicyItem = Field(default_factory=PolicyItem)
    split_drift: PolicyItem = Field(default_factory=PolicyItem)
    provenance: PolicyItem = Field(default_factory=PolicyItem)
    pii_scan: PolicyItem = Field(default_factory=PolicyItem)

    def item(self, name: str) -> PolicyItem:
        found = getattr(self, name, None)
        if isinstance(found, PolicyItem):
            return found
        return PolicyItem()


class SamplingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    fraction: float = Field(default=1.0, gt=0, le=1.0)
    seed: int = 1337


class PerformanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    workers: int = Field(default=0, ge=0, le=64)  # 0 -> auto
    progress: bool | None = None
    chunk_size: int = Field(default=1024 * 1024, ge=1024)
    cache: bool = True  # reuse sha256 across runs, keyed by path+size+mtime


class DatasetSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: DatasetType = DatasetType.AUTO
    name: str | None = None
    ignore: list[str] = Field(default_factory=list)


class LabelSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = None  # column | directory | none
    column: str | None = None


class GroupSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_column: str | None = None
    columns: list[str] = Field(default_factory=list)

    def resolved(self) -> list[str]:
        cols = list(self.columns)
        if self.entity_column and self.entity_column not in cols:
            cols.insert(0, self.entity_column)
        return cols


class TemporalSection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column: str | None = None
    train_before_test: bool = True
    split_column: str | None = None  # split membership carried inside the table


class Provenance(BaseModel):
    model_config = ConfigDict(extra="allow")

    source: str | None = None
    version: str | None = None
    license: str | None = None
    download_date: str | None = None

    @property
    def is_empty(self) -> bool:
        return not (self.source or self.version or self.license or self.download_date)


class Suppression(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    rule: str
    reason: str
    scope: str | None = None  # optional "split:<name>" or "column:<name>"


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    preset: str = "standard"
    dataset: DatasetSection = Field(default_factory=DatasetSection)
    splits: dict[str, str] = Field(default_factory=dict)
    labels: LabelSection = Field(default_factory=LabelSection)
    groups: GroupSection = Field(default_factory=GroupSection)
    temporal: TemporalSection = Field(default_factory=TemporalSection)
    id_columns: list[str] = Field(default_factory=list)
    provenance: Provenance = Field(default_factory=Provenance)
    policies: Policies = Field(default_factory=Policies)
    suppress: list[Suppression] = Field(default_factory=list)
    fingerprint: FingerprintMode = FingerprintMode.FULL
    sampling: SamplingConfig = Field(default_factory=SamplingConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)

    warnings: list[str] = Field(default_factory=list)
    source_path: str | None = None
    root: Path | None = None

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls, root: Path, path: Path | None = None, preset: str | None = None) -> Config:
        cfg_path = path or _find_config(root)
        raw: dict[str, Any] = {}
        if cfg_path is not None:
            try:
                loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                raise ConfigError(f"Cannot read config {cfg_path}: {exc}") from exc
            if not isinstance(loaded, dict):
                raise ConfigError(f"Config root must be a mapping, got {type(loaded).__name__}")
            raw = loaded
        if preset:
            raw = {**raw, "preset": preset}
        raw = _apply_preset(raw)
        raw = _normalize_legacy_keys(raw)
        try:
            cfg = cls.model_validate(raw)
        except ValidationError as exc:
            raise ConfigError(_format_validation_error(exc)) from exc
        cfg.source_path = str(cfg_path) if cfg_path else None
        cfg.root = root
        cfg.warnings.extend(_unknown_policy_keys(raw))
        cfg.validate_semantics()
        return cfg

    def validate_semantics(self) -> None:
        for sup in self.suppress:
            if not re.fullmatch(r"DD\d{3}", sup.rule):
                raise ConfigError(
                    f"suppress.rule must look like 'DD003', got '{sup.rule}'. "
                    "Run `dataset-doctor rules` to list rule ids."
                )
            if not sup.reason.strip():
                raise ConfigError(f"suppress entry for {sup.rule} needs a non-empty reason")
        for name in self.policies.model_extra or {}:  # unknown policy block
            self.warnings.append(f"Unknown policy block '{name}' is ignored")
        if self.dataset.type is DatasetType.AUTO and self.fingerprint is FingerprintMode.FULL:
            pass  # resolved later, once the adapter is known

    # ------------------------------------------------------------------- hashes
    def resolved_dict(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"source_path", "root", "warnings"})
        return data

    def config_hash(self) -> str:
        blob = json.dumps(self.resolved_dict(), sort_keys=True, ensure_ascii=False, default=str)
        return "cfg_" + hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]

    def suppression_for(self, rule_id: str) -> Suppression | None:
        for sup in self.suppress:
            if sup.rule == rule_id:
                return sup
        return None

    def severity_override(self, rule_id: str) -> Severity | None:
        from .rules import RULE_TO_POLICY

        policy_name = RULE_TO_POLICY.get(rule_id)
        if not policy_name:
            return None
        return self.policies.item(policy_name).severity

    def effective_workers(self) -> int:
        if self.performance.workers:
            return self.performance.workers
        import os

        return max(1, min(8, (os.cpu_count() or 2)))

    def ignore_patterns(self) -> list[str]:
        """Built-in noise plus whatever the user added (spec section 83)."""
        return [*DEFAULT_IGNORE, *self.dataset.ignore]

    def to_dataset_spec(self, root: Path) -> DatasetSpec:
        splits = [
            SplitSpec(name=name, path=str(value), role=role_for(name)) for name, value in sorted(self.splits.items())
        ]
        return DatasetSpec(
            root=str(root),
            dataset_type=self.dataset.type,
            splits=splits,
            label_column=self.labels.column,
            label_source=self.labels.source,
            group_columns=self.groups.resolved(),
            temporal_column=self.temporal.column,
            split_column=self.temporal.split_column,
            id_columns=list(self.id_columns),
        )


# ---------------------------------------------------------------------- presets
# A preset is only a severity/enabled delta. It never changes a measurement.
_PRESETS: dict[str, dict[str, Any]] = {
    "standard": {},
    "research": {
        "policies": {
            "near_duplicate": {"enabled": True},
            "outlier": {"enabled": False},
        }
    },
    "medical": {
        "policies": {
            "group_leakage": {"enabled": True, "severity": Severity.CRITICAL},
            "pii_scan": {"enabled": True},
            "temporal_leakage": {"enabled": True},
        }
    },
    "vision": {
        "policies": {
            "near_duplicate": {"enabled": True, "hamming_threshold": 6},
            "image_property_shift": {"enabled": True},
        }
    },
    "time_series": {
        "policies": {
            "temporal_leakage": {"enabled": True, "severity": Severity.CRITICAL},
            "feature_shift": {"enabled": True},
        }
    },
}


def available_presets() -> list[str]:
    return sorted(_PRESETS)


def _deep_merge(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in extra.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _apply_preset(raw: dict[str, Any]) -> dict[str, Any]:
    preset = str(raw.get("preset", "standard"))
    if preset not in _PRESETS:
        raise ConfigError(f"Unknown preset '{preset}'. Available: {', '.join(available_presets())}")
    merged = _deep_merge(_PRESETS[preset], raw)
    merged["preset"] = preset
    return merged


_LEGACY_ALIASES = {
    "class imbalance": "class_imbalance",
    "distribution_shift": "feature_shift",
    "duplicate": "exact_duplicate",
    "entity_leak": "group_leakage",
}


def _normalize_legacy_keys(raw: dict[str, Any]) -> dict[str, Any]:
    """Accept the spelling variants that appear in the wild (and in the spec)."""
    out = dict(raw)
    if isinstance(out.get("policies"), dict):
        policies = dict(out["policies"])
        for old, new in _LEGACY_ALIASES.items():
            if old in policies and new not in policies:
                policies[new] = policies.pop(old)
        out["policies"] = policies
    groups = out.get("groups")
    if isinstance(groups, dict) and "columns" not in groups and "column" in groups:
        groups = {**groups, "columns": [groups.pop("column")]}
        out["groups"] = groups
    return out


def _unknown_policy_keys(raw: dict[str, Any]) -> list[str]:
    policies = raw.get("policies")
    if not isinstance(policies, dict):
        return []
    known = set(Policies.model_fields)
    return [
        f"Unknown policy block '{key}' is ignored (see `dataset-doctor rules`)" for key in policies if key not in known
    ]


def _format_validation_error(exc: ValidationError) -> str:
    lines = ["Invalid configuration:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"]) or "<root>"
        lines.append(f"  - {loc}: {err['msg']}")
    return "\n".join(lines)


def _find_config(root: Path) -> Path | None:
    for candidate in (
        root / "dataset-doctor.yaml",
        root / "dataset-doctor.yml",
        root.parent / "dataset-doctor.yaml",
        Path.cwd() / "dataset-doctor.yaml",
    ):
        if candidate.is_file():
            return candidate
    return None


_TRAINLIKE = {"train", "training", "trn", "fit"}
_VAL = {"val", "valid", "validation", "dev", "evaluate"}
_TEST = {"test", "testing", "tst", "eval"}


def role_for(name: str) -> SplitRole:
    key = name.strip().lower()
    if key in _TRAINLIKE:
        return SplitRole.TRAIN
    if key in _VAL:
        return SplitRole.VAL
    if key in _TEST:
        return SplitRole.TEST
    return SplitRole.UNKNOWN


INIT_TEMPLATE = """# Dataset Doctor configuration
# Full reference: docs/guides/CONFIGURATION.md

dataset:
  type: auto            # auto | tabular | image

# Leave empty to auto-discover train/val/test. Otherwise map split -> path:
# splits:
#   train: data/train.csv
#   val:   data/val.csv
#   test:  data/test.csv

# labels:
#   source: directory   # image-folder style
#   column: target      # tabular style

# groups:
#   columns: [patient_id]

# temporal:
#   column: timestamp
#   train_before_test: true

# provenance:
#   source: "MVTec AD"
#   version: "1.0"
#   license: "..."

policies:
  exact_duplicate:
    enabled: true
  near_duplicate:
    enabled: true
    method: phash
    hamming_threshold: 6
  class_imbalance:
    enabled: true
  feature_shift:
    enabled: true

# Suppressed rules still appear in the report as SUPPRESSED, with the reason.
# suppress:
#   - rule: DD011
#     reason: "Long-tail dataset by design"
"""


def write_init_template(path: Path, force: bool = False) -> bool:
    if path.exists() and not force:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(INIT_TEMPLATE, encoding="utf-8")
    return True
