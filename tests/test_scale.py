"""TEST 20: 50 000 files must not exhaust memory.

Skipped by default because it writes tens of thousands of files; run it with
``DATASET_DOCTOR_SCALE=1``. The guarantee being tested is not "it finished" but
"it finished without materialising the dataset": the audit holds one manifest
record per file and nothing per byte, so peak growth stays roughly linear in the
file count and independent of the file size.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

Image = pytest.importorskip("PIL.Image")

from dataset_doctor_audit import audit_dataset  # noqa: E402

FILES = int(os.environ.get("DATASET_DOCTOR_SCALE_FILES", "50000"))
ENABLED = os.environ.get("DATASET_DOCTOR_SCALE") == "1"
CLASSES = 500

pytestmark = pytest.mark.skipif(not ENABLED, reason="opt-in scale test: set DATASET_DOCTOR_SCALE=1 (writes 50k files)")


def _tiny_png(color: tuple[int, int, int]) -> bytes:
    from io import BytesIO

    handle = BytesIO()
    Image.new("RGB", (8, 8), color).save(handle, format="PNG")
    return handle.getvalue()


@pytest.fixture(scope="module")
def large_image_dataset(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the fixture, or reuse one a previous run already paid for.

    ``DATASET_DOCTOR_SCALE_DIR`` points at a dataset with the same shape (``train/clsNNN``
    plus a 20% ``test`` split, ``DATASET_DOCTOR_SCALE_FILES`` set to its train count).
    Writing 50 000 files costs more wall clock than auditing them, and a CI runner that has
    the artifact should not have to regenerate it to check the memory claim.
    """
    reuse = os.environ.get("DATASET_DOCTOR_SCALE_DIR")
    if reuse:
        root = Path(reuse).expanduser().resolve()
        assert (root / "dataset-doctor.yaml").is_file(), f"{root} is not an audited dataset"
        return root

    root = tmp_path_factory.mktemp("scale") / "images"
    palette = [_tiny_png((index * 37 % 256, index * 71 % 256, index * 13 % 256)) for index in range(CLASSES)]
    for index in range(FILES):
        label = f"cls{index % CLASSES:03d}"
        directory = root / "train" / label
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"s{index:06d}.png").write_bytes(palette[index % CLASSES])
        if index % 5 == 0:  # 20% of the images belong to the evaluation split
            test_dir = root / "test" / label
            test_dir.mkdir(parents=True, exist_ok=True)
            (test_dir / f"s{index:06d}.png").write_bytes(palette[index % CLASSES])
    (root / "dataset-doctor.yaml").write_text(
        "dataset:\n  type: image\nlabels:\n  source: directory\npolicies: {}\n", encoding="utf-8"
    )
    return root


def _peak_megabytes() -> float:
    psutil = pytest.importorskip("psutil")
    return psutil.Process().memory_full_info().peak_wset / 1024 / 1024


def test_test20_every_file_is_accounted_for_and_ram_stays_bounded(large_image_dataset: Path) -> None:
    started = time.perf_counter()
    result = audit_dataset(large_image_dataset)
    elapsed = time.perf_counter() - started
    peak = _peak_megabytes()

    assert result.identity.num_samples == FILES + FILES // 5
    assert sum(result.identity.split_sizes.values()) == result.identity.num_samples
    assert result.identity.class_counts and len(result.identity.class_counts) == CLASSES
    # 8 GB is the documented host budget; the interpreter, pandas and Pillow sit inside the
    # same number, so this is the user-facing ceiling rather than a claim about the loop.
    assert peak < 8192, f"peak working set {peak:.0f} MB over the documented 8 GB budget"
    assert elapsed < 1800, f"{elapsed:.0f}s for {result.identity.num_samples} samples"
    # The ceilings above are pass/fail; this is the measurement a README can quote. Run with
    # `-s` and copy it out rather than re-deriving it somewhere else.
    print(f"TEST 20 measured: {result.identity.num_samples:,} samples in {elapsed:.1f}s, peak {peak:.0f} MB")
