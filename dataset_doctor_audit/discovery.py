"""Dataset structure discovery.

Never assume the directory layout is standard (spec section 10): probe several
shapes, record what was inferred, and let the report show it. An unresolved split
is reported as ``unknown`` so downstream rules can answer INCONCLUSIVE instead of
silently treating "one big pile" as a safe train/test separation.
"""

from __future__ import annotations

from pathlib import Path

from .config import Config, role_for
from .errors import DiscoveryError
from .models import DatasetSpec, DatasetType, SplitRole, SplitSpec

TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".xlsx", ".xls", ".feather"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
SPLIT_DIR_NAMES = {
    "train",
    "training",
    "trn",
    "val",
    "valid",
    "validation",
    "dev",
    "test",
    "testing",
    "tst",
    "eval",
    "evaluate",
}


def discover(root: Path, config: Config) -> DatasetSpec:
    root = root.expanduser().resolve()
    if not root.exists():
        raise DiscoveryError(f"Path does not exist: {root}")

    spec = config.to_dataset_spec(root)

    if config.splits:
        spec.resolved_type = _type_from_paths(
            [Path(p) if Path(p).is_absolute() else root / p for p in config.splits.values()],
            config,
            spec,
        )
        return spec

    if root.is_file():
        return _from_single_file(root, spec, config)

    if spec.splits:
        spec.resolved_type = _type_from_paths([root / s.path for s in spec.splits], config, spec)
        return spec

    return _from_directory(root, spec, config)


def _from_single_file(path: Path, spec: DatasetSpec, config: Config) -> DatasetSpec:
    spec.inference_notes.append(f"Root is a single file: {path.name}")
    if path.suffix.lower() in IMAGE_SUFFIXES:
        raise DiscoveryError("A single image file is not an auditable dataset.")
    split_column = config.temporal.split_column or _find_split_column(path)
    if split_column:
        spec.splits = []  # resolved row-by-row by the tabular adapter
        spec.split_column = split_column
        spec.inference_notes.append(f"Splits read from the '{split_column}' column inside {path.name}")
    else:
        spec.splits = [SplitSpec(name="all", path=str(path), role=SplitRole.UNKNOWN, kind="file")]
        spec.inference_notes.append("No train/val/test split found: cross-split checks will be INCONCLUSIVE.")
    spec.resolved_type = DatasetType.TABULAR
    return spec


def _from_directory(root: Path, spec: DatasetSpec, config: Config) -> DatasetSpec:
    child_dirs = sorted(
        d for d in root.iterdir() if d.is_dir() and not is_ignored(d.name, config) and d.name.lower() in SPLIT_DIR_NAMES
    )
    table_files = sorted(
        f
        for f in root.iterdir()
        if f.is_file() and f.suffix.lower() in TABULAR_SUFFIXES and not is_ignored(f.name, config)
    )
    nested_tables = sorted(d for d in root.iterdir() if d.is_dir() and _contains_tables(d, config))

    if child_dirs and not table_files:
        spec.resolved_type = _type_from_paths(child_dirs, config, spec)
        for d in child_dirs:
            spec.splits.append(
                SplitSpec(
                    name=_canonical_split_name(d.name),
                    path=str(d),
                    role=role_for(d.name),
                    kind="directory",
                )
            )
        spec.inference_notes.append("Splits discovered as subdirectories: " + ", ".join(s.name for s in spec.splits))
        return spec

    split_files = [f for f in table_files if f.stem.lower() in SPLIT_DIR_NAMES]
    if split_files:
        spec.resolved_type = DatasetType.TABULAR
        # A directory and a file can both name the same split (train/ next to train.csv is
        # what a half-finished conversion leaves behind). Dropping either one silently would
        # audit part of the data, so both are registered and the collision is stated.
        directories = {_canonical_split_name(d.name): d for d in child_dirs}
        for name, directory in sorted(directories.items()):
            spec.splits.append(
                SplitSpec(name=name, path=str(directory), role=role_for(directory.name), kind="directory")
            )
        for f in split_files:
            name = _canonical_split_name(f.stem)
            if name in directories:
                # One split may not have two sources: the adapter loads frames by split name,
                # so a second registration would be silently ignored. The directory wins and
                # the file is reported rather than dropped.
                spec.inference_notes.append(
                    f"Not audited: {f.name} and {directories[name].name}/ both name the split "
                    f"'{name}'. The directory was kept. Merge them or rename one, otherwise the "
                    "audit of that split is not the whole split."
                )
                continue
            spec.splits.append(SplitSpec(name=name, path=str(f), role=role_for(f.stem), kind="file"))
        others = [f.name for f in table_files if f not in split_files]
        if others:
            spec.inference_notes.append(
                "Table files not named as a split and therefore not audited: " + ", ".join(others)
            )
        spec.inference_notes.append(
            "Splits discovered from files and directories: " + ", ".join(f"{s.name}({s.kind})" for s in spec.splits)
        )
        return spec

    if nested_tables and len(nested_tables) <= 6:
        spec.resolved_type = DatasetType.TABULAR
        for d in nested_tables:
            spec.splits.append(
                SplitSpec(
                    name=_canonical_split_name(d.name),
                    path=str(d),
                    role=role_for(d.name),
                    kind="directory",
                )
            )
        spec.inference_notes.append(
            "Splits inferred from directories containing table files: " + ", ".join(s.name for s in spec.splits)
        )
        return spec

    # one data directory wrapping train/val/test, e.g. ./data/train
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not is_ignored(p.name, config)):
        inner = sorted(c for c in d.iterdir() if c.is_dir() and c.name.lower() in SPLIT_DIR_NAMES)
        if len(inner) >= 2:
            spec.resolved_type = _type_from_paths(inner, config, spec)
            for c in inner:
                spec.splits.append(
                    SplitSpec(
                        name=_canonical_split_name(c.name),
                        path=str(c),
                        role=role_for(c.name),
                        kind="directory",
                    )
                )
            spec.inference_notes.append(f"Splits discovered under {d.name}/: " + ", ".join(s.name for s in spec.splits))
            return spec

    # last resort: undifferentiated data
    spec.resolved_type = _type_from_paths([root], config, spec)
    spec.splits = [SplitSpec(name="all", path=str(root), role=SplitRole.UNKNOWN)]
    spec.inference_notes.append(
        "No train/val/test structure detected; everything treated as one split named 'all'. "
        "Cross-split leakage checks will be INCONCLUSIVE. Pass `splits:` in dataset-doctor.yaml "
        "if your layout is custom."
    )
    return spec


def _type_from_paths(paths: list[Path], config: Config, spec: DatasetSpec | None = None) -> DatasetType:
    wanted = config.dataset.type
    if wanted is not DatasetType.AUTO:
        return wanted
    table_hits = 0
    image_hits = 0
    for p in paths[:8]:
        if p.is_file():
            if p.suffix.lower() in TABULAR_SUFFIXES:
                table_hits += 1
            elif p.suffix.lower() in IMAGE_SUFFIXES:
                image_hits += 1
            continue
        for f in list(p.rglob("*"))[:400]:
            if not f.is_file() or is_ignored(f.name, config):
                continue
            if f.suffix.lower() in TABULAR_SUFFIXES:
                table_hits += 1
            elif f.suffix.lower() in IMAGE_SUFFIXES:
                image_hits += 1
    if spec is not None:
        spec.inference_notes.append(
            f"Dataset type inferred from content ({'tables' if table_hits >= image_hits else 'images'})"
        )
    return DatasetType.TABULAR if table_hits >= image_hits and table_hits else DatasetType.IMAGE


def _contains_tables(directory: Path, config: Config) -> bool:
    return any(
        f.suffix.lower() in TABULAR_SUFFIXES
        for f in directory.iterdir()
        if f.is_file() and not is_ignored(f.name, config)
    )


def _find_split_column(path: Path) -> str | None:
    try:
        import pandas as pd

        header = pd.read_csv(path, nrows=5) if path.suffix.lower() in {".csv", ".tsv"} else pd.read_parquet(path)
    except Exception:  # pragma: no cover - unreadable file surfaces later
        return None
    for name in ("split", "set", "partition", "fold", "usage"):
        if name in header.columns:
            return str(name)
    return None


def _canonical_split_name(raw: str) -> str:
    key = raw.strip().lower()
    return {
        "training": "train",
        "trn": "train",
        "valid": "val",
        "validation": "val",
        "dev": "val",
        "testing": "test",
        "tst": "test",
        "eval": "test",
        "evaluate": "test",
    }.get(key, key)


def is_ignored(name: str, config: Config) -> bool:
    import fnmatch

    if name.startswith("."):
        return True
    return any(fnmatch.fnmatch(name, pattern) for pattern in config.ignore_patterns())
