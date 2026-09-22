"""Deterministic demo datasets with deliberately planted, documented problems.

Three fixtures, because one dataset that is merely broken proves nothing:

* ``leaky_tabular``  - entity leakage, exact cross-split duplicates, a post-outcome column
* ``leaky_images``   - duplicate images, near-duplicates, conflicting labels, corrupt files
* ``clean_tabular``  - built to produce no CRITICAL finding. The false-positive control:
  a tool that screams at everything is not detecting leakage, it is detecting data.

Everything is generated from a fixed seed, so a demo run, a documentation screenshot
and a regression test all see the same bytes. No third-party data is bundled, which
keeps the license story as simple as the code.
"""

from __future__ import annotations

import csv
import random
import shutil
from pathlib import Path
from typing import Any

import numpy as np

DEMO_SEED = 20260920
TABULAR_COLUMNS = [
    "record_id",
    "patient_id",
    "age",
    "sex",
    "bmi",
    "visit_lactate",
    "discharge_code",
    "target",
]


def build_demo(root: Path | str, images: bool = True, overwrite: bool = False) -> dict[str, str]:
    """Create the fixtures under ``root`` and describe which planted fault each holds."""
    destination = Path(root)
    if destination.exists() and overwrite:
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    built: dict[str, str] = {}
    built["leaky_tabular"] = build_leaky_tabular(destination / "leaky_tabular")
    built["clean_tabular"] = build_clean_tabular(destination / "clean_tabular")
    if images:
        try:
            built["leaky_images"] = build_leaky_images(destination / "leaky_images")
        except ImportError:  # pragma: no cover - Pillow is a hard dependency, this is belt and braces
            built["leaky_images"] = "skipped: Pillow is not installed"
    return built


# ----------------------------------------------------------------------- tabular
def _rows(seed: int, patients: int, per_patient: int, leaked: bool, prefix: str = "p") -> list[dict[str, Any]]:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for index in range(patients * per_patient):
        patient = f"{prefix}{index // per_patient:03d}"
        target = int(rng.random() < 0.42)
        age = int(np.clip(rng.normal(58 if target else 52, 12), 18, 95))
        rows.append(
            {
                "record_id": f"{prefix}r{index:05d}",
                "patient_id": patient,
                "age": age,
                "sex": "M" if rng.random() < 0.5 else "F",
                "bmi": round(float(np.clip(rng.normal(26 + target, 4), 14, 48)), 1),
                # A post-outcome measurement: only drawn once the team already knows the answer.
                "visit_lactate": round(4.1 + 4.6 * target + float(rng.normal(0, 0.35)), 2)
                if leaked
                else round(float(rng.normal(2.4, 0.6)), 2),
                # Deterministic: the ward writes this code *after* the outcome is known.
                "discharge_code": f"DC-{target + 1:02d}" if leaked else f"DC-{int(rng.random() * 2) + 1:02d}",
                "target": target,
            }
        )
    return rows


def _write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=TABULAR_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def build_leaky_tabular(root: Path) -> str:
    """Three faults that leak, two that only skew, one that is just missing.

    Namespace discipline is the load-bearing part: train patients are p0xx, test q0xx and
    val v0xx, so the only entity overlap between splits is the one planted below. Reusing
    one id namespace across splits would leak by accident and make the counts in
    PLANTED_FAULTS.md fiction.
    """
    root.mkdir(parents=True, exist_ok=True)
    train = _rows(DEMO_SEED, patients=40, per_patient=5, leaked=True, prefix="p")
    test = _rows(DEMO_SEED + 1, patients=12, per_patient=5, leaked=True, prefix="q")
    val = _rows(DEMO_SEED + 2, patients=6, per_patient=5, leaked=True, prefix="v")
    # 1. entity leakage: 8 train patients re-booked into the test split under new record ids
    shared = [row for row in train if row["patient_id"] in {f"p{i:03d}" for i in range(8)}]
    for row in shared[::2][:20]:  # every other row, so all 8 patients land on both sides
        test.append({**row, "record_id": "x" + row["record_id"]})
    # 2. exact cross-split duplicates: 6 train rows copied verbatim, id and all
    test.extend(dict(row) for row in train[:6])
    random.Random(DEMO_SEED + 3).shuffle(test)
    _write_table(root / "train.csv", train)
    _write_table(root / "test.csv", test)
    _write_table(root / "val.csv", val)
    (root / "dataset-doctor.yaml").write_text(_tabular_config(), encoding="utf-8")
    (root / "PLANTED_FAULTS.md").write_text(_leaky_tabular_note(), encoding="utf-8")
    return "entity leakage, exact cross-split duplicates, post-outcome columns, imbalance, shift"


def _tabular_config() -> str:
    return """# Generated by `dataset-doctor demo`. Declaring these fields is what lets the
# entity and temporal rules measure anything at all.
dataset:
  type: tabular
labels:
  column: target
groups:
  columns: [patient_id]
id_columns: [record_id]
policies: {}
"""


def _leaky_tabular_note() -> str:
    return """# leaky_tabular - planted faults

316 rows: 200 train (patients p0xx), 86 test (q0xx plus the planted rows), 30 val (v0xx).
Every row of this table was read back out of an actual `dataset-doctor audit` run, so the
counts are what the tool said, not what the generator hoped for.

| # | Fault | Where | Observed |
| --- | --- | --- | --- |
| 1 | 8 train patients re-booked into test under new record ids (20 rows) | `patient_id` | DD005-0001 CRITICAL, 8 entities / 66 samples |
| 2 | 6 train rows copied verbatim into test, id and all | train.csv / test.csv | DD003-0001 CRITICAL, 6 groups / 12 samples |
| 3 | `discharge_code` = `DC-{target+1:02d}`, written after the outcome is known | all splits | DD007-0002 CRITICAL: deterministic relabeling, 1:1 over 2 value pairs, 316 rows |
| 4 | `visit_lactate` drawn *from* the label (4.1 + 4.6 * target, noise sd 0.35) | all splits | DD007-0001 MEDIUM candidate: AUC and MI are high, but a genuine biomarker looks identical in data, so the tool declines to call it a verdict |
| 5 | test oversamples the positive class, because the copied rows came from it | labels | DD013-0001 LOW - total variation 0.107, JS distance 0.076 |
| 6 | ~42% positive rate, 5 repeats per patient | labels | DD011 PASS - imbalance this mild is a fact, not a fault |
| 7 | no provenance block in `dataset-doctor.yaml` | config | DD020 LOW |
| 8 | no `temporal.column` declared, and no images here | config / modality | DD006 NOT_RUN, DD004 UNSUPPORTED. A rule that could not run is reported as such - it is never a PASS |

Two findings are **not** planted, and the fixture is honest about that. The copied rows carry
the label-correlated columns with them, so `visit_lactate` (SMD 0.228) and `discharge_code`
(TV 0.107) also show up under DD012-0001 next to `bmi` (SMD 0.201) - a leak usually reports
twice, once as leakage and once as shift. And DD012-0002 compares train with a 30-row val split,
where the tool put `bmi` at SMD 0.336 and `sex` at TV 0.105 above the cutoff: at that size the
PSI null floor is (10-1)/30 = 0.30, so PSI is reported with `psi_trigger_usable: false` and the
standardised mean difference carries the verdict alone. Both stay LOW - an effect this small in
a split this short is a fact worth knowing, not a verdict. The eight rows above are the
deterministic ones.

Deliberately *not* flagged, and that is part of the fixture: `record_id` is unique per row
but declared under `id_columns`, so DD008 stays quiet (a declared key is identity, not
signal) and DD014 skips it too - unseen `record_id` values in test are expected, and
reporting them would bury the category drift people came to look at.

Each planted fault has a fixed position and a fixed count, so a regression test can assert on
exact numbers; the two DD012 rows above are the measured output of the same seeded generator,
and they are labelled as emergent rather than designed. The paired control fixture is
`clean_tabular`.
"""


def build_clean_tabular(root: Path) -> str:
    """Same shape, no leakage: the fixture that must come back quiet."""
    root.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(DEMO_SEED + 7)
    train: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for index in range(300):
        patient = f"c{index // 3:04d}"
        bucket = train if index < 240 else test
        target = int(rng.random() < 0.5)
        age = int(np.clip(rng.normal(55, 11), 20, 92))
        bucket.append(
            {
                "record_id": f"c{index:05d}",
                "patient_id": patient,
                "age": age,
                "sex": "M" if rng.random() < 0.5 else "F",
                "bmi": round(float(np.clip(rng.normal(26, 4), 15, 45)), 1),
                "visit_lactate": round(float(rng.normal(2.4, 0.6)), 2),
                "discharge_code": f"DC-{int(rng.random() * 2) + 1:02d}",
                "target": target,
            }
        )
    _write_table(root / "train.csv", train)
    _write_table(root / "test.csv", test)
    (root / "dataset-doctor.yaml").write_text(_tabular_config(), encoding="utf-8")
    (root / "PLANTED_FAULTS.md").write_text(
        "# clean_tabular - no planted faults\n\n"
        "Disjoint patients, no duplicated rows, `visit_lactate` and `discharge_code` independent of the "
        "label, balanced classes, both splits from the same generator. This fixture exists to catch a "
        "tool that reports CRITICAL findings just because a dataset has data in it.\n\n"
        "Expected: **zero CRITICAL and zero HIGH findings**. What an actual run reports is DD001 INFO, "
        "DD020 LOW (no provenance block) and DD012 LOW: `visit_lactate` sits at |SMD| 0.247 between a "
        "240-row train and a 60-row test split drawn from the *same* distribution, which is about 1.7 "
        "standard errors of pure sampling noise. Reporting it at LOW rather than MEDIUM is deliberate - "
        "an effect this small in a split this short is a fact worth knowing, not a verdict, and the "
        "severity ladder exists so that distinction survives into the report.\n",
        encoding="utf-8",
    )
    return "control fixture: expected to produce no critical findings"


# ------------------------------------------------------------------------ images
def build_leaky_images(root: Path) -> str:
    """Image-folder fixture: ~140 images carrying the five classic image faults.

    Every image gets its own structural seed, so a near-duplicate finding means the
    generator planted one - not that the fixture happens to look like noise to pHash.
    """
    root.mkdir(parents=True, exist_ok=True)
    made = 0
    classes = {"scratch": 40, "bruise": 30, "dent": 18, "crack": 8}
    for class_index, (label, count) in enumerate(sorted(classes.items())):
        directory = root / "train" / label
        directory.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            _pattern(1000 + class_index * 100 + index).save(directory / f"train_{label}_{index:03d}.png")
            made += 1
    test_dir = root / "test"
    for class_index, (label, count) in enumerate(sorted({"scratch": 10, "bruise": 8, "dent": 5}.items())):
        (test_dir / label).mkdir(parents=True, exist_ok=True)
        for index in range(count):
            seed = 5000 + class_index * 100 + index
            _pattern(seed).save(test_dir / label / f"test_{label}_{index:03d}.png")
            made += 1

    # 1. exact duplicate across splits: the same bytes on both sides
    source = next((root / "train" / "scratch").glob("train_scratch_00*.png"))
    (test_dir / "scratch").mkdir(parents=True, exist_ok=True)
    for offset in range(4):
        shutil.copy2(source, test_dir / "scratch" / f"dup_{offset:02d}.png")
    # 2. near-duplicates inside train: same structure, brightness nudged
    train_scratch = root / "train" / "scratch"
    for offset in range(6):
        seed = 7000 + offset
        _pattern(seed).save(train_scratch / f"near_{offset:02d}.png")
        _pattern(seed).point(lambda value: min(255, int(value * 1.03) + 2)).save(
            train_scratch / f"near_{offset:02d}_b.png"
        )
        made += 2
    # 2b. the same trick across the split boundary - visually identical, not byte identical,
    #     so DD003 cannot see it and only a perceptual hash can.
    for offset in range(3):
        seed = 8000 + offset
        _pattern(seed).save(train_scratch / f"nearx_{offset:02d}.png")
        _pattern(seed).point(lambda value: min(255, int(value * 1.06) + 4)).save(
            test_dir / "scratch" / f"nearx_{offset:02d}_test.png"
        )
        made += 2
    # 3. label conflict: byte-identical images under three different class folders
    conflict = _pattern(9021)
    (root / "train" / "bruise").mkdir(parents=True, exist_ok=True)
    conflict.save(root / "train" / "bruise" / "conflict_a.png")
    conflict.save(root / "train" / "dent" / "conflict_b.png")
    (test_dir / "crack").mkdir(parents=True, exist_ok=True)
    conflict.save(test_dir / "crack" / "conflict_c.png")
    made += 3
    # 4. corrupt files: a truncated JPEG and a zero-byte PNG
    (root / "train" / "crack").mkdir(parents=True, exist_ok=True)
    tmp = root / "train" / "crack" / "_seed.jpg"
    _pattern(4242).save(tmp, format="JPEG")
    payload = tmp.read_bytes()
    (root / "train" / "crack" / "truncated.jpg").write_bytes(payload[: max(20, len(payload) // 3)])
    tmp.unlink()
    (root / "train" / "crack" / "empty.png").write_bytes(b"")
    made += 2
    (root / "dataset-doctor.yaml").write_text(_image_config(), encoding="utf-8")
    (root / "PLANTED_FAULTS.md").write_text(_leaky_images_note(made), encoding="utf-8")
    return "exact duplicates, near-duplicates, label conflicts, corrupt files, imbalance"


def _pattern(seed_value: int) -> Any:
    """One deterministic image per seed: a random 8x8 block grid, upscaled.

    Random blocks make distinct seeds genuinely distinct under a perceptual hash, which
    is what lets a near-duplicate finding be traced back to a planted pair.
    """
    from PIL import Image

    rng = np.random.default_rng(seed_value)
    grid = rng.integers(0, 256, size=(8, 8), dtype=np.uint8)
    image = Image.fromarray(grid, mode="L").resize((64, 64), Image.Resampling.NEAREST)
    return image.convert("RGB")


def _image_config() -> str:
    return """# Generated by `dataset-doctor demo`.
dataset:
  type: image
labels:
  source: directory
policies: {}
"""


def _leaky_images_note(count: int) -> str:
    return f"""# leaky_images - planted faults ({count} images)

Every row below was read back out of an actual `dataset-doctor audit` run, with the
sample counts the tool reported rather than the counts the generator intended.

| # | Fault | Files | Observed |
| --- | --- | --- | --- |
| 1 | 4 byte-identical copies of one train image inside test | `test/scratch/dup_*.png` | DD003-0001 CRITICAL, 8 samples |
| 2 | 3 near-duplicate pairs across the boundary (brightness 1.06x + 4, so no shared sha256) | `train/scratch/nearx_*` / `test/scratch/nearx_*_test` | DD004-0001 HIGH, 6 samples = 3 pairs |
| 3 | 6 near-duplicate pairs inside train (brightness 1.03x + 2) | `train/scratch/near_*` | DD004-0002 LOW, 12 samples = 6 pairs |
| 4 | one image stored under three class folders (bruise, dent, crack) | `conflict_a/b/c.png` | DD009-0001 CRITICAL, 3 samples |
| 5 | a truncated JPEG and a zero-byte PNG | `train/crack/` | DD016-0001 HIGH, 2 of 146 files |
| 6 | class counts 40/30/18/8 in train vs 10/8/5/1 in test, no provenance block | labels / config | DD011, DD013, DD014 stay quiet; DD020 LOW |

Row 3 vs row 2 is the point of the fixture: the *same* kind of edit is a LOW fact when it
stays inside train and a HIGH leakage candidate when it crosses into test, and only the
second one can inflate a published score.

Row 6 is a deliberate negative result. The class imbalance is 40:8 and the label mix does
shift, but neither crosses the policy thresholds at this sample size, so the honest report
is silence - a tool that flagged every uneven class list would train users to ignore it.

DD004 excludes byte-identical pairs by design: rows 1 and 4 already own those samples, and
counting one fault twice at two severities is how a duplicate report becomes unfalsifiable.

`train/crack/_seed.jpg` is deleted after the truncated copy is written, so the fixture
contains no mystery bytes.
"""
