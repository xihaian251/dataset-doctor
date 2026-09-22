"""File formats: the audit must not depend on the container.

A parquet file and the csv it came from have to produce the same verdict, or "local-first,
any format" is a slogan. These tests also pin the modality list from the spec: tabular via
csv/tsv/parquet/Excel, image via jpg/png/webp/bmp.

Spec test coverage: TEST 26 (Excel reads correctly), TEST 27 (Parquet reads correctly).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from conftest import TABULAR_CONFIG, row, write_rows
from PIL import Image

from dataset_doctor_audit import audit_dataset
from dataset_doctor_audit.errors import DatasetDoctorError
from dataset_doctor_audit.models import DatasetType

COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]


def _config(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    return root


def _leaky_frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    """60 rows where three patients and eight whole rows appear on both sides of the boundary."""
    train = pd.DataFrame([row(f"r{i:03d}", f"p{i // 6:02d}", index=i) for i in range(40)])
    leaked = [row(f"r{i:03d}", f"p{i // 6:02d}", index=i) for i in range(8)]
    test = pd.DataFrame(leaked + [row(f"t{i:03d}", f"p{10 + i // 6:02d}", index=40 + i) for i in range(20)])
    return train, test


def _verdict(root: Path) -> tuple[str, tuple[str, ...], int]:
    result = audit_dataset(root)
    rules = tuple(sorted({finding.rule_id for finding in result.report.findings}))
    return result.report.eval_safety.value, rules, result.identity.num_samples


# ------------------------------------------------------------------- TEST 27: parquet
def test_test27_a_parquet_leaky_dataset_is_caught_the_same_way_as_a_csv_one(tmp_path: Path) -> None:
    train, test = _leaky_frames()
    csv_root = _config(tmp_path / "as_csv")
    write_rows(csv_root / "train.csv", train.to_dict("records"), COLUMNS)
    write_rows(csv_root / "test.csv", test.to_dict("records"), COLUMNS)
    parquet_root = _config(tmp_path / "as_parquet")
    train.to_parquet(parquet_root / "train.parquet", index=False)
    test.to_parquet(parquet_root / "test.parquet", index=False)

    expected = _verdict(csv_root)
    assert expected[0] == "FORMAL_EVAL_INVALID", "the fixture must actually be leaky"

    actual = _verdict(parquet_root)
    assert actual[1] == expected[1], "the same data must raise the same rules in either container"
    assert actual == expected


def test_test27_parquet_and_csv_agree_on_a_clean_dataset_too(tmp_path: Path) -> None:
    """Identical on the failure case only would be a coincidence, not a contract."""
    train = pd.DataFrame([row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(120)])
    test = pd.DataFrame([row(f"t{i:03d}", f"q{i // 8:02d}", index=120 + i) for i in range(60)])
    csv_root = _config(tmp_path / "clean_csv")
    write_rows(csv_root / "train.csv", train.to_dict("records"), COLUMNS)
    write_rows(csv_root / "test.csv", test.to_dict("records"), COLUMNS)
    pq_root = _config(tmp_path / "clean_pq")
    train.to_parquet(pq_root / "train.parquet", index=False)
    test.to_parquet(pq_root / "test.parquet", index=False)

    assert _verdict(csv_root)[0] == _verdict(pq_root)[0]
    assert _verdict(pq_root)[2] == 180


# --------------------------------------------------------------------- TEST 26: Excel
def test_test26_an_excel_workbook_is_audited_like_any_table(tmp_path: Path) -> None:
    train, test = _leaky_frames()
    root = _config(tmp_path / "as_excel")
    with pd.ExcelWriter(root / "train.xlsx") as writer:
        train.to_excel(writer, index=False, sheet_name="train")
    with pd.ExcelWriter(root / "test.xlsx") as writer:
        test.to_excel(writer, index=False, sheet_name="test")

    result = audit_dataset(root)

    assert result.identity.dataset_type is DatasetType.TABULAR
    assert result.identity.num_samples == 68
    assert result.by_rule("DD003"), "a duplicate row inside a workbook is still a duplicate row"
    assert result.report.eval_safety.value == "FORMAL_EVAL_INVALID"


def test_test26_multi_sheet_workbooks_are_never_read_as_only_their_first_sheet(
    tmp_path: Path,
) -> None:
    """68 rows in two sheets, one split declared: auditing sheet 1 alone would lose 28 rows."""
    train, test = _leaky_frames()
    root = _config(tmp_path / "one_workbook")
    with pd.ExcelWriter(root / "splits.xlsx") as writer:
        train.to_excel(writer, index=False, sheet_name="train")
        test.to_excel(writer, index=False, sheet_name="test")

    with pytest.raises(DatasetDoctorError) as excinfo:
        audit_dataset(root)

    message = str(excinfo.value)
    assert "splits.xlsx" in message and "train" in message and "test" in message
    assert "first sheet" in message, f"the refusal must say what it refused to do: {message}"


def test_test26_a_sheet_per_split_is_audited_once_the_splits_are_declared(tmp_path: Path) -> None:
    """The documented way to keep a workbook's sheets apart: say which sheet is which split."""
    train, test = _leaky_frames()
    root = tmp_path / "declared"
    root.mkdir()
    (root / "dataset-doctor.yaml").write_text(
        TABULAR_CONFIG + "splits:\n  train: splits.xlsx\n  test: splits.xlsx\n", encoding="utf-8"
    )
    with pd.ExcelWriter(root / "splits.xlsx") as writer:
        train.to_excel(writer, index=False, sheet_name="train")
        test.to_excel(writer, index=False, sheet_name="test")

    result = audit_dataset(root)

    assert result.identity.split_sizes == {"train": 40, "test": 28}
    assert result.by_rule("DD003"), "the duplicated rows are still duplicates on two sheets"


# ------------------------------------------------------------------------- other tabular
def test_a_tsv_split_is_read_with_the_right_delimiter(tmp_path: Path) -> None:
    rows = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(24)]
    root = _config(tmp_path / "tsv")
    for name, chunk in (("train", rows[:16]), ("test", rows[16:])):
        path = root / f"{name}.tsv"
        path.write_text(
            "\t".join(COLUMNS) + "\n" + "\n".join("\t".join(str(r[c]) for c in COLUMNS) for r in chunk) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    result = audit_dataset(root)

    assert result.identity.num_samples == 24
    assert set(result.identity.schema) == set(COLUMNS)


def test_several_files_in_one_split_are_merged_not_audited_separately(tmp_path: Path) -> None:
    """A split spread over part-0/part-1 is one split of 32 rows, not two splits of 16."""
    dataset = _config(tmp_path / "parts")
    parts = dataset / "train"
    parts.mkdir(parents=True)
    rows = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(32)]
    write_rows(parts / "part-0.csv", rows[:16], COLUMNS)
    write_rows(parts / "part-1.csv", rows[16:], COLUMNS)
    write_rows(dataset / "test.csv", [row(f"t{i:03d}", f"q{i // 4:02d}", index=32 + i) for i in range(16)], COLUMNS)

    result = audit_dataset(dataset)

    assert result.identity.split_sizes["train"] == 32
    assert result.identity.num_samples == 48


def test_an_unsupported_extension_is_not_silently_treated_as_data(tmp_path: Path) -> None:
    root = _config(tmp_path / "json_only")
    (root / "train.json").write_text("[]", encoding="utf-8")

    with pytest.raises(DatasetDoctorError):
        audit_dataset(root)


# ------------------------------------------------------------------------- image formats
@pytest.mark.parametrize("suffix", [".png", ".jpg", ".bmp", ".webp"])
def test_every_supported_image_extension_is_discovered_and_hashed(tmp_path: Path, suffix: str) -> None:
    root = tmp_path / f"imgs{suffix.replace('.', '_')}"
    config = "dataset:\n  type: image\nlabels:\n  source: directory\npolicies: {}\n"
    (root / "train" / "cat").mkdir(parents=True)
    (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")
    for index in range(3):
        image = Image.new("RGB", (24, 24), tuple((index * 70 % 256,) * 3))
        image.save(root / "train" / "cat" / f"{index}{suffix}")

    result = audit_dataset(root)

    assert result.identity.dataset_type is DatasetType.IMAGE
    assert result.identity.num_samples == 3
    assert result.identity.file_extensions == {suffix: 3}
    assert result.identity.class_counts.get("cat") == 3


def test_image_labels_come_from_the_directory_name(tmp_path: Path) -> None:
    root = tmp_path / "folder_labels"
    (root / "train" / "cat").mkdir(parents=True)
    (root / "dataset-doctor.yaml").write_text(
        "dataset:\n  type: image\nlabels:\n  source: directory\npolicies: {}\n", encoding="utf-8"
    )
    for split, labels in (("train", ("cat", "dog")), ("test", ("cat", "dog"))):
        for label in labels:
            (root / split / label).mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (16, 16), (90, 40, 200 if label == "dog" else 20)).save(root / split / label / "a.png")

    result = audit_dataset(root)

    assert result.identity.split_sizes == {"train": 2, "test": 2}
    assert result.identity.class_counts == {"cat": 2, "dog": 2}
    assert result.rule("DD009").status.value != "NOT_RUN", "directory labels must be usable as labels"
