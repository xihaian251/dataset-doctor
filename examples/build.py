#!/usr/bin/env python3
"""Generate the example datasets under ``examples/`` and, with ``--audit``, measure them.

Every fixture isolates one fault so a reader can tie a finding back to exactly one cause;
the two mixed fixtures at the end follow the master spec's numbered examples. The builders
reuse ``dataset_doctor_audit.demo`` primitives on purpose - the shape of a record is the same
across the whole repository, so a number in a report means the same thing everywhere.

    python examples/build.py            # write the fixtures
    python examples/build.py --audit    # write them, then record what the tool actually said

``--audit`` regenerates ``RESULTS.md`` from a live run. Nothing in this repository quotes a
verdict that was not produced by running the audit on these exact bytes.
"""

from __future__ import annotations

import argparse
import csv
import random
import shutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataset_doctor_audit.demo import (
    DEMO_SEED,
    TABULAR_COLUMNS,
    _image_config,
    _pattern,
    _rows,
    _tabular_config,
    _write_table,
)

EXAMPLES = Path(__file__).resolve().parent

# The patient namespaces are disjoint per fixture (p/d/g/l/h/s prefixes) so that the only
# entity overlap on either side of a split is the one a builder planted deliberately.


def _table(
    root: Path,
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    note: str,
    val: list[dict[str, Any]] | None = None,
    config: str | None = None,
) -> str:
    """Write one tabular fixture: disjoint split files, declared label and entity column."""
    root.mkdir(parents=True, exist_ok=True)
    _write_table(root / "train.csv", train)
    _write_table(root / "test.csv", test)
    if val is not None:
        _write_table(root / "val.csv", val)
    (root / "dataset-doctor.yaml").write_text(config or _tabular_config(), encoding="utf-8")
    _write_note(root, note)
    return f"{len(train)} train / {len(test)} test rows"


def _write_note(root: Path, body: str) -> None:
    (root / "PLANTED_FAULTS.md").write_text(
        f"# {root.name}\n\n{body.strip()}\n\nRegenerate: `python examples/build.py`\n",
        encoding="utf-8",
    )


def _image_note(root: Path, body: str) -> None:
    _write_note(root, body)


def _copy_images(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


# ------------------------------------------------------------------ tabular, one fault each
def safe_tabular(root: Path) -> str:
    """The control: nothing planted, so anything this fixture reports is a false positive."""
    train = _rows(DEMO_SEED + 11, patients=60, per_patient=3, leaked=False, prefix="s")
    test = _rows(DEMO_SEED + 12, patients=20, per_patient=3, leaked=False, prefix="e")
    return _table(
        root,
        train,
        test,
        "No fault is planted here. This is the control fixture: every finding it produces "
        "is a false positive, and the CI gate fails if a critical or blocking one appears.",
    )


def unsafe_duplicate(root: Path) -> str:
    """Exact cross-split duplicates: the same rows scored on both sides of the boundary."""
    train = _rows(DEMO_SEED + 21, patients=40, per_patient=5, leaked=False, prefix="p")
    test = _rows(DEMO_SEED + 22, patients=12, per_patient=5, leaked=False, prefix="q")
    test.extend(dict(row) for row in train[:5])
    random.Random(DEMO_SEED + 23).shuffle(test)
    return _table(
        root,
        train,
        test,
        "Planted: 5 train rows copied into `test.csv` verbatim, `record_id` included, so the "
        "two files share byte-identical records. No post-outcome column and no other entity "
        "is shared. Note that DD005 fires here too: a verbatim copy always carries its "
        "`patient_id` across the boundary with it, so an exact duplicate is unavoidably also "
        "an entity overlap. The two findings describe one fault seen from two sides, and "
        "DD003's evidence is the sharper of the pair.",
    )


def unsafe_group_leakage(root: Path) -> str:
    """Entity leakage: the same patients appear in train and test under fresh record ids."""
    train = _rows(DEMO_SEED + 31, patients=40, per_patient=5, leaked=False, prefix="p")
    test = _rows(DEMO_SEED + 32, patients=12, per_patient=5, leaked=False, prefix="q")
    stolen = [row for row in train if row["patient_id"] in {f"p{i:03d}" for i in range(4)}]
    test.extend({**row, "record_id": "x" + row["record_id"]} for row in stolen[::2])
    return _table(
        root,
        train,
        test,
        "Planted: patients p000-p003 re-booked into test under new `record_id`s (every other "
        "row, 10 rows total). No row is an exact duplicate, so a dedup script would miss this "
        "completely - only the entity column makes it visible.",
    )


def unsafe_label_conflict(root: Path) -> str:
    """The same features, opposite labels: the ground truth itself disagrees."""
    train = _rows(DEMO_SEED + 41, patients=40, per_patient=5, leaked=False, prefix="p")
    test = _rows(DEMO_SEED + 42, patients=12, per_patient=5, leaked=False, prefix="q")
    for row in train[:4]:
        twin = {key: value for key, value in row.items() if key != "target"}
        test.append({**twin, "record_id": "c" + row["record_id"], "target": 1 - row["target"]})
    return _table(
        root,
        train,
        test,
        "Planted: 4 train records replicated in test with identical feature values, a new "
        "`record_id` and the label flipped. The features cannot separate these rows, so the "
        "label is the only thing that differs - a rate-noise or annotation-pipeline problem "
        "that lands inside the evaluation split. DD005 comes along for the same reason it "
        "does in `unsafe_duplicate`: the replicas keep their `patient_id`, so the entity "
        "crosses the boundary too.",
    )


def unsafe_target_leakage(root: Path) -> str:
    """A feature that is a deterministic function of the label, and nothing else."""
    train = _rows(DEMO_SEED + 51, patients=40, per_patient=5, leaked=True, prefix="p")
    test = _rows(DEMO_SEED + 52, patients=12, per_patient=5, leaked=True, prefix="q")
    return _table(
        root,
        train,
        test,
        "Planted: `discharge_code` is written as `DC-{target+1:02d}` after the outcome is "
        "known, and `visit_lactate` is drawn from the label. No duplicated rows and no shared "
        "patients - the data is perfectly split and perfectly useless, which is the point. "
        "The first column is a deterministic relabeling (a verdict); the second only predicts "
        "well (a candidate a real biomarker would also produce).",
    )


def shifted_tabular(root: Path) -> str:
    """Distribution shift without leakage: the eval set describes a different population."""
    train = _rows(DEMO_SEED + 61, patients=40, per_patient=5, leaked=False, prefix="p")
    rng = np.random.default_rng(DEMO_SEED + 62)
    test: list[dict[str, Any]] = []
    for index in range(60):
        target = int(rng.random() < 0.75)
        test.append(
            {
                "record_id": f"q{index:05d}",
                "patient_id": f"q{index // 3:03d}",
                "age": int(np.clip(rng.normal(70, 11), 18, 95)),
                "sex": "M" if rng.random() < 0.7 else "F",
                "bmi": round(float(np.clip(rng.normal(31, 4), 15, 48)), 1),
                "visit_lactate": round(float(rng.normal(2.4, 0.6)), 2),
                "discharge_code": f"DC-{int(rng.random() * 2) + 1:02d}",
                "target": target,
            }
        )
    return _table(
        root,
        train,
        test,
        "Planted: the test split is an older, heavier, mostly male population with a 75% "
        "positive rate, built from disjoint patients. No row or entity crosses the boundary - "
        "the model can be trained honestly and still measured on people it was not meant for. "
        "Shift is a data quality fact, not leakage, and must never be reported as one.",
    )


def leaky_patient_dataset(root: Path) -> str:
    """The spec's mixed clinical fixture: three leakage faults plus a temporal inversion."""
    train = _rows(DEMO_SEED + 71, patients=40, per_patient=5, leaked=True, prefix="p")
    test = _rows(DEMO_SEED + 72, patients=12, per_patient=5, leaked=True, prefix="q")
    val = _rows(DEMO_SEED + 73, patients=6, per_patient=5, leaked=True, prefix="v")
    shared = [row for row in train if row["patient_id"] in {f"p{i:03d}" for i in range(6)}]
    test.extend({**row, "record_id": "x" + row["record_id"]} for row in shared[::2])
    test.extend(dict(row) for row in train[:4])
    random.Random(DEMO_SEED + 74).shuffle(test)
    description = _table(
        root,
        train,
        test,
        "Planted together: 6 train patients re-booked into test, 4 verbatim row copies, "
        "`discharge_code` as a deterministic relabeling of the label, `visit_lactate` drawn "
        "from the label, a test split enriched with the positive class, and a collection "
        "window where train (2026) is *later* than test (2024) - a backtest that predicts the "
        "past. The control for this fixture is `safe_tabular`.",
        val=val,
    )
    _stamp_dates(root)
    return description


def _stamp_dates(root: Path) -> None:
    """Add a temporal column where train is *later* than test, then declare it.

    A single-file layout with a `split` column keeps the dates and the split in the same
    table, so DD006 can compare them directly instead of inferring a boundary from file names.
    """
    columns = [*TABULAR_COLUMNS[:-1], "collected_at", "split", TABULAR_COLUMNS[-1]]
    rows: list[dict[str, Any]] = []
    for name, year in (("train", 2026), ("val", 2025), ("test", 2024)):
        source = Path(root) / f"{name}.csv"
        with open(source, encoding="utf-8", newline="") as handle:
            for index, line in enumerate(csv.DictReader(handle)):
                line["split"] = name
                # Train was collected in 2026, test in 2024: the future predicts the past.
                line["collected_at"] = f"{year}-{index % 12 + 1:02d}-{index % 27 + 1:02d}"
                rows.append({key: line[key] for key in columns})
    with open(root / "cohort.csv", "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    for name in ("train", "val", "test"):
        (root / f"{name}.csv").unlink()
    (root / "dataset-doctor.yaml").write_text(
        """# Generated by examples/build.py.
dataset:
  type: tabular
labels:
  column: target
groups:
  columns: [patient_id]
id_columns: [record_id]
# One table holds every split, so both the split membership and the timestamp it was
# collected at have to be declared as columns.
temporal:
  column: collected_at
  split_column: split
policies: {}
""",
        encoding="utf-8",
    )


# ----------------------------------------------------------------------- image fixtures
def _image_set(
    root: Path,
    train: dict[str, int],
    test: dict[str, int],
    note: str,
    seed_base: int,
) -> int:
    """Write disjoint, structurally distinct images per class and return the file count."""
    root.mkdir(parents=True, exist_ok=True)
    made = 0
    for split_index, (split, counts) in enumerate((("train", train), ("test", test))):
        for class_index, (label, count) in enumerate(sorted(counts.items())):
            directory = root / split / label
            directory.mkdir(parents=True, exist_ok=True)
            for index in range(count):
                seed = seed_base + split_index * 1000 + class_index * 100 + index
                _pattern(seed).save(directory / f"{split}_{label}_{index:03d}.png")
                made += 1
    (root / "dataset-doctor.yaml").write_text(_image_config(), encoding="utf-8")
    _image_note(root, note)
    return made


def safe_image(root: Path) -> str:
    made = _image_set(
        root,
        {"scratch": 20, "bruise": 16, "dent": 12},
        {"scratch": 6, "bruise": 5, "dent": 4},
        "No fault is planted. Seeds are unique per image, so nothing here is a duplicate or a "
        "near-duplicate by construction; anything DD003/DD004 reports would be a false "
        "positive of the perceptual hash.",
        110_000,
    )
    return f"{made} images"


def unsafe_image_duplicate(root: Path) -> str:
    made = _image_set(
        root,
        {"scratch": 20, "bruise": 16},
        {"scratch": 6, "bruise": 5},
        "Planted: 4 train images copied byte-for-byte into `test/`. Same pixels, same sha256, "
        "different file name - the class of leakage a checksum-based dedup does catch, "
        "isolated from everything else.",
        111_000,
    )
    source_dir = root / "train" / "scratch"
    target_dir = root / "test" / "scratch"
    for index in range(4):
        _copy_images(source_dir / f"train_scratch_{index:03d}.png", target_dir / f"leaked_{index:02d}.png")
    return f"{made + 4} images"


def unsafe_near_duplicate(root: Path) -> str:
    made = _image_set(
        root,
        {"scratch": 20, "bruise": 16},
        {"scratch": 6, "bruise": 5},
        "Planted: 3 pairs that straddle the split boundary after a brightness change "
        "(1.06x + 4). The pixels differ, so no sha256 matches; only a perceptual hash sees "
        "them. This is the fault an exact-duplicate check is blind to.",
        112_000,
    )
    for index in range(3):
        source = _pattern(112_500 + index)
        source.save(root / "train" / "scratch" / f"near_{index:02d}.png")
        source.point(lambda value: min(255, int(value * 1.06) + 4)).save(
            root / "test" / "scratch" / f"near_{index:02d}_test.png"
        )
    return f"{made + 6} images"


def unsafe_image_label_conflict(root: Path) -> str:
    made = _image_set(
        root,
        {"scratch": 18, "bruise": 14, "dent": 10},
        {"scratch": 6, "bruise": 5},
        "Planted: one image saved under three different class folders - two in train, one in "
        "test. Identical content, three labels, so the label space rather than the split "
        "boundary is what is broken. DD003 reports the same files as an exact cross-split "
        "duplicate: with one copy inside test, both readings are true.",
        113_000,
    )
    conflict = _pattern(113_900)
    for directory in ("train/bruise", "train/dent", "test/scratch"):
        conflict.save(root / directory / "conflict.png")
    return f"{made + 3} images"


def corrupt_image(root: Path) -> str:
    made = _image_set(
        root,
        {"scratch": 16, "bruise": 12},
        {"scratch": 6},
        "Planted: a truncated JPEG and a zero-byte PNG. Neither is leakage; both silently "
        "shrink a pipeline that skips unloadable files, so the coverage number is the "
        "finding.",
        114_000,
    )
    temporary = root / "train" / "scratch" / "_seed.jpg"
    _pattern(114_500).save(temporary, format="JPEG")
    payload = temporary.read_bytes()
    (root / "train" / "scratch" / "truncated.jpg").write_bytes(payload[: max(20, len(payload) // 3)])
    temporary.unlink()
    (root / "train" / "scratch" / "empty.png").write_bytes(b"")
    return f"{made + 2} images"


def leaky_image_dataset(root: Path) -> str:
    """The spec's numbered image demo: 100 images carrying five separate faults.

    The counts are the spec's, read the way the tool counts them: ten samples caught in
    exact duplicates is five copied images, six near-duplicate samples is three pairs.
    """
    made = _image_set(
        root,
        {"scratch": 28, "bruise": 20, "dent": 14, "crack": 8},
        {"scratch": 8, "bruise": 6},
        "Planted, at the spec's sizes: 10 exact duplicates (5 train images copied into "
        "test), 6 near-duplicate samples (3 pairs across the boundary), a 3-way label "
        "conflict (one image under three class folders), 1 truncated JPEG and 1 zero-byte "
        "PNG, plus a 28:8:14:8 class distribution. Nothing else is planted.",
        115_000,
    )
    for index in range(5):
        _copy_images(
            root / "train" / "scratch" / f"train_scratch_{index:03d}.png",
            root / "test" / "scratch" / f"dup_{index:02d}.png",
        )
        made += 1
    for index in range(3):
        source = _pattern(116_000 + index)
        source.save(root / "train" / "bruise" / f"near_{index:02d}.png")
        source.point(lambda value: min(255, int(value * 1.06) + 4)).save(
            root / "test" / "bruise" / f"near_{index:02d}_test.png"
        )
        made += 2
    conflict = _pattern(116_900)
    for directory in ("train/dent", "train/crack", "test/bruise"):
        (root / directory).mkdir(parents=True, exist_ok=True)
        conflict.save(root / directory / "conflict.png")
        made += 1
    temporary = root / "train" / "crack" / "_seed.jpg"
    _pattern(117_000).save(temporary, format="JPEG")
    payload = temporary.read_bytes()
    (root / "train" / "crack" / "truncated.jpg").write_bytes(payload[: max(20, len(payload) // 3)])
    temporary.unlink()
    (root / "train" / "crack" / "empty.png").write_bytes(b"")
    made += 2
    counted = _count_images(root)
    assert counted == made == 100, f"the spec's fixture is 100 images, this built {counted}"
    return f"{counted} images"


def _count_images(root: Path) -> int:
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".png", ".jpg"})


# --------------------------------------------------------------------------- the registry
FIXTURES: dict[str, Callable[[Path], str]] = {
    "safe_tabular": safe_tabular,
    "unsafe_duplicate": unsafe_duplicate,
    "unsafe_group_leakage": unsafe_group_leakage,
    "unsafe_label_conflict": unsafe_label_conflict,
    "unsafe_target_leakage": unsafe_target_leakage,
    "shifted_tabular": shifted_tabular,
    "leaky_patient_dataset": leaky_patient_dataset,
    "safe_image": safe_image,
    "unsafe_image_duplicate": unsafe_image_duplicate,
    "unsafe_near_duplicate": unsafe_near_duplicate,
    "unsafe_image_label_conflict": unsafe_image_label_conflict,
    "corrupt_image": corrupt_image,
    "leaky_image_dataset": leaky_image_dataset,
}


def build_all(destination: Path, only: str | None = None) -> dict[str, str]:
    built: dict[str, str] = {}
    for name, builder in FIXTURES.items():
        if only and name != only:
            continue
        target = destination / name
        if target.exists():
            shutil.rmtree(target)
        built[name] = builder(target)
    return built


def record(destination: Path) -> str:
    """Audit every fixture and render the observed verdicts. Numbers here are measured."""
    from dataset_doctor_audit import audit_dataset

    lines = [
        "# What the tool actually said about these fixtures",
        "",
        "Generated by `python examples/build.py --audit`. This file is the output of a real run;",
        "no row was written by hand. It is checked in so a reader can compare a verdict with the",
        "fault that was planted without running anything.",
        "",
        "| fixture | planted | verdict | samples | findings |",
        "| --- | --- | --- | --- | --- |",
    ]
    details: list[str] = []
    for name in FIXTURES:
        result = audit_dataset(destination / name)
        counts: dict[str, int] = {}
        for finding in result.report.findings:
            counts[finding.severity.value] = counts.get(finding.severity.value, 0) + 1
        summary = ", ".join(
            f"{counts[key]} {key.lower()}" for key in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO") if counts.get(key)
        )
        lines.append(
            f"| `{name}` | {_PLANTED[name]} | `{result.report.eval_safety.value}` "
            f"| {result.identity.num_samples} | {summary} |"
        )
        rules = [
            finding for finding in result.report.findings if finding.severity.value in {"CRITICAL", "HIGH", "MEDIUM"}
        ]
        for finding in rules:
            subject = finding.title.split(":", 1)[-1].strip()
            details.append(
                f"- `{name}` {finding.finding_id} **{finding.severity.value}** "
                f"{finding.status.value} ({finding.formal_impact.value}) - {subject}"
            )
    if details:
        lines.extend(["", "## Every CRITICAL, HIGH and MEDIUM finding", ""])
        lines.extend(details)
    return "\n".join(lines) + "\n"


_PLANTED = {
    "safe_tabular": "nothing (control)",
    "unsafe_duplicate": "exact cross-split duplicate rows",
    "unsafe_group_leakage": "shared patients across splits",
    "unsafe_label_conflict": "identical features, opposite labels",
    "unsafe_target_leakage": "feature derived from the label",
    "shifted_tabular": "covariate + label shift, no leakage",
    "leaky_patient_dataset": "entity, exact duplicate and target leakage together, plus a temporal inversion",
    "safe_image": "nothing (control)",
    "unsafe_image_duplicate": "byte-identical images inside test",
    "unsafe_near_duplicate": "perceptually identical images across the boundary",
    "unsafe_image_label_conflict": "one image, three classes",
    "corrupt_image": "a truncated JPEG and a zero-byte PNG",
    "leaky_image_dataset": "10 exact / 6 near duplicates, 3-way label conflict, 2 corrupt files, imbalance",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output", type=Path, default=EXAMPLES, help="where the fixtures go")
    parser.add_argument("--only", choices=sorted(FIXTURES), help="build one fixture (debugging)")
    parser.add_argument("--audit", action="store_true", help="also run the audit and write RESULTS.md")
    args = parser.parse_args()

    built = build_all(args.output, only=args.only)
    for name, description in built.items():
        print(f"{name:32s} {description}")
    if args.audit:
        text = record(args.output)
        (args.output / "RESULTS.md").write_text(text, encoding="utf-8")
        print(f"\nwrote {args.output / 'RESULTS.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
