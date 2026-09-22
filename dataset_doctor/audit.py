"""The audit pipeline: discover -> adapt -> manifest -> detect -> policy -> report.

Two invariants are enforced here rather than inside each detector, because they are
the two a reviewer actually checks:

* A rule that could not run never looks like a rule that passed. Every detector
  either returns findings, raises ``NotApplicable`` (NOT_RUN / UNSUPPORTED) or
  raises ``InsufficientEvidence`` (INCONCLUSIVE). Each becomes a ``RuleOutcome``
  even when the finding list is empty, so the report states its own coverage.
* Detectors report facts; only :mod:`dataset_doctor.rules` turns a fact into a
  severity, and the only input it accepts is policy (spec section 107).
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import manifest as manifest_ops
from .adapters import build_adapter
from .config import Config
from .detectors import distribution, duplicates, integrity, labels, leakage, structural, versioning
from .detectors.context import AuditContext, InsufficientEvidence, NotApplicable
from .diff import compare_snapshots
from .errors import ConfigError, DiscoveryError
from .hashing import HashCache
from .models import (
    AuditFinding,
    AuditReport,
    AuditStatus,
    DatasetDiff,
    DatasetIdentity,
    DatasetManifest,
    DatasetSnapshot,
    DatasetSpec,
    EvalSafety,
    FingerprintMode,
    FormalImpact,
    RuleOutcome,
    Severity,
    utcnow,
)
from .rules import REGISTRY, apply_policy, eval_safety, outcome_for, severity_counts
from .snapshots import build_snapshot, resolve_snapshot, save_snapshot

LOGGER = logging.getLogger("dataset_doctor")

DETECTORS: list[tuple[str, Callable[[AuditContext], list[Any]]]] = [
    ("DD001", structural.detect_identity),
    ("DD002", structural.detect_split_integrity),
    ("DD003", duplicates.detect_exact_duplicates),
    ("DD004", duplicates.detect_near_duplicates),
    ("DD005", leakage.detect_group_leakage),
    ("DD006", leakage.detect_temporal_leakage),
    ("DD007", leakage.detect_target_leakage),
    ("DD008", leakage.detect_identifier_leakage),
    ("DD009", labels.detect_label_conflicts),
    ("DD010", labels.detect_missing_labels),
    ("DD011", distribution.detect_class_imbalance),
    ("DD012", distribution.detect_feature_shift),
    ("DD013", distribution.detect_label_shift),
    ("DD014", structural.detect_schema_drift),
    ("DD015", distribution.detect_missingness_shift),
    ("DD016", integrity.detect_corrupt_samples),
    ("DD017", distribution.detect_image_property_shift),
    ("DD018", versioning.detect_version_drift),
    ("DD019", versioning.detect_version_drift),
    ("DD020", structural.detect_provenance),
    ("DD021", structural.detect_pii),
]
"""Execution order: identity first, leakage before statistics, provenance last."""

VERSION_DRIFT_RULES = ("DD018", "DD019")

METHODOLOGY = [
    "Sample identity: images are hashed by streaming SHA256 over file bytes; tabular rows by SHA256 over a "
    "canonical per-row string (NaN has one spelling, floats are rounded to 12 decimals before repr).",
    "Facts come from detectors, severities from policy. A finding's severity can only be changed by "
    "policies.<rule>.severity, and the report records that it was (metadata.severity_source).",
    "Formal-evaluation verdict is rule-based: any BLOCKING finding => INVALID; MEDIUM-or-worse POTENTIAL "
    "finding => RISKY; too many INCONCLUSIVE rules => INCONCLUSIVE; else SAFE.",
    "Statistics are reported as effect size first. Distribution shift uses standardised mean difference and "
    "PSI as the trigger, with KS/Wasserstein/JS as supporting evidence, Benjamini-Hochberg corrected across "
    "columns.",
    "Near-duplicate search uses exact-match bit-band candidate generation over 64-bit pHash: for threshold t "
    "the candidate set is a superset of all pairs within Hamming distance t, so no O(N^2) sweep is needed "
    "and coverage loss is only from bucket truncation, which is itself reported.",
    "Everything is read-only. No file in the dataset is modified, and reports are written to the output "
    "directory chosen by the user.",
]

LIMITATIONS = [
    "Data leakage has a semantic component that cannot be detected from data alone: a column that is only "
    "known after the outcome looks identical, in the table, to a column that is merely predictive. Those "
    "cases are reported as candidates, never verdicts.",
    "Within-split findings are measured on hashes; a crop, rotation or recompression of an image is invisible "
    "to SHA256 and only partially covered by pHash.",
    "Group/entity leakage can only be checked for entity columns the user declares. An undeclared patient id "
    "is undetectable, so the report lists the columns it did not check.",
    "Sampling and metadata fingerprint modes reduce coverage; affected rules answer INCONCLUSIVE instead of PASS.",
    "Preprocessing leakage (a scaler fitted on the full data before the split) requires static analysis of "
    "the training code and is not implemented in V0.1.",
]


@dataclass
class ScanResult:
    """Everything derived from the bytes before any rule is applied."""

    root: Path
    config: Config
    spec: DatasetSpec
    manifest: DatasetManifest
    identity: DatasetIdentity
    ctx: AuditContext
    workdir: Path
    duration_ms: int = 0


@dataclass
class AuditResult:
    scan: ScanResult
    report: AuditReport
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def root(self) -> Path:
        return self.scan.root

    @property
    def identity(self) -> DatasetIdentity:
        return self.scan.identity

    @property
    def manifest(self) -> DatasetManifest:
        return self.scan.manifest

    @property
    def config(self) -> Config:
        return self.scan.config

    def rule(self, rule_id: str) -> RuleOutcome | None:
        return next((item for item in self.report.rule_outcomes if item.rule_id == rule_id), None)

    def by_rule(self, rule_id: str) -> list[AuditFinding]:
        return [finding for finding in self.report.findings if finding.rule_id == rule_id]

    def exit_code(self, ci: bool = False, strict: bool = False) -> int:
        """0 no blocking issue, 1 blocking findings, 2 config error, 3 internal error.

        Blocking means "a formal evaluation on this dataset would not be trustworthy",
        not "any finding exists" - DD001 always produces one informational finding, so
        the second reading would make the tool unusable in CI. Only assertive findings
        (FAIL/WARNING) count here: an INCONCLUSIVE BLOCKING finding says "not ruled out",
        and exiting 1 on it would claim a proof the tool does not have. ``--ci`` adds
        medium-and-worse findings and any verdict that is not plainly safe. ``--strict``
        is a superset of ``--ci``: it fails on all of that *and* when a rule could not
        reach a verdict, so a gate that catches "we looked and were unsure" can never be
        loosened by asking for more caution.
        """
        findings = self.report.findings
        assertive = (AuditStatus.FAIL, AuditStatus.WARNING)
        blocking = [
            item for item in findings if item.formal_impact is FormalImpact.BLOCKING and item.status in assertive
        ]
        if blocking:
            return 1
        critical = [item for item in findings if item.severity is Severity.CRITICAL and item.status in assertive]
        if critical:
            return 1
        if ci or strict:
            if any(item.severity.rank >= Severity.MEDIUM.rank for item in findings if item.status in assertive):
                return 1
            if self.report.eval_safety is not EvalSafety.FORMAL_EVAL_SAFE:
                return 1
        if strict and self.report.coverage.get("rules_inconclusive"):
            return 1
        if self.report.eval_safety is EvalSafety.FORMAL_EVAL_INVALID:
            return 1
        return 0


def load_config(
    target: Path,
    config_path: Path | None = None,
    preset: str | None = None,
    fingerprint: str | None = None,
    workers: int | None = None,
) -> Config:
    root = Path(target).expanduser()
    if not root.exists():
        raise DiscoveryError(f"Path does not exist: {root}")
    search = root if root.is_dir() else root.parent
    config = Config.load(search, config_path, preset)
    if fingerprint:
        try:
            from .models import FingerprintMode

            config.fingerprint = FingerprintMode(fingerprint)
        except ValueError as exc:
            raise ConfigError(f"Unknown fingerprint mode '{fingerprint}' (metadata|full|sampled)") from exc
    if workers is not None:
        config.performance.workers = workers
    return config


def scan(
    target: Path | str,
    config: Config | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    baseline: DatasetDiff | None = None,
) -> ScanResult:
    """Enumerate the dataset, build the manifest and the identity. No rules run here."""
    started = time.perf_counter()
    root = Path(target).expanduser()
    if not root.exists():
        raise DiscoveryError(f"Path does not exist: {root}")
    config = config or load_config(root)
    from .discovery import discover

    spec = discover(root, config)
    workdir = manifest_ops.workdir_for(root if root.is_dir() else root.parent)
    cache = HashCache(workdir / "hashes.jsonl", enabled=config.performance.cache)
    adapter = build_adapter(root, spec, config, cache)
    manifest = manifest_ops.build_manifest(adapter, config, root, progress=progress)
    identity = manifest_ops.build_identity(manifest, spec, adapter, config.config_hash(), config)
    tables: dict[str, Any] = {}
    if adapter.supports("tabular"):
        tables = adapter.tables()
    ctx = AuditContext(
        root=root,
        config=config,
        spec=spec,
        manifest=manifest,
        identity=identity,
        adapter=adapter,
        tables=tables,
        baseline=baseline,
    )
    if config.fingerprint.value != "metadata":
        manifest_ops.save_manifest(manifest, workdir)
    cache.save()
    return ScanResult(
        root=root,
        config=config,
        spec=spec,
        manifest=manifest,
        identity=identity,
        ctx=ctx,
        workdir=workdir,
        duration_ms=int((time.perf_counter() - started) * 1000),
    )


def audit_dataset(
    target: Path | str,
    config: Config | None = None,
    progress: Callable[[str, int, int], None] | None = None,
    baseline_snapshot: str | Path | None = None,
) -> AuditResult:
    config = config or load_config(Path(target))
    baseline: DatasetDiff | None = None
    if baseline_snapshot is not None:
        baseline = diff_against_baseline(Path(target), baseline_snapshot, config)

    scan_result = scan(target, config=config, progress=progress, baseline=baseline)
    started = time.perf_counter()
    findings, outcomes = run_rules(scan_result.ctx)
    duration_ms = scan_result.duration_ms + int((time.perf_counter() - started) * 1000)

    verdict, reasons = eval_safety(findings, outcomes, scan_result.identity.num_samples, scan_result.ctx.dataset_type)
    suppressed = [outcome.rule_id for outcome in outcomes if outcome.status is AuditStatus.SUPPRESSED]
    not_run = [
        outcome.rule_id for outcome in outcomes if outcome.status in (AuditStatus.NOT_RUN, AuditStatus.UNSUPPORTED)
    ]
    inconclusive = [outcome.rule_id for outcome in outcomes if outcome.status is AuditStatus.INCONCLUSIVE]

    report = AuditReport(
        tool_version=_tool_version(),
        generated_at=utcnow(),
        duration_ms=duration_ms,
        identity=scan_result.identity,
        config_hash=config.config_hash(),
        policy_preset=config.preset,
        eval_safety=EvalSafety(verdict),
        eval_safety_reasons=reasons,
        summary=_summary(findings, outcomes, suppressed, not_run),
        rule_outcomes=outcomes,
        findings=findings,
        methodology=list(METHODOLOGY),
        limitations=_limitations(scan_result, inconclusive),
        coverage={
            "rules_total": len(REGISTRY),
            "rules_attempted": len(outcomes),
            "rules_inconclusive": inconclusive,
            "rules_not_run": not_run,
            "rules_suppressed": suppressed,
            "fingerprint_mode": scan_result.manifest.mode.value,
            "sample_fraction": scan_result.manifest.sample_fraction,
            "hashed_samples": sum(1 for record in scan_result.manifest.records if record.sha256 or record.row_sha256),
            "config_warnings": list(config.warnings),
            "inference_notes": list(scan_result.spec.inference_notes),
            "adapter_notes": list(scan_result.ctx.adapter.notes),
            "skipped_files": list(getattr(scan_result.ctx.adapter, "skipped", []))[:50],
            "unreadable_files": list(getattr(scan_result.ctx.adapter, "unreadable", []))[:50],
            "python": sys_version(),
            "platform": sys_platform(),
            "elapsed_ms": duration_ms,
        },
    )
    return AuditResult(scan=scan_result, report=report, findings=findings)


def run_rules(ctx: AuditContext) -> tuple[list[AuditFinding], list[RuleOutcome]]:
    """Execute every detector once, then judge each rule separately.

    DD018 and DD019 share one detector (both read the same diff), so results are
    cached per detector and re-bucketed per rule id, with finding ids renumbered so
    every rule's findings are ``<RULE>-0001, -0002, ...`` (spec section 70).
    """
    runs: dict[int, dict[str, Any]] = {}
    for _rule_id, detector in DETECTORS:
        runs.setdefault(id(detector), {"detector": detector, "findings": [], "status": None, "reason": None, "ms": 0})
    for entry in runs.values():
        entry.update(_execute(ctx, entry["detector"]))

    findings: list[AuditFinding] = []
    outcomes: list[RuleOutcome] = []
    counters: dict[str, int] = {}
    for rule_id, detector in DETECTORS:
        entry = runs[id(detector)]
        suppression = ctx.config.suppression_for(rule_id)
        produced: list[AuditFinding]
        if suppression is not None:
            produced, status, reason = [], AuditStatus.SUPPRESSED, suppression.reason
        elif entry["status"] is not None:
            produced, status, reason = [], entry["status"], entry["reason"]
        else:
            produced = [item for item in entry["findings"] if item.rule_id == rule_id]
            status, reason = (_status_of(produced) if produced else AuditStatus.PASS), None

        kept: list[AuditFinding] = []
        for finding in produced:
            counters[rule_id] = counters.get(rule_id, 0) + 1
            finding = finding.model_copy(update={"finding_id": f"{rule_id}-{counters[rule_id]:04d}"})
            finding = apply_policy(finding, _policy_severity(ctx.config, finding))
            kept.append(finding)
        findings.extend(kept)
        outcomes.append(
            outcome_for(
                rule_id,
                kept,
                status,
                suppression_reason=reason if status is AuditStatus.SUPPRESSED else None,
                skip_reason=None if status is AuditStatus.SUPPRESSED else reason,
                duration_ms=int(entry["ms"]),
            )
        )
    return findings, outcomes


def _execute(ctx: AuditContext, detector: Callable[[AuditContext], list[Any]]) -> dict[str, Any]:
    """Run one detector and translate its exceptions into statuses. Never a silent PASS."""
    started = time.perf_counter()
    try:
        produced = list(detector(ctx) or [])
    except NotApplicable as exc:
        return {
            "findings": [],
            "status": AuditStatus(exc.status),
            "reason": str(exc.reason),
            "ms": int((time.perf_counter() - started) * 1000),
        }
    except InsufficientEvidence as exc:
        return {
            "findings": [],
            "status": AuditStatus.INCONCLUSIVE,
            "reason": str(exc.reason),
            "ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as exc:  # a broken rule must not abort the whole audit
        LOGGER.warning("rule for %s failed: %s: %s", getattr(detector, "__name__", detector), type(exc).__name__, exc)
        return {
            "findings": [],
            "status": AuditStatus.INCONCLUSIVE,
            "reason": f"detector error {type(exc).__name__}: {exc}",
            "ms": int((time.perf_counter() - started) * 1000),
        }
    return {"findings": produced, "status": None, "reason": None, "ms": int((time.perf_counter() - started) * 1000)}


def _status_of(produced: list[AuditFinding]) -> AuditStatus:
    if any(item.status is AuditStatus.FAIL for item in produced):
        return AuditStatus.FAIL
    if any(item.status is AuditStatus.INCONCLUSIVE for item in produced):
        return AuditStatus.INCONCLUSIVE
    if any(item.status is AuditStatus.WARNING for item in produced):
        return AuditStatus.WARNING
    if all(item.severity is Severity.INFO for item in produced):
        return AuditStatus.PASS
    return AuditStatus.WARNING


def _policy_severity(config: Config, finding: AuditFinding) -> Severity | None:
    """Policy may override a rule's severity, but a within-split override is its own knob.

    ``policies.exact_duplicate.severity`` is about the leakage case people suppress the
    rule for; ``within_split_severity`` covers the redundancy case, so one override
    cannot silently flatten the distinction the whole tool exists to make.
    """
    from .rules import RULE_TO_POLICY

    policy_name = RULE_TO_POLICY.get(finding.rule_id)
    if not policy_name:
        return None
    item = config.policies.item(policy_name)
    scope = str(finding.metadata.get("scope", ""))
    if scope == "within_split":
        override = item.extra_settings().get("within_split_severity")
        if override is None:
            return None
        try:
            return Severity(str(override))
        except ValueError:
            return None
    return item.severity


def _summary(
    findings: list[AuditFinding],
    outcomes: list[RuleOutcome],
    suppressed: list[str],
    not_run: list[str],
) -> Any:
    from .models import AuditSummary

    by_category: dict[str, int] = {}
    for finding in findings:
        key = finding.category.value
        by_category[key] = by_category.get(key, 0) + 1
    return AuditSummary(
        total_findings=len(findings),
        by_severity=severity_counts(findings),
        by_status={
            status.value: sum(1 for outcome in outcomes if outcome.status is status)
            for status in AuditStatus
            if any(outcome.status is status for outcome in outcomes)
        },
        by_category=dict(sorted(by_category.items())),
        blocking_findings=sum(1 for finding in findings if finding.formal_impact is FormalImpact.BLOCKING),
        suppressed_rules=sorted(suppressed),
        not_run_rules=sorted(not_run),
    )


def _limitations(ctx_scan: ScanResult, inconclusive: list[str]) -> list[str]:
    extra = list(LIMITATIONS)
    if ctx_scan.manifest.mode.value == "metadata":
        extra.insert(
            0,
            "Fingerprint mode 'metadata' was used: file contents were not hashed, so integrity and "
            "duplicate rules answered INCONCLUSIVE rather than PASS.",
        )
    if ctx_scan.manifest.sample_fraction < 1.0 and ctx_scan.manifest.mode.value == "sampled":
        extra.insert(
            0,
            f"Fingerprint mode 'sampled' hashed {ctx_scan.manifest.sample_fraction:.1%} of samples with "
            f"seed {ctx_scan.manifest.seed}; duplication is only measured inside that subset.",
        )
    if inconclusive:
        extra.append("Rules that could not reach a verdict: " + ", ".join(sorted(inconclusive)) + ".")
    return extra


# ------------------------------------------------------------------------ helpers
def fingerprint_dataset(
    target: Path | str,
    config: Config | None = None,
    progress: Callable[[str, int, int], None] | None = None,
) -> ScanResult:
    return scan(target, config=config, progress=progress)


def snapshot_dataset(
    target: Path | str,
    name: str | None = None,
    config: Config | None = None,
    audit: bool = False,
    directory: Path | None = None,
) -> tuple[DatasetSnapshot, Path]:
    from .snapshots import new_snapshot_name

    if audit:
        result = audit_dataset(target, config=config)
        report = result.report
        scan_result = result.scan
    else:
        scan_result = scan(target, config=config)
        report = None
    snapshot = build_snapshot(
        scan_result.manifest, scan_result.identity, new_snapshot_name(scan_result.root, name), report
    )
    return snapshot, save_snapshot(snapshot, directory)


def diff_against_baseline(target: Path, baseline: str | Path, config: Config) -> DatasetDiff:
    """Compare the dataset as it is now against a stored snapshot."""
    root = Path(target).expanduser().resolve()
    snapshot, _ = resolve_snapshot(root, str(baseline))
    current = scan(root, config=config)
    fresh = build_snapshot(current.manifest, current.identity, "current", None)
    return compare_snapshots(snapshot, fresh, left_source=str(baseline), right_source=str(root))


def diff_targets(
    left: str | Path,
    right: str | Path,
    fingerprint: str | None = None,
) -> DatasetDiff:
    """``dataset-doctor diff A B``, where each side is a dataset directory or a snapshot."""

    search_roots = tuple(Path(str(value)).expanduser() for value in (left, right))

    def resolve(value: str | Path) -> tuple[DatasetSnapshot, str]:
        from .errors import DiffError
        from .snapshots import load_snapshot

        path = Path(str(value)).expanduser()
        if path.is_dir():
            config = load_config(path)
            if fingerprint:
                config.fingerprint = FingerprintMode(fingerprint)
            scan_result = scan(path, config=config)
            return build_snapshot(scan_result.manifest, scan_result.identity, path.name, None), str(path.resolve())
        if path.is_file():
            return load_snapshot(path), str(path.resolve())
        try:
            snapshot, found = resolve_snapshot(Path.cwd(), str(value), extra_roots=search_roots)
        except Exception as exc:
            raise DiffError(f"Cannot resolve dataset or snapshot '{value}': {exc}") from exc
        return snapshot, str(found)

    left_snapshot, left_source = resolve(left)
    right_snapshot, right_source = resolve(right)
    return compare_snapshots(left_snapshot, right_snapshot, left_source, right_source)


def _tool_version() -> str:
    from . import __version__

    return __version__


def sys_version() -> str:
    import sys

    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def sys_platform() -> str:
    import platform

    return f"{platform.system()}-{platform.machine()}"


def atomic_write(path: Path, payload: str) -> Path:
    """Temp file then rename, so an interrupted run never leaves a half report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return path


__all__ = [
    "AuditResult",
    "ScanResult",
    "atomic_write",
    "audit_dataset",
    "diff_against_baseline",
    "diff_targets",
    "fingerprint_dataset",
    "load_config",
    "run_rules",
    "scan",
    "snapshot_dataset",
]
