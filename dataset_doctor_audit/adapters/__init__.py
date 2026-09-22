"""Adapter selection."""

from __future__ import annotations

from pathlib import Path

from ..config import Config
from ..errors import DiscoveryError
from ..hashing import HashCache
from ..models import DatasetSpec, DatasetType
from .base import DatasetAdapter
from .imagefolder import ImageFolderAdapter
from .tabular import TabularAdapter

__all__ = ["DatasetAdapter", "ImageFolderAdapter", "TabularAdapter", "build_adapter"]

_REGISTRY: dict[DatasetType, type[DatasetAdapter]] = {
    DatasetType.TABULAR: TabularAdapter,
    DatasetType.IMAGE: ImageFolderAdapter,
}


def build_adapter(root: Path, spec: DatasetSpec, config: Config, cache: HashCache | None = None) -> DatasetAdapter:
    resolved = spec.resolved_type
    if resolved is None or resolved is DatasetType.AUTO:
        raise DiscoveryError(
            f"Could not determine the dataset type of {root}. Set `dataset.type` in dataset-doctor.yaml."
        )
    adapter_cls = _REGISTRY.get(resolved)
    if adapter_cls is None:  # pragma: no cover - guarded by registry contents
        raise DiscoveryError(f"No adapter registered for dataset type '{resolved.value}'.")
    adapter = adapter_cls(root, spec, config, cache)
    if resolved is DatasetType.IMAGE and spec.label_source not in (None, "directory"):
        adapter.note(
            f"labels.source='{spec.label_source}' is not implemented for image datasets in V0.1; "
            "labels were read from the directory name."
        )
    return adapter
