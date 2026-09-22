"""Discovery: what the tool is allowed to conclude from a directory tree alone.

Section 10 of the spec forbids assuming a standard layout. Every case below therefore
asserts on two things: the split set that was resolved, and the note that explains it.
A note is part of the result - an inference the report cannot show is an inference the
reviewer cannot check.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dataset_doctor_audit import load_config
from dataset_doctor_audit.discovery import discover
from dataset_doctor_audit.models import DatasetType, SplitRole

HEADER = "record_id,patient_id,age,value,target\n"


def build(root: Path, layout: dict[str, str]) -> Path:
    """Create ``root`` and write ``layout`` as ``relative path -> file contents``."""
    for relative, contents in layout.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")
    if not (root / "dataset-doctor.yaml").exists():
        (root / "dataset-doctor.yaml").write_text("dataset:\n  type: tabular\npolicies: {}\n", encoding="utf-8")
    return root


def spec_for(root: Path):
    return discover(root, load_config(root))


# ------------------------------------------------------------------- split resolution
def test_a_directory_of_split_names_is_a_split_set(tmp_path: Path) -> None:
    root = build(
        tmp_path / "dirs",
        {"train/a.csv": HEADER + "r1,p1,40,1,0\n", "test/b.csv": HEADER + "t1,q1,41,2,1\n"},
    )

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "test"}
    assert all(s.kind == "directory" for s in spec.splits)
    assert {s.name: s.role for s in spec.splits} == {"train": SplitRole.TRAIN, "test": SplitRole.TEST}
    assert any("subdirectories" in note for note in spec.inference_notes)


def test_a_half_finished_conversion_keeps_both_sources_and_says_so(tmp_path: Path) -> None:
    """`train/` next to `train.csv` is what an interrupted script leaves behind."""
    root = build(
        tmp_path / "mixed",
        {
            "train/a.csv": HEADER + "r1,p1,40,1,0\n",
            "train.csv": HEADER + "r2,p2,41,2,1\n",
            "test.csv": HEADER + "t1,q1,42,3,0\n",
        },
    )

    spec = spec_for(root)

    assert {s.name: s.kind for s in spec.splits} == {"train": "directory", "test": "file"}
    collision = [note for note in spec.inference_notes if note.startswith("Not audited")]
    assert collision and "train.csv" in collision[0] and "train/" in collision[0]
    assert "audit of that split is not the whole split" in collision[0]


def test_split_names_are_canonicalised_not_invented(tmp_path: Path) -> None:
    root = build(
        tmp_path / "alias",
        {
            "training/a.csv": HEADER + "r1,p1,40,1,0\n",
            "validation/b.csv": HEADER + "r2,p2,41,2,1\n",
            "tst/c.csv": HEADER + "r3,p3,42,3,0\n",
        },
    )

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "val", "test"}


def test_a_wrapper_directory_is_entered_once(tmp_path: Path) -> None:
    root = build(
        tmp_path / "wrapped",
        {
            "data/train/a.csv": HEADER + "r1,p1,40,1,0\n",
            "data/test/b.csv": HEADER + "r2,p2,41,2,1\n",
        },
    )

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "test"}
    assert any(note.startswith("Splits discovered under data/") for note in spec.inference_notes)


def test_unstructured_data_becomes_one_split_named_all_with_an_explicit_warning(tmp_path: Path) -> None:
    root = build(tmp_path / "pile", {"rows.csv": HEADER + "r1,p1,40,1,0\n"})

    spec = spec_for(root)

    assert [(s.name, s.role) for s in spec.splits] == [("all", SplitRole.UNKNOWN)]
    assert any("INCONCLUSIVE" in note for note in spec.inference_notes)
    assert any("dataset-doctor.yaml" in note for note in spec.inference_notes)


def test_a_table_that_is_not_named_after_a_split_is_reported_not_silently_skipped(tmp_path: Path) -> None:
    root = build(
        tmp_path / "extra",
        {
            "train.csv": HEADER + "r1,p1,40,1,0\n",
            "test.csv": HEADER + "t1,q1,41,2,1\n",
            "predictions.csv": HEADER + "r1,p1,40,1,0\n",
        },
    )

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "test"}
    assert any("predictions.csv" in note and "not audited" in note for note in spec.inference_notes)


# ------------------------------------------------------------------- declared layouts
def test_declared_splits_override_every_heuristic(tmp_path: Path) -> None:
    root = tmp_path / "declared"
    build(
        root,
        {"part-01.csv": HEADER + "r1,p1,40,1,0\n", "part-02.csv": HEADER + "r2,p2,41,2,1\n"},
    )
    (root / "dataset-doctor.yaml").write_text(
        "dataset:\n  type: tabular\nsplits:\n  train: part-01.csv\n  test: part-02.csv\npolicies: {}\n",
        encoding="utf-8",
    )

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "test"}
    assert all(s.role is not SplitRole.UNKNOWN for s in spec.splits)


def test_a_split_column_inside_one_file_is_a_real_split(tmp_path: Path) -> None:
    root = build(
        tmp_path / "column",
        {"all.csv": "record_id,split,value\nr1,train,1\nt1,test,2\n"},
    )
    (root / "dataset-doctor.yaml").write_text("dataset:\n  type: tabular\npolicies: {}\n", encoding="utf-8")

    spec = discover(root / "all.csv", load_config(root / "all.csv"))

    assert spec.split_column == "split"
    assert spec.splits == []
    assert any("inside all.csv" in note for note in spec.inference_notes)


# ------------------------------------------------------------------- noise on disk
def test_editor_and_archive_artefacts_are_never_read_as_data(tmp_path: Path) -> None:
    root = build(
        tmp_path / "noise",
        {
            "train/a.csv": HEADER + "r1,p1,40,1,0\n",
            "test/b.csv": HEADER + "r2,p2,41,2,1\n",
            "__MACOSX/junk.csv": HEADER,
            "Thumbs.db": "x",
            ".DS_Store": "x",
        },
    )
    (root / ".ipynb_checkpoints").mkdir()
    (root / ".ipynb_checkpoints" / "train.csv").write_text(HEADER, encoding="utf-8")

    spec = spec_for(root)

    assert {s.name for s in spec.splits} == {"train", "test"}
    assert not any("__MACOSX" in s.name or "checkpoint" in s.name for s in spec.splits)


def test_type_is_inferred_from_content_and_recorded_as_an_inference(tmp_path: Path) -> None:
    import numpy as np
    from PIL import Image

    root = tmp_path / "auto"
    for split in ("train", "test"):
        directory = root / split / "cat"
        directory.mkdir(parents=True)
        Image.fromarray(np.full((8, 8, 3), 90, dtype=np.uint8), "RGB").save(directory / "a.png")
    (root / "dataset-doctor.yaml").write_text("policies: {}\n", encoding="utf-8")

    spec = discover(root, load_config(root))

    assert spec.resolved_type is DatasetType.IMAGE
    assert any("inferred from content" in note for note in spec.inference_notes)


def test_a_missing_path_fails_before_any_caching(tmp_path: Path) -> None:
    from dataset_doctor_audit.errors import DiscoveryError

    with pytest.raises(DiscoveryError, match="does not exist"):
        discover(tmp_path / "nope", load_config(tmp_path))
