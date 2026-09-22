"""Manifest construction, fingerprint modes, dataset identity, and persistence.

``manifest.jsonl`` is the join between an audit run and the bytes on disk: every
finding cites sample ids that resolve back to a manifest row, so a reviewer can
re-check the evidence without re-running the tool.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .adapters.base import DatasetAdapter
from .config import Config
from .hashing import sha256_json
from .models import (
    SCHEMA_VERSION,
    DatasetIdentity,
    DatasetManifest,
    DatasetSpec,
    DatasetType,
    FingerprintMode,
    SampleRecord,
    utcnow,
)

MANIFEST_NAME = "manifest.jsonl"
WORKDIR_NAME = ".dataset-doctor"

SAMPLE_MARKER = "hash_sampled"


def select_hash_subset(records: list[SampleRecord], fraction: float, seed: int) -> set[str]:
    """Deterministic subsample by hash of (seed, sample_id) — stable across runs."""
    if fraction >= 1.0:
        return {record.sample_id for record in records}
    threshold = int(fraction * (2**32))
    chosen: set[str] = set()
    for record in records:
        digest = hashlib.sha256(f"{seed}\x1f{record.sample_id}".encode()).digest()
        if int.from_bytes(digest[:4], "big") < threshold:
            chosen.add(record.sample_id)
    if not chosen and records:
        chosen.add(sorted(record.sample_id for record in records)[0])
    return chosen


def build_manifest(
    adapter: DatasetAdapter,
    config: Config,
    root: Path,
    progress: Any = None,
) -> DatasetManifest:
    mode = config.fingerprint
    sampling = config.sampling
    records = adapter.samples(progress=progress)

    if mode is FingerprintMode.METADATA:
        fraction = 0.0
    elif mode is FingerprintMode.SAMPLED or sampling.enabled:
        fraction = sampling.fraction
    else:
        fraction = 1.0

    chosen = select_hash_subset(records, fraction, sampling.seed) if fraction < 1.0 else None
    if chosen is not None:
        kept: list[SampleRecord] = []
        for record in records:
            picked = record.sample_id in chosen
            metadata = {**record.metadata, SAMPLE_MARKER: picked}
            if not picked:
                metadata = {
                    **metadata,
                    "sha256_unverified": record.sha256 is None,
                }
                record = record.model_copy(update={"sha256": None, "metadata": metadata})
            else:
                record = record.model_copy(update={"metadata": metadata})
            kept.append(record)
        records = kept

    manifest = DatasetManifest(
        root=str(root),
        mode=mode,
        sample_fraction=fraction if mode is not FingerprintMode.METADATA else 0.0,
        seed=sampling.seed,
        records=records,
    )
    return manifest


def metadata_key(record: SampleRecord) -> str:
    """Content-free identity of a sample, used by the metadata fingerprint."""
    return "|".join(
        [
            record.relative_path,
            str(record.size if record.size is not None else ""),
            record.split,
            record.label or "",
        ]
    )


def manifest_hash(manifest: DatasetManifest) -> str:
    """Stable, order-independent digest of the manifest content.

    metadata: relative path + size + label + split
    full:     per-sample SHA256, stable-sorted, then digested (spec section 16)
    sampled:  same as full but over the sampled subset, and never presented as
              a complete integrity hash (spec section 17)
    """
    if manifest.mode is FingerprintMode.METADATA:
        keys = sorted(metadata_key(record) for record in manifest.records)
        payload: Any = {"mode": "metadata", "keys": keys}
    else:
        hashes = sorted(record.sha256 or f"unhashed:{record.sample_id}" for record in manifest.records)
        payload = {
            "mode": manifest.mode.value,
            "sample_fraction": manifest.sample_fraction,
            "hashes": hashes,
        }
    return sha256_json(payload)[:32]


def dataset_id_from(manifest_digest: str, num_samples: int) -> str:
    return f"ds_{hashlib.sha256(f'{manifest_digest}:{num_samples}'.encode()).hexdigest()[:8]}"


def save_manifest(manifest: DatasetManifest, workdir: Path) -> Path:
    workdir.mkdir(parents=True, exist_ok=True)
    path = workdir / MANIFEST_NAME
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "schema_version": manifest.schema_version,
                    "root": manifest.root,
                    "mode": manifest.mode.value,
                    "sample_fraction": manifest.sample_fraction,
                    "seed": manifest.seed,
                    "created_at": manifest.created_at.isoformat(),
                    "count": len(manifest.records),
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        for record in manifest.records:
            handle.write(json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def load_manifest(path: Path) -> DatasetManifest:
    from .errors import SnapshotError

    if not path.is_file():
        raise SnapshotError(f"Manifest not found: {path}. Run `dataset-doctor scan` first.")
    with path.open("r", encoding="utf-8") as handle:
        lines = [line for line in handle.read().splitlines() if line.strip()]
    if not lines:
        raise SnapshotError(f"Manifest is empty: {path}")
    header = json.loads(lines[0])
    records = [SampleRecord.model_validate(json.loads(line)) for line in lines[1:]]
    return DatasetManifest(
        schema_version=header.get("schema_version", SCHEMA_VERSION),
        root=header["root"],
        mode=FingerprintMode(header.get("mode", "full")),
        sample_fraction=float(header.get("sample_fraction", 1.0)),
        seed=int(header.get("seed", 1337)),
        created_at=utcnow(),
        records=records,
    )


def build_identity(
    manifest: DatasetManifest,
    spec: DatasetSpec,
    adapter: DatasetAdapter,
    config_hash: str,
    config: Config,
) -> DatasetIdentity:
    split_sizes: dict[str, int] = {}
    class_counts: dict[str, int] = {}
    extensions: dict[str, int] = {}
    for record in manifest.records:
        split_sizes[record.split] = split_sizes.get(record.split, 0) + 1
        key = record.label if record.label is not None else "<unlabeled>"
        class_counts[key] = class_counts.get(key, 0) + 1
        suffix = Path(record.relative_path.split(";")[0]).suffix.lower()
        if suffix:
            extensions[suffix] = extensions.get(suffix, 0) + 1

    digest = manifest_hash(manifest)
    resolved_type = spec.resolved_type or DatasetType.AUTO
    return DatasetIdentity(
        dataset_id=dataset_id_from(digest, len(manifest.records)),
        root_path=str(Path(manifest.root)),
        dataset_type=resolved_type,
        num_samples=len(manifest.records),
        split_sizes=dict(sorted(split_sizes.items())),
        classes=sorted(class_counts),
        class_counts=dict(sorted(class_counts.items())),
        schema=adapter.schema(),
        file_extensions=dict(sorted(extensions.items())),
        manifest_hash=digest,
        config_hash=config_hash,
        fingerprint_mode=manifest.mode,
        metadata={
            "inference_notes": list(spec.inference_notes),
            "adapter_notes": list(adapter.notes),
            "label_column": getattr(adapter, "label_column", None),
            "group_columns": list(spec.group_columns),
            "provenance_declared": not config.provenance.is_empty,
            "sampled_fraction": manifest.sample_fraction,
        },
    )


def fingerprint_lines(identity: DatasetIdentity) -> list[str]:
    """The human-facing block from spec section 13."""
    lines = [
        f"Dataset ID: {identity.dataset_id}",
        "",
        f"Samples: {identity.num_samples:,}",
    ]
    for name, count in identity.split_sizes.items():
        lines.append(f"  {name}: {count:,}")
    lines += ["", f"Classes: {len(identity.classes)}"]
    lines += ["", f"Fingerprint mode: {identity.fingerprint_mode.value}"]
    if identity.fingerprint_mode is FingerprintMode.SAMPLED:
        lines.append(f"  sampled fraction: {identity.metadata.get('sampled_fraction')}")
    lines += [
        f"Manifest SHA256: {identity.manifest_hash}",
        f"Config hash: {identity.config_hash}",
    ]
    return lines


def workdir_for(root: Path) -> Path:
    return root / WORKDIR_NAME
