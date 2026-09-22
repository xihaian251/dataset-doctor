"""Group-aware, stratified re-splitting - the only way this tool touches data.

Two hard rules, both from the spec's prohibitions: the input is never modified (the
result goes to a *new* directory, and an existing non-empty output is refused rather
than overwritten), and the split is reproducible (seed, strategy, ratios and a
``split-manifest.json`` written next to the output, so a reviewer can re-run it).

Why group-aware: shuffling rows and hoping entities do not collide is exactly what
creates the leakage DD005 reports. Assignment happens at entity level here - every
row sharing a group key lands in one and only one split - and class balance is chased
per stratum. When an entity is too coarse to hit the requested ratio the result is
flagged APPROXIMATE in the manifest rather than quietly rounded, because a split that
is 3% off is fine and a split that *claims* to be exact is not.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from .discovery import IMAGE_SUFFIXES
from .errors import SplitError
from .models import SCHEMA_VERSION, utcnow

TABULAR_SUFFIXES = {".csv", ".tsv", ".parquet", ".pq", ".feather", ".xlsx", ".xls"}
DEFAULT_RATIOS = {"train": 0.8, "val": 0.1, "test": 0.1}
ORDER = ("train", "val", "test")
# How far the written row shares may drift from the request before the result is labelled
# APPROXIMATE. 5 points is below what any user would call a mistake and above the rounding
# noise a single entity can cause on a small pool.
ROW_RATIO_TOLERANCE = 0.05


@dataclass
class SplitRequest:
    source: Path
    output: Path
    ratios: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_RATIOS))
    group_by: str | None = None  # column name (tabular) or path regex (image)
    stratify: str | None = None  # column name (tabular); "label" for images
    seed: int = 42
    dedupe: bool = False


@dataclass
class SplitResult:
    strategy: str
    rows: int
    units: int
    split_sizes: dict[str, int]
    entity_split_sizes: dict[str, int]
    class_counts: dict[str, dict[str, int]]
    duplicates_removed: int
    approximate: bool
    notes: list[str]
    manifest: dict[str, Any]
    output: Path
    written_files: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "rows": self.rows,
            "entities": self.units,
            "split_sizes": self.split_sizes,
            "entity_split_sizes": self.entity_split_sizes,
            "class_counts": self.class_counts,
            "duplicates_removed": self.duplicates_removed,
            "approximate": self.approximate,
            "notes": self.notes,
            "output": str(self.output),
            "written_files": self.written_files,
            "manifest_path": str(self.output / "split-manifest.json"),
        }


# ------------------------------------------------------------------------ entry
def split_dataset(request: SplitRequest) -> SplitResult:
    ratios = _normalise_ratios(request.ratios)
    source = Path(request.source).expanduser().resolve()
    output = Path(request.output).expanduser().resolve()
    if not source.exists():
        raise SplitError(f"source does not exist: {source}")
    _refuse_existing(output)
    if source == output or output in source.parents:
        raise SplitError(f"--output must not contain the input ({output} holds {source})")
    if source.is_file() or _has_tabular(source):
        return _split_tabular(request, source, output, ratios)
    return _split_images(request, source, output, ratios)


def _refuse_existing(output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise SplitError(
            f"refusing to write into a non-empty directory: {output}\n"
            "Nothing in this project overwrites existing data. Choose another --output, "
            "or delete that directory yourself once you have checked what is in it."
        )


def _refuse_empty(sizes: dict[str, int], request: SplitRequest, units: int) -> None:
    """Fail before writing anything if a requested split would come out empty."""
    empty = [name for name, count in sizes.items() if count == 0]
    if not empty:
        return
    reason = (
        f" With --group-by {request.group_by!r} an entity never spans two splits, and {units} "
        "entire entit"
        f"{'y' if units == 1 else 'ies'} could not fill every requested split. Use a finer entity, "
        "change --ratios, or drop --group-by."
        if request.group_by
        else ""
    )
    raise SplitError(
        f"the requested split leaves {', '.join(sorted(empty))} empty, so there would be nothing "
        f"to evaluate on.{reason} Nothing was written."
    )


def _carry_config(source: Path, output: Path, request: SplitRequest, modality: str) -> str | None:
    """Keep the metadata the audit needs together with the data it describes.

    A re-split directory that lost its config turns `patient_id` back into an ordinary
    column, and DD014 then reports the new patients in test as schema drift. Carrying the
    declaration over is what makes `audit <output>` comparable to `audit <source>`.
    """
    for name in ("dataset-doctor.yaml", "dataset-doctor.yml"):
        existing = source / name
        if existing.is_file():
            body = (
                "# Carried over verbatim by `dataset-doctor-audit split`, so an audit of this directory\n"
                "# measures the same declared fields as an audit of its source.\n"
                + existing.read_text(encoding="utf-8")
            )
            (output / name).write_text(body, encoding="utf-8")
            return name
    if modality == "tabular" and not (request.group_by or request.stratify):
        return None  # nothing was known, so there is nothing honest to write
    lines = [
        "# Synthesised by `dataset-doctor-audit split` from the flags this command was given;",
        "# the source directory carried no dataset-doctor.yaml.",
        "dataset:",
        f"  type: {'tabular' if modality == 'tabular' else 'image'}",
    ]
    if modality == "tabular":
        if request.stratify:
            lines += ["labels:", f"  column: {request.stratify}"]
        if request.group_by:
            lines += ["groups:", f"  columns: [{request.group_by}]"]
    else:
        lines += ["labels:", "  source: directory"]
    lines += ["policies: {}"]
    (output / "dataset-doctor.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return "dataset-doctor.yaml"


def _normalise_ratios(ratios: dict[str, float]) -> dict[str, float]:
    cleaned = {str(name).strip().lower(): float(value) for name, value in ratios.items()}
    cleaned = {name: value for name, value in cleaned.items() if value > 0}
    if len(cleaned) < 2:
        raise SplitError("at least two non-zero splits are required for an evaluation to mean anything")
    total = sum(cleaned.values())
    if abs(total - 1.0) > 1e-6:
        cleaned = {name: value / total for name, value in cleaned.items()}
    return dict(sorted(cleaned.items(), key=lambda item: ORDER.index(item[0]) if item[0] in ORDER else len(ORDER)))


def _ratio_deviation(sizes: dict[str, int], ratios: dict[str, float]) -> float:
    """Worst gap, as a share of the written rows, between what was asked and what was cut."""
    total = sum(sizes.values())
    if total <= 0:
        return 0.0
    return max(abs(sizes.get(name, 0) / total - ratio) for name, ratio in ratios.items())


def _has_tabular(source: Path) -> bool:
    return any(f.is_file() and f.suffix.lower() in TABULAR_SUFFIXES for f in sorted(source.rglob("*")))


def _key_text(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "__missing_entity__"
    return str(value).strip() or "__missing_entity__"


def _order_key(seed: int, unit_id: str) -> str:
    return hashlib.sha256(f"{seed}|{unit_id}".encode()).hexdigest()


# ---------------------------------------------------------------------- tabular
def _read_one(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t")
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".feather":
        return pd.read_feather(path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path)
    raise SplitError(f"unsupported input format: {path.suffix} ({path.name})")


def _read_source(source: Path) -> pd.DataFrame:
    if source.is_file():
        return _read_one(source)
    files = sorted(
        f
        for f in source.rglob("*")
        if f.is_file() and f.suffix.lower() in TABULAR_SUFFIXES and not f.name.startswith("split-manifest")
    )
    if not files:
        raise SplitError(f"no tabular file found under {source}")
    frames = [_read_one(f) for f in files]
    return frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)


def _split_tabular(request: SplitRequest, source: Path, output: Path, ratios: dict[str, float]) -> SplitResult:
    frame = _read_source(source).reset_index(drop=True)
    if frame.empty:
        raise SplitError(f"{source} contains no rows")
    notes: list[str] = []
    duplicates_removed = 0
    if request.dedupe:
        before = len(frame)
        frame = frame.drop_duplicates(keep="first").reset_index(drop=True)
        duplicates_removed = before - len(frame)
        if duplicates_removed:
            notes.append(f"Removed {duplicates_removed} exact duplicate row(s), keeping the first occurrence.")

    columns = set(frame.columns)
    if request.group_by and request.group_by not in columns:
        raise SplitError(
            f"--group-by column '{request.group_by}' is not among {sorted(columns)}. Grouping by an "
            "absent column would silently produce an ungrouped split, which is the bug this command exists to fix."
        )
    if request.stratify and request.stratify not in columns:
        raise SplitError(f"--stratify column '{request.stratify}' is not among {sorted(columns)}")

    if request.group_by:
        grouped: dict[str, list[int]] = defaultdict(list)
        for position, value in enumerate(frame[request.group_by].tolist()):
            grouped[_key_text(value)].append(position)
        units = dict(grouped)
    else:
        units = {f"row::{index}": [index] for index in range(len(frame))}
        notes.append("No --group-by: every row is its own entity, so this is a plain row shuffle.")

    strata = _strata(frame, units, request.stratify, notes)
    assignment, deviation = _assign(strata, {k: len(v) for k, v in units.items()}, ratios, request.seed)

    split_of_row = [assignment[units_of_row] for units_of_row in _row_units(units, len(frame))]
    labels = pd.Series(split_of_row, index=frame.index)
    parts = {name: frame[labels == name].reset_index(drop=True) for name in ratios}
    _refuse_empty({name: len(part) for name, part in parts.items()}, request, len(units))
    sizes: dict[str, int] = {}
    class_counts: dict[str, dict[str, int]] = {}
    written: list[str] = []
    output.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower() if source.is_file() else ".csv"
    for name, part in parts.items():
        sizes[name] = len(part)
        class_counts[name] = _class_counts(part, request.stratify)
        target = output / f"{name}{suffix}"
        _write_table(part, target)
        written.append(target.name)

    # An entity-granular cut can match the requested *entity* counts and still be nowhere near
    # the requested *row* shares - one 40-row patient in a 60-row pool does that on its own.
    # Reporting only the entity gap would let such a split claim it was exact.
    row_deviation = _ratio_deviation(sizes, ratios)
    approximate = deviation > 1.0 + 1e-9 or row_deviation > ROW_RATIO_TOLERANCE
    if approximate:
        notes.append(
            f"Entity-level assignment misses the requested ratio: up to {deviation:.1f} entities in the "
            f"worst stratum, and the written shares differ from the request by up to "
            f"{row_deviation * 100:.1f} percentage points. A {max(len(rows) for rows in units.values())}-row "
            "entity cannot be divided across splits, so exact ratios are unreachable here. See "
            "split-manifest.json for the counts."
        )

    carried = _carry_config(source, output, request, "tabular")
    if carried:
        written.append(carried)

    entity_split_sizes = dict(sorted(Counter(assignment.values()).items()))
    strategy = _strategy_name(bool(request.group_by), bool(request.stratify), approximate)
    manifest = _manifest(
        request,
        source,
        output,
        ratios,
        strategy,
        sizes,
        entity_split_sizes,
        class_counts,
        _group_manifest(request),
        notes,
        approximate,
        len(units),
        [output / n for n in written],
        deviation,
        row_deviation,
    )
    _write_manifest(output, manifest)
    return SplitResult(
        strategy=strategy,
        rows=len(frame),
        units=len(units),
        split_sizes=sizes,
        entity_split_sizes=entity_split_sizes,
        class_counts=class_counts,
        duplicates_removed=duplicates_removed,
        approximate=approximate,
        notes=notes,
        manifest=manifest,
        output=output,
        written_files=written,
    )


def _row_units(units: dict[str, list[int]], total: int) -> list[str]:
    mapping = {row: unit_id for unit_id, rows in units.items() for row in rows}
    covered = len(mapping)
    if covered != total:
        raise SplitError(f"internal error: {total - covered} row(s) belong to no entity group")
    return [mapping[index] for index in range(total)]


def _strata(
    frame: pd.DataFrame, units: dict[str, list[int]], stratify: str | None, notes: list[str]
) -> dict[str, list[str]]:
    """Stratum label -> entity ids. An entity takes its majority label."""
    strata: dict[str, list[str]] = defaultdict(list)
    if not stratify:
        strata["__all__"] = list(units)
        return strata
    mixed = 0
    for unit_id, rows in units.items():
        counts = Counter(str(value) for value in frame[stratify].iloc[rows].tolist())
        if len(counts) > 1:
            mixed += 1
        label = counts.most_common(1)[0][0]
        strata[label].append(unit_id)
    if mixed:
        notes.append(
            f"{mixed} entity group(s) carry more than one value of '{stratify}'. The majority value decided "
            "which stratum the whole entity went to - one entity cannot sit in two splits at once."
        )
    return dict(strata)


def _assign(
    strata: dict[str, list[str]], unit_rows: dict[str, int], ratios: dict[str, float], seed: int
) -> tuple[dict[str, str], float]:
    """Greedy largest-relative-deficit assignment per stratum, deterministic for a seed.

    Returns the assignment and the worst stratum deviation from the requested ratio,
    counted in entities - the number that says how far "approximate" actually is.
    """
    assignment: dict[str, str] = {}
    worst = 0.0
    for label, unit_ids in sorted(strata.items()):
        ordered = sorted(unit_ids, key=lambda unit_id: _order_key(seed, f"{label}|{unit_id}"))
        owned: dict[str, int] = dict.fromkeys(ratios, 0)
        owned_rows: dict[str, int] = dict.fromkeys(ratios, 0)
        for unit_id in ordered:
            weight = unit_rows[unit_id]
            # Smallest fill fraction wins; a split with nothing in it yet is the hungriest.
            best = min(ratios, key=lambda name: (owned_rows[name] + weight) / ratios[name])
            assignment[unit_id] = best
            owned[best] += 1
            owned_rows[best] += weight
        worst = max(worst, max(abs(owned[name] - ratios[name] * len(ordered)) for name in ratios))
    return assignment, worst


def _class_counts(part: pd.DataFrame, column: str | None) -> dict[str, int]:
    if not column or column not in part.columns:
        return {}
    counts = Counter(_key_text(value) for value in part[column].tolist())
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _group_manifest(request: SplitRequest) -> dict[str, Any]:
    return {"modality": "tabular", "group_by": request.group_by, "stratify": request.stratify}


def _write_table(part: pd.DataFrame, target: Path) -> None:
    suffix = target.suffix.lower()
    if suffix == ".csv":
        part.to_csv(target, index=False)
    elif suffix == ".tsv":
        part.to_csv(target, sep="\t", index=False)
    elif suffix in {".parquet", ".pq"}:
        part.to_parquet(target, index=False)
    elif suffix == ".feather":
        part.to_feather(target)
    elif suffix in {".xlsx", ".xls"}:
        part.to_excel(target, index=False)
    else:  # pragma: no cover - guarded by _read_one
        raise SplitError(f"cannot write {suffix} output")


# ----------------------------------------------------------------------- images
def split_image_paths(paths: list[str], group_pattern: str | None) -> dict[str, list[str]]:
    """Entity id -> file paths, grouping image paths by a regex applied to each path."""
    matcher: re.Pattern[str] | None = None
    if group_pattern:
        try:
            matcher = re.compile(group_pattern)
        except re.error as exc:
            raise SplitError(f"--group-by is used as a path regex for images and did not compile: {exc}") from exc
    units: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if matcher is not None:
            found = matcher.search(path)
            if found is None:
                raise SplitError(
                    f"--group-by pattern {group_pattern!r} did not match sample path {path!r}. "
                    "An unmatched entity silently joins other entities into one group, which is worse than failing."
                )
            # `found.groups` is a method; the number of capture groups lives on the pattern.
            # A pattern without one groups by the whole match instead of raising IndexError.
            key = found.group(1) if matcher.groups else found.group(0)
            units[str(key)].append(path)
        else:
            units[path].append(path)
    return dict(units)


def image_label(path: str) -> str:
    parts = [p for p in Path(path).parts if p not in ("train", "val", "test")]
    return parts[-2] if len(parts) >= 2 else "__unlabeled__"


def _split_images(request: SplitRequest, source: Path, output: Path, ratios: dict[str, float]) -> SplitResult:
    notes: list[str] = []
    paths = _image_paths(source)
    if not paths:
        raise SplitError(f"{source} contains neither a tabular file nor a supported image")
    units = split_image_paths(paths, request.group_by)
    if not request.group_by:
        notes.append(
            "No --group-by: each file is its own entity. Pass a path regex with one capture group "
            "(e.g. '(?:^|/)(session_[0-9]+)') to keep an entity on one side of the split."
        )
    strata: dict[str, list[str]] = defaultdict(list)
    for unit_id, members in units.items():
        counts = Counter(image_label(member) for member in members)
        strata[counts.most_common(1)[0][0]].append(unit_id)
    assignment, deviation = _assign(strata, {k: len(v) for k, v in units.items()}, ratios, request.seed)

    written: list[str] = []
    sizes: dict[str, int] = dict.fromkeys(ratios, 0)
    counters: dict[str, Counter[str]] = defaultdict(Counter)
    moved: dict[str, list[str]] = defaultdict(list)
    for unit_id, members in sorted(units.items()):
        split_name = assignment[unit_id]
        for relative in members:
            moved[split_name].append(relative)
            sizes[split_name] += 1
            counters[split_name][image_label(relative)] += 1
    _refuse_empty(sizes, request, len(units))
    row_deviation = _ratio_deviation(sizes, ratios)
    approximate = deviation > 1.0 + 1e-9 or row_deviation > ROW_RATIO_TOLERANCE
    if approximate:
        notes.append(
            f"Entity-level assignment misses the requested ratio: up to {deviation:.1f} entities in the "
            f"worst stratum, and the written shares differ from the request by up to "
            f"{row_deviation * 100:.1f} percentage points; an entity's images stay together by design."
        )
    output.mkdir(parents=True, exist_ok=True)
    for split_name, members in sorted(moved.items()):
        for relative in members:
            target = output / split_name / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
            written.append(target.relative_to(output).as_posix())

    class_counts = {
        name: dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))
        for name, counter in sorted(counters.items())
    }
    entity_split_sizes = dict(sorted(Counter(assignment.values()).items()))
    strategy = _strategy_name(bool(request.group_by), True, approximate)
    manifest = _manifest(
        request,
        source,
        output,
        ratios,
        strategy,
        sizes,
        entity_split_sizes,
        class_counts,
        {"modality": "image", "group_by": request.group_by, "stratify": "label(directory)"},
        notes,
        approximate,
        len(units),
        [output / name for name in ratios],
        deviation,
        row_deviation,
    )
    manifest["assignments"] = {name: sorted(moved.get(name, [])) for name in ratios}
    _write_manifest(output, manifest)
    carried = _carry_config(source, output, request, "image")
    if carried:
        written.append(carried)
    return SplitResult(
        strategy=strategy,
        rows=len(paths),
        units=len(units),
        split_sizes=sizes,
        entity_split_sizes=entity_split_sizes,
        class_counts=class_counts,
        duplicates_removed=0,
        approximate=approximate,
        notes=notes,
        manifest=manifest,
        output=output,
        written_files=written,
    )


def _image_paths(source: Path) -> list[str]:
    """Relative POSIX paths of every decodable image, skipping dot-dirs and caches."""
    out: list[str] = []
    for candidate in sorted(source.rglob("*")):
        if not candidate.is_file():
            continue
        relative = candidate.relative_to(source)
        if any(part.startswith(".") or part == "__pycache__" for part in relative.parts[:-1]):
            continue
        if candidate.suffix.lower() in IMAGE_SUFFIXES:
            out.append(relative.as_posix())
    return out


# --------------------------------------------------------------------- manifest
def _manifest(
    request: SplitRequest,
    source: Path,
    output: Path,
    ratios: dict[str, float],
    strategy: str,
    sizes: dict[str, int],
    entity_sizes: dict[str, int],
    class_counts: dict[str, Any],
    keys: dict[str, Any],
    notes: list[str],
    approximate: bool,
    units: int,
    targets: list[Path],
    deviation: float,
    row_deviation: float,
) -> dict[str, Any]:
    """The artifact that makes this split reproducible and reviewable."""
    from . import __version__

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "dataset-doctor-audit", "version": __version__, "command": "split"},
        "created_at": utcnow().isoformat(),
        "source": str(source),
        "output": str(output),
        "seed": request.seed,
        "ratios": {name: round(value, 6) for name, value in ratios.items()},
        "strategy": strategy,
        "approximate": approximate,
        "ratio_deviation_entities": round(deviation, 3),
        "ratio_deviation_rows": round(row_deviation, 4),
        "entities": units,
        "split_sizes": sizes,
        "entity_split_sizes": entity_sizes,
        "class_counts": class_counts,
        "keys": keys,
        "dedupe": request.dedupe,
        "notes": notes,
        "files": [
            {
                "path": target.name if target.is_file() else target.relative_to(output).as_posix(),
                "sha256": _sha256(target) if target.is_file() else None,
                "kind": "file" if target.is_file() else "directory",
            }
            for target in targets
        ],
        "reproduce": "dataset-doctor-audit split " + f"{source}{_echo_flags(request)} --output <a new directory>",
    }
    return payload


def _write_manifest(output: Path, manifest: dict[str, Any]) -> Path:
    path = output / "split-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _echo_flags(request: SplitRequest) -> str:
    flags = [f"--ratios {','.join(f'{k}={v}' for k, v in request.ratios.items())}", f"--seed {request.seed}"]
    if request.group_by:
        flags.append(f"--group-by {request.group_by}")
    if request.stratify:
        flags.append(f"--stratify {request.stratify}")
    if request.dedupe:
        flags.append("--dedupe")
    return " " + " ".join(flags)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _strategy_name(grouped: bool, stratified: bool, approximate: bool) -> str:
    base = "+".join(
        part
        for part in [
            "grouped" if grouped else "row-wise",
            "stratified" if stratified else "unstratified",
        ]
        if part
    )
    return f"{base} (APPROXIMATE)" if approximate else base
