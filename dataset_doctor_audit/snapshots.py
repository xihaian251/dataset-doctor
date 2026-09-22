"""Version snapshots: cheap, content-free records of what a dataset was.

A snapshot stores the manifest projection plus the identity and a findings digest -
never the data itself (spec section 67). That is what makes it reasonable to commit
to a repository, and what makes ``dataset-doctor-audit diff`` able to answer "did the test
set change?" months later.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .errors import SnapshotError
from .manifest import WORKDIR_NAME
from .models import (
    SCHEMA_VERSION,
    AuditReport,
    DatasetIdentity,
    DatasetManifest,
    DatasetSnapshot,
    SnapshotRecord,
    utcnow,
)

SNAPSHOT_SUBDIR = "snapshots"
FINDING_DIGEST_RULES = ("DD003", "DD004", "DD005", "DD006", "DD007", "DD009", "DD019")


def snapshot_root(root: Path) -> Path:
    return Path(root) / WORKDIR_NAME / SNAPSHOT_SUBDIR


def build_snapshot(
    manifest: DatasetManifest,
    identity: DatasetIdentity,
    name: str,
    report: AuditReport | None = None,
) -> DatasetSnapshot:
    return DatasetSnapshot(
        name=name,
        identity=identity,
        fingerprint_mode=manifest.mode,
        records=[
            SnapshotRecord(
                sample_id=record.sample_id,
                relative_path=record.relative_path,
                split=record.split,
                label=record.label,
                size=record.size,
                sha256=record.sha256 or record.row_sha256,
                row_sha256=record.row_sha256,
                feature_sha256=record.metadata.get("feature_sha256"),
                groups=dict(record.groups),
            )
            for record in manifest.records
        ],
        findings_digest=findings_digest(report),
        source_report=None if report is None else str(report.identity.root_path),
    )


def findings_digest(report: AuditReport | None) -> dict[str, Any]:
    """Per-finding summary used by diff. Keyed by rule + scope + split pair so the
    key survives a change of counts inside the finding."""
    if report is None:
        return {}
    entries: dict[str, dict[str, Any]] = {}
    for finding in report.findings:
        key = "|".join(
            [
                finding.rule_id,
                str(finding.metadata.get("scope", "-")),
                finding.source_split or "-",
                finding.target_split or "-",
            ]
        )
        entry = entries.setdefault(
            key,
            {
                "rule_id": finding.rule_id,
                "title": finding.title,
                "severities": {},
                "statuses": {},
                "affected_count": 0,
                "evidence_keys": [],
            },
        )
        entry["severities"][finding.severity.value] = entry["severities"].get(finding.severity.value, 0) + 1
        entry["statuses"][finding.status.value] = entry["statuses"].get(finding.status.value, 0) + 1
        entry["affected_count"] += finding.affected_count
        digest = json.dumps(finding.evidence, sort_keys=True, ensure_ascii=False, default=str)
        entry["evidence_keys"].append(_evidence_key(digest))
    return {
        "schema_version": SCHEMA_VERSION,
        "eval_safety": report.eval_safety.value,
        "manifest_hash": report.identity.manifest_hash,
        "entries": {key: entries[key] for key in sorted(entries)},
    }


def _evidence_key(serialised: str) -> str:
    import hashlib

    return hashlib.sha256(serialised.encode("utf-8")).hexdigest()[:16]


def save_snapshot(snapshot: DatasetSnapshot, directory: Path | None = None) -> Path:
    target = directory or snapshot_root(Path(snapshot.identity.root_path))
    target.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(char if char.isalnum() or char in "._-" else "_" for char in snapshot.name)
    path = target / f"{safe_name}.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return path


def load_snapshot(path: Path) -> DatasetSnapshot:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SnapshotError(f"Cannot read snapshot {path}: {exc}") from exc
    try:
        return DatasetSnapshot.model_validate(payload)
    except Exception as exc:
        raise SnapshotError(f"Snapshot {path} does not match schema {SCHEMA_VERSION}: {exc}") from exc


def list_snapshots(root: Path, directory: Path | None = None) -> list[Path]:
    target = Path(directory) if directory else snapshot_root(Path(root))
    if not target.is_dir():
        return []
    return sorted(target.glob("*.json"))


def resolve_snapshot(root: Path, name: str, extra_roots: tuple[Path, ...] = ()) -> tuple[DatasetSnapshot, Path]:
    """Accept a path to a snapshot file, or a name/id found under .dataset-doctor.

    ``extra_roots`` lets a ``diff`` look for a named snapshot inside the dataset it is
    being compared with, which is where ``--save-snapshot`` actually put it.
    """
    candidate = Path(name)
    if candidate.is_file():
        return load_snapshot(candidate), candidate
    available = list_snapshots(root)
    for extra in extra_roots:
        for path in list_snapshots(extra):
            if path not in available:
                available.append(path)
    for path in available:
        if path.stem == name or str(path) == name:
            return load_snapshot(path), path
    matches: list[tuple[DatasetSnapshot, Path]] = []
    for path in available:
        snapshot = load_snapshot(path)
        if snapshot.name == name or snapshot.identity.dataset_id == name:
            matches.append((snapshot, path))
    if len(matches) == 1:
        return matches[0]
    known_names = ", ".join(sorted(path.stem for path in available)) or "(none - run `dataset-doctor-audit snapshot`)"
    raise SnapshotError(
        f"No snapshot named '{name}' under {snapshot_root(root)}"
        + "".join(f" or {snapshot_root(Path(extra))}" for extra in extra_roots)
        + f". Known: {known_names}."
        " A snapshot is stored inside the dataset it describes, so pass that directory as the other"
        " side of the diff, or give the path to the .json file."
    )


def snapshot_summary(snapshot: DatasetSnapshot) -> list[str]:
    identity = snapshot.identity
    return [
        f"Snapshot: {snapshot.name}",
        f"Created: {snapshot.created_at.isoformat()}",
        f"Dataset ID: {identity.dataset_id}",
        f"Samples: {identity.num_samples:,}",
        "Splits: " + ", ".join(f"{key}={value}" for key, value in identity.split_sizes.items()),
        f"Fingerprint: {snapshot.fingerprint_mode.value} / {identity.manifest_hash}",
        f"Records stored: {len(snapshot.records):,}",
    ]


def new_snapshot_name(root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    directory = snapshot_root(Path(root))
    stamp = utcnow().strftime("%Y%m%dT%H%M%SZ")
    base = Path(root).name or "dataset"
    name = f"{base}-{stamp}"
    index = 1
    while (directory / f"{name}.json").exists():
        index += 1
        name = f"{base}-{stamp}-{index}"
    return name
