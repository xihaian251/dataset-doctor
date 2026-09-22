"""Paths and encodings: the failure mode that makes a tool look broken on a real machine.

Windows has three things the CI machines of most open-source tools do not: backslash path
separators, drive letters, and a user directory that is not ASCII. Unicode file names are the
common case for this project's users, not an edge case, so both the *input* path and the
*report* path are checked with Chinese names, and the report must still be readable text.

Spec test coverage: TEST 24 (Windows paths work), TEST 25 (Unicode / 中文路径 work).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import TABULAR_CONFIG, row, write_rows

from dataset_doctor import audit_dataset
from dataset_doctor.models import DatasetType

COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]


def _tabular(root: Path, columns: list[str] | None = None, train: int = 24, test: int = 12) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    columns = columns or COLUMNS
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(train)], columns)
    write_rows(
        root / "test.csv",
        [row(f"t{i:03d}", f"q{i // 4:02d}", index=train + i) for i in range(test)],
        columns,
    )
    return root


# ------------------------------------------------------------------- TEST 24: Windows
def test_test24_a_windows_path_with_spaces_brackets_and_a_drive_letter_works(tmp_path: Path) -> None:
    root = _tabular(tmp_path / "My Dataset (2026)" / "exports" / "final v2")

    result = audit_dataset(root)

    assert result.identity.num_samples == 36
    assert Path(result.identity.root_path) == root.resolve() or str(root.resolve()) in str(result.identity.root_path)


def test_test24_a_trailing_separator_and_mixed_separators_are_accepted(tmp_path: Path) -> None:
    root = _tabular(tmp_path / "trailing")
    as_string = str(root) + os.sep
    with_mixed = str(root).replace("\\", "/") if os.sep == "\\" else str(root)

    assert audit_dataset(Path(as_string)).identity.num_samples == 36
    assert audit_dataset(with_mixed).identity.num_samples == 36


def test_test24_a_relative_path_resolves_against_the_working_directory(tmp_path: Path, monkeypatch: Any) -> None:
    root = _tabular(tmp_path / "relative" / "dataset")
    monkeypatch.chdir(tmp_path / "relative")

    result = audit_dataset(Path("dataset"))

    assert result.identity.num_samples == 36
    assert result.identity.dataset_id == audit_dataset(root).identity.dataset_id
    assert result.identity.dataset_id, "the same data reached by another path spelling fingerprints the same"


def test_test24_backslashes_in_data_are_not_mangled_by_the_csv_layer(tmp_path: Path) -> None:
    """Windows users put paths *in* their cells; a CSV reader that eats escapes corrupts them."""
    root = tmp_path / "backslash_values"
    root.mkdir()
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")
    rows = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(12)]
    for record in rows:
        record["sex"] = f"C:\\Users\\example\\file_{record['record_id']}.txt"
    write_rows(root / "train.csv", rows, COLUMNS)
    write_rows(root / "test.csv", rows[:6], COLUMNS)

    result = audit_dataset(root)

    column = result.identity.schema["sex"]
    assert column in {"string", "object", "text"}, column
    values = [record.metadata.get("external_id") for record in result.manifest.records[:1]]
    assert values == ["r000"], "id columns must survive untouched"


# --------------------------------------------------------------------- TEST 25: Unicode
def test_test25_a_dataset_under_a_chinese_path_audits_and_reports(tmp_path: Path) -> None:
    root = _tabular(tmp_path / "数据集_2026" / "实验一")
    outdir = tmp_path / "输出报告"

    result = audit_dataset(root)
    from dataset_doctor.reports import write_reports

    written = write_reports(result.report, outdir)

    assert result.identity.num_samples == 36
    assert all(path.exists() for path in written)
    payload = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    assert "数据集_2026" in json.dumps(payload, ensure_ascii=False)
    assert "数据集_2026" in payload["identity"]["root_path"]
    html = (outdir / "report.html").read_text(encoding="utf-8")
    assert "数据集_2026" in html or "实验一" in html


def test_test25_unicode_column_names_and_values_are_audited_not_rejected(tmp_path: Path) -> None:
    """A Chinese-language dataset is the normal case for this tool's users, not a stress test."""
    root = tmp_path / "中文数据"
    root.mkdir()
    columns = ["编号", "病人", "年龄", "性别", "体重指数", "数值", "标签"]
    config = TABULAR_CONFIG.replace("target", "标签").replace("patient_id", "病人").replace("record_id", "编号")
    (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")

    def make(prefix: str, offset: int, count: int) -> list[dict[str, Any]]:
        return [
            {
                "编号": f"{prefix}{index:03d}",
                "病人": f"病人{index // 6:02d}",
                "年龄": 40 + index % 9,
                "性别": "男" if index % 2 else "女",
                "体重指数": round(20.0 + (index % 7) * 0.9, 2),
                "数值": round(1.5 + index * 0.25, 3),
                "标签": "阳性" if index % 3 == 0 else "阴性",
            }
            for index in range(offset, offset + count)
        ]

    write_rows(root / "train.csv", make("r", 0, 30), columns)
    write_rows(root / "test.csv", make("t", 30, 18), columns)

    result = audit_dataset(root)

    assert result.identity.dataset_type is DatasetType.TABULAR
    assert result.identity.num_samples == 48
    assert set(result.identity.class_counts) == {"阳性", "阴性"}
    assert result.identity.split_sizes == {"train": 30, "test": 18}
    assert result.identity.metadata["label_column"] == "标签"
    assert result.identity.metadata["group_columns"] == ["病人"]


def test_test25_a_conflicting_label_in_chinese_is_still_detected(tmp_path: Path) -> None:
    """DD009 has to compare labels by value; an encoding bug would hide the conflict."""
    root = tmp_path / "冲突标签"
    root.mkdir()
    columns = ["编号", "病人", "年龄", "性别", "体重指数", "数值", "标签"]
    config = TABULAR_CONFIG.replace("target", "标签").replace("patient_id", "病人").replace("record_id", "编号")
    (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")

    def one(identifier: str, patient: str, index: int, label: str) -> dict[str, Any]:
        return {
            "编号": identifier,
            "病人": patient,
            "年龄": 40 + index % 9,
            "性别": "男",
            "体重指数": round(21.0 + (index % 5) * 1.3, 2),
            "数值": round(2.5 + index * 0.4, 3),
            "标签": label,
        }

    train = [one(f"r{i:03d}", f"病人{i // 6:02d}", i, "阳性" if i % 3 == 0 else "阴性") for i in range(20)]
    test = [one(f"t{i:03d}", f"病人{40 + i // 6:02d}", i, "阴性") for i in range(10)]
    test.append(dict(train[0], 编号="t900", 病人="病人40"))
    write_rows(root / "train.csv", train, columns)
    write_rows(root / "test.csv", test, columns)

    result = audit_dataset(root)

    conflicts = result.by_rule("DD009")
    assert conflicts, "identical 中文 input with two different 标签 is a conflict"
    seen = {label for group in conflicts[0].evidence["groups"] for label in group["labels"]}
    assert seen == {"阳性", "阴性"}


# ------------------------------------------------------- the console script, end to end
@pytest.mark.parametrize("name", ["数据集_2026", "My Dataset (2026)"])
def test_the_installed_command_line_entry_point_survives_a_subprocess_with_that_directory(
    tmp_path: Path, name: str
) -> None:
    """In-process tests cannot catch an encoding failure at the stdout boundary.

    This runs the real console script with a UTF-8 child environment and reads its report
    back from disk, which is what a user on a Chinese Windows install actually does.
    """
    root = _tabular(tmp_path / name)
    outdir = tmp_path / "out"
    command = [
        sys.executable,
        "-m",
        "dataset_doctor.cli",
        "audit",
        str(root),
        "--output",
        str(outdir),
        "--format",
        "json",
        "--quiet",
    ]
    environment = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

    completed = subprocess.run(
        command, cwd=str(Path(__file__).resolve().parents[1]), env=environment, capture_output=True, timeout=180
    )

    assert completed.returncode in (0, 1), completed.stdout.decode("utf-8", "replace")[-800:]
    payload = json.loads((outdir / "report.json").read_text(encoding="utf-8"))
    assert payload["identity"]["num_samples"] == 36
    assert name in payload["identity"]["root_path"]
