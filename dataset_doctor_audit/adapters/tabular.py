"""Tabular adapter: CSV / TSV / Parquet / Feather / Excel, one file (or directory) per split.

Row identity, not file identity, is what matters here: a CSV re-saved with a
different byte order is still the same dataset. Hence two hashes per row
(docs/adr/0002-hash-strategy.md):

* ``row_sha256``    - every column except the split column  -> exact duplicate rows
* ``feature_sha256``- every column except split, id and label -> same features,
                      possibly different label (leakage + label conflict signal)
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

import pandas as pd

from ..errors import AdapterError
from ..hashing import sha256_file, stable_sample_id
from ..models import DatasetType, SampleRecord, SplitRole, SplitSpec
from .base import DatasetAdapter, ProgressFn

TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".feather", ".xlsx", ".xls"}
LABEL_CANDIDATES = ("label", "target", "class", "y", "category", "outcome")
NULL_TOKENS = {"", "na", "n/a", "nan", "null", "none", "unknown", "-", "?", "<na>"}


class TabularAdapter(DatasetAdapter):
    dataset_type: ClassVar[DatasetType] = DatasetType.TABULAR
    capabilities: ClassVar[frozenset[str]] = frozenset({"tabular", "columns", "rows"})

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._frames: dict[str, pd.DataFrame] = {}
        self._column_types: dict[str, str] = {}

    # --------------------------------------------------------------------- read
    def split_files(self, split: SplitSpec) -> list[Path]:
        path = Path(split.path)
        if not path.is_absolute():
            path = self.root / path
        if path.is_file():
            return [path]
        if not path.is_dir():
            # `relative`, not `str`: these entries are copied verbatim into DD016's evidence,
            # into `location.paths`, and into `coverage.unreadable_files`, and a report is
            # written to be attached to a paper.
            self.unreadable.append({"path": self.relative(path), "reason": "split path does not exist"})
            return []
        files = sorted(
            f
            for f in path.rglob("*")
            if f.is_file() and f.suffix.lower() in TABULAR_SUFFIXES and not f.name.startswith(".")
        )
        if not files:
            self.unreadable.append({"path": self.relative(path), "reason": "no tabular file found"})
        return files

    @staticmethod
    def _read(path: Path, split_name: str | None = None) -> pd.DataFrame:
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            return pd.read_csv(path, sep="\t" if suffix == ".tsv" else None, engine="python")
        if suffix in {".parquet", ".pq"}:
            return pd.read_parquet(path)
        if suffix == ".feather":
            return pd.read_feather(path)
        if suffix in {".xlsx", ".xls"}:
            return TabularAdapter._read_workbook(path, split_name)
        raise AdapterError(f"Unsupported tabular format: {path.suffix}")

    @staticmethod
    def _read_workbook(path: Path, split_name: str | None) -> pd.DataFrame:
        """One workbook contributes one split, and the sheet is chosen rather than assumed.

        The pandas default is the first sheet, which would audit 40 rows of a 68-row
        train/test workbook and report nothing was missed. So: the split name names a sheet,
        or the workbook has exactly one sheet, or the file is refused with its sheet list.
        """
        book = pd.read_excel(path, sheet_name=None)
        wanted = _canonical_split(split_name or "")
        if wanted:
            for title, frame in book.items():
                if _canonical_split(str(title)) == wanted:
                    return frame
        if len(book) == 1:
            return next(iter(book.values()))
        named = f" for split '{split_name}'" if split_name else ""
        raise AdapterError(
            f"{path.name} has {len(book)} sheets ({', '.join(str(title) for title in book)})"
            f"{named} and none of them matches{'' if split_name else ' (no split was declared)'}. "
            "Refusing to read the first sheet alone: the other rows would be audited as if they "
            "did not exist. Name a sheet after the split, or export one file per split."
        )

    def _load(self, split: SplitSpec) -> pd.DataFrame:
        if split.name in self._frames:
            return self._frames[split.name]
        frames = []
        for file in self.split_files(split):
            try:
                frame = self._read(file, split.name)
            except Exception as exc:  # surfaced as DD016/UNSUPPORTED, not a crash
                self.unreadable.append({"path": self.relative(file), "reason": f"{type(exc).__name__}: {exc}"})
                continue
            frames.append(frame)
        if not frames:
            frame = pd.DataFrame()
        elif len(frames) == 1:
            frame = frames[0]
        else:
            frame = pd.concat(frames, ignore_index=True)
            self.note(f"Split '{split.name}' merged from {len(frames)} table files")
        self._frames[split.name] = frame
        return frame

    # ----------------------------------------------------------------- columns
    def columns(self, split: str | None = None) -> list[str]:
        targets = [s for s in self.splits if split is None or s.name == split]
        names: list[str] = []
        for split_spec in targets:
            for column in self._load(split_spec).columns:
                if column not in names:
                    names.append(str(column))
        return names

    def infer_label_column(self) -> str | None:
        if self.spec.label_column:
            return self.spec.label_column
        if self.spec.label_source == "none":
            return None
        available = self.columns()
        for candidate in LABEL_CANDIDATES:
            if candidate in available:
                self.note(f"Label column inferred as '{candidate}'. Set labels.column to make this explicit.")
                return candidate
        return None

    def feature_columns(self, exclude: Iterable[str] = ()) -> list[str]:
        skip = {self.spec.split_column, self.label_column, *self.spec.id_columns, *exclude}
        union: set[str] = set()
        for split in self.splits:
            union.update(str(c) for c in self._load(split).columns)
        return [column for column in sorted(union) if column not in skip]

    @property
    def label_column(self) -> str | None:
        if not hasattr(self, "_label_column"):
            self._label_column = self.infer_label_column()
        return self._label_column

    def schema(self) -> dict[str, str]:
        schema: dict[str, str] = {}
        for split in self.splits:
            frame = self._load(split)
            for column in frame.columns:
                dtype = describe_dtype(frame[column])
                previous = schema.get(str(column))
                if previous is None:
                    schema[str(column)] = dtype
                elif previous != dtype:
                    schema[str(column)] = f"{previous}|{dtype}"
        return schema

    def tables(self) -> dict[str, pd.DataFrame]:
        return {split.name: self._load(split) for split in self.splits}

    # --------------------------------------------------------------- samples
    def samples(self, progress: ProgressFn = None) -> list[SampleRecord]:
        records: list[SampleRecord] = []
        for split in self.splits:
            frame = self._load(split)
            if frame.empty:
                self.note(f"Split '{split.name}' is empty")
                continue
            records.extend(self._records_for(split, frame))
            if progress:
                progress(split.name, len(records), max(1, sum(len(self._frames[s]) for s in self._frames)))
        if self.spec.split_column:
            records = self._resplit_by_column(records)
        return self.require_non_empty(records)

    def _records_for(self, split: SplitSpec, frame: pd.DataFrame) -> list[SampleRecord]:
        source = Path(split.path)
        files = self.split_files(split)
        file_hash = {str(f): sha256_file(f) for f in files} if files else {}
        rel_paths = [self.relative(f) for f in files] or [self.relative(source)]
        all_columns = [str(c) for c in frame.columns]
        feature_cols = [
            c for c in all_columns if c not in {self.spec.split_column, self.label_column, *self.spec.id_columns}
        ]
        row_values = _stringify(frame, all_columns)
        # The row's *content* identity excludes the split column: moving a row between
        # splits is a split move, not an edit to the observation itself.
        content_columns = [c for c in all_columns if c != self.spec.split_column]
        content_values = row_values if len(content_columns) == len(all_columns) else _stringify(frame, content_columns)
        feature_values = _stringify(frame[feature_cols], feature_cols) if feature_cols else [""] * len(frame)
        label_series = (
            frame[self.label_column].tolist()
            if self.label_column and self.label_column in frame
            else [None] * len(frame)
        )
        group_series = {column: frame[column].tolist() for column in self.spec.group_columns if column in frame}
        time_values = (
            frame[self.spec.temporal_column].tolist()
            if self.spec.temporal_column and self.spec.temporal_column in frame
            else [None] * len(frame)
        )
        id_values = (
            frame[self.spec.id_columns].astype(str).agg("\x1f".join, axis=1).tolist()
            if self.spec.id_columns and set(self.spec.id_columns) <= set(all_columns)
            else [None] * len(frame)
        )
        split_values = (
            frame[self.spec.split_column].tolist()
            if self.spec.split_column and self.spec.split_column in all_columns
            else [None] * len(frame)
        )

        records: list[SampleRecord] = []
        single_file = len(rel_paths) == 1
        for index in range(len(frame)):
            row_key = row_values[index]
            content_key = content_values[index]
            feature_key = feature_values[index]
            explicit_id = id_values[index]
            sample_id = (
                stable_sample_id(split.name, explicit_id)
                if explicit_id and explicit_id.strip("\x1f")
                else stable_sample_id(rel_paths[0] if single_file else split.name, index, row_key[:64])
            )
            label = _clean_label(label_series[index])
            groups: dict[str, str] = {}
            for column in group_series:
                # A row without a group value is not assigned a fake entity: it simply
                # carries no membership for that column, and DD005 reports how many did.
                value = _clean_text(group_series[column][index])
                if value is not None:
                    groups[column] = value
            metadata: dict[str, Any] = {
                "row_index": index,
                "feature_sha256": stable_sample_id(feature_key) if feature_key else None,
                "file_sha256": file_hash.get(str(files[0])) if single_file and files else None,
            }
            if explicit_id and explicit_id.strip("\x1f"):
                metadata["external_id"] = explicit_id.replace("\x1f", "|")
            split_value = _clean_text(split_values[index])
            if split_value is not None:
                metadata["split_value"] = split_value
            if not single_file:
                metadata["source_file"] = rel_paths[min(index, len(rel_paths) - 1)]
            moment = _clean_text(time_values[index])
            if moment is not None:
                metadata["time"] = moment
            records.append(
                SampleRecord(
                    sample_id=sample_id,
                    relative_path=rel_paths[0] if single_file else ";".join(rel_paths),
                    split=split.name,
                    label=label,
                    size=None,
                    row_sha256=stable_sample_id(content_key),
                    sha256=metadata["file_sha256"],
                    groups=groups,
                    metadata=metadata,
                )
            )
        return records

    def _resplit_by_column(self, records: list[SampleRecord]) -> list[SampleRecord]:
        column = self.spec.split_column
        assert column is not None
        out: list[SampleRecord] = []
        seen: set[str] = set()
        for record in records:
            raw = record.metadata.get("split_value")
            name = _canonical_split(str(raw)) if raw is not None else "unknown"
            seen.add(name)
            out.append(record.model_copy(update={"split": name}))
        from ..config import role_for

        self.spec.splits = [
            SplitSpec(name=name, path=str(self.root), role=role_for(name), kind="column") for name in sorted(seen)
        ]
        self.note(f"Splits assigned from the '{column}' column: {', '.join(sorted(seen))}")
        return out


def _stringify(frame: pd.DataFrame, columns: list[str]) -> list[str]:
    """Deterministic per-row key string. NaN has one spelling, not four."""
    series_list = []
    for column in columns:
        if column in frame.columns:
            series_list.append([_cell(value) for value in frame[column].tolist()])
        else:
            series_list.append([""] * len(frame))
    return ["\x1f".join(row) for row in zip(*series_list, strict=False)]


def _cell(value: Any) -> str:
    if value is None:
        return "\x00"
    if isinstance(value, float) and math.isnan(value):
        return "\x00"
    try:
        if pd.isna(value):
            return "\x00"
    except (TypeError, ValueError):
        pass
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return repr(round(value, 12))
    return str(value)


def _clean_text(value: Any) -> str | None:
    text = _cell(value)
    if text == "\x00":
        return None
    return text.strip()


def _clean_label(value: Any) -> str | None:
    text = _clean_text(value)
    if text is None:
        return None
    return text if text.lower() not in NULL_TOKENS else None


def _canonical_split(raw: str) -> str:
    from ..config import role_for

    key = raw.strip().lower()
    if not key:
        return "unknown"
    return role_for(key).value if role_for(key) is not SplitRole.UNKNOWN else key


def describe_dtype(series: pd.Series) -> str:
    dtype = series.dtype
    name = str(dtype)
    if name in {"object", "string", "str"}:
        non_null = series.dropna()
        if len(non_null) and non_null.astype(str).str.strip().isin(NULL_TOKENS).all():
            return "string:null-like"
        return "string"
    if "int" in name:
        return "int"
    if "float" in name:
        return "float"
    if "bool" in name:
        return "bool"
    if "datetime" in name:
        return "datetime"
    if "category" in name:
        return "category"
    if "bytes" in name:
        return "bytes"
    return name
