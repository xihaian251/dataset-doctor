"""Adapter layer: turn a directory tree or a set of tables into ``SampleRecord``s.

Detectors never touch the filesystem directly, which is what keeps near-duplicate
logic from leaking into the tabular path and vice versa (spec section 105).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from ..config import Config
from ..errors import AdapterError
from ..hashing import HashCache
from ..models import DatasetSpec, DatasetType, SampleRecord, SplitSpec

ProgressFn = Callable[[str, int, int], None] | None


class DatasetAdapter(ABC):
    dataset_type: ClassVar[DatasetType]
    capabilities: ClassVar[frozenset[str]] = frozenset()

    def __init__(
        self,
        root: Path,
        spec: DatasetSpec,
        config: Config,
        cache: HashCache | None = None,
    ) -> None:
        self.root = Path(root)
        self.spec = spec
        self.config = config
        self.cache = cache
        self.notes: list[str] = []
        #: Files the adapter refused to read, each with the reason. Reported under DD016 and
        #: quoted by ``require_non_empty`` so an empty dataset explains itself.
        self.unreadable: list[dict[str, str]] = []

    # ------------------------------------------------------------------ surface
    @abstractmethod
    def samples(self, progress: ProgressFn = None) -> list[SampleRecord]:
        """Enumerate samples. Content hashing happens here per fingerprint mode."""

    def tables(self) -> dict[str, pd.DataFrame]:
        return {}

    def schema(self) -> dict[str, str]:
        return {}

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def note(self, message: str) -> None:
        if message not in self.notes:
            self.notes.append(message)

    # ------------------------------------------------------------------- shared
    @property
    def splits(self) -> list[SplitSpec]:
        return self.spec.splits

    def require_non_empty(self, records: list[SampleRecord]) -> list[SampleRecord]:
        if not records:
            # "Nothing was found" is only useful if it says why. A file that was refused
            # (an ambiguous workbook, a corrupt table) is otherwise invisible here, because
            # the refusal lands in `unreadable` and the audit dies on the empty check first.
            reasons = "; ".join(f"{item.get('path', '?')}: {item.get('reason', '?')}" for item in self.unreadable[:5])
            raise AdapterError(
                f"No samples found under {self.root} with the detected layout "
                f"({'; '.join(self.spec.inference_notes) or 'no inference notes'}). "
                + (f"Files that were not read -> {reasons}. " if reasons else "")
                + "Specify `splits:` in dataset-doctor.yaml."
            )
        return records

    def relative(self, path: Path) -> str:
        # Both sides are resolved: `audit ./data` and `audit /abs/data` must produce the same
        # sample ids, or the manifest hash - and with it DD018/DD019 - changes with how the
        # command happened to be typed, and reports leak the caller's absolute path.
        root = self.root.resolve()
        try:
            return path.resolve().relative_to(root).as_posix()
        except ValueError:
            return path.resolve().as_posix()

    def label_of(self, record_path: Path, split: SplitSpec) -> str | None:
        """Image-folder convention: the parent directory is the class name."""
        source = Path(split.path)
        try:
            rel = record_path.resolve().relative_to(source.resolve())
        except ValueError:
            return None
        if len(rel.parts) < 2:
            return None
        return rel.parts[0]


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]
