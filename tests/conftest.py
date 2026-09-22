"""Deterministic tiny datasets on disk, plus the two helpers every test needs.

Nothing here samples from a global RNG: a fixture that changes between runs would make
the assertions on exact counts worthless.
"""

from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from dataset_doctor_audit import audit_dataset, load_config
from dataset_doctor_audit.audit import AuditResult
from dataset_doctor_audit.models import AuditFinding, AuditStatus, Severity

TABULAR_CONFIG = """\
dataset:
  type: tabular
labels:
  column: target
groups:
  columns: [patient_id]
id_columns: [record_id]
policies: {}
"""

IMAGE_CONFIG = """\
dataset:
  type: image
labels:
  source: directory
policies: {}
"""

TABULAR_COLUMNS = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target"]

CYCLE = 20
_PHI = (5**0.5 - 1) / 2
_PHI2 = 0.7548776662466927


def row(record_id: str, patient_id: str, index: int | None = None, **values: Any) -> dict[str, Any]:
    """One deterministic row whose features depend only on ``index``.

    Two properties matter for a leakage test fixture. ``age``/``sex``/``target`` repeat
    every CYCLE rows, so any split whose size is a multiple of CYCLE has an identical
    marginal distribution - "no shift reported" is then a real assertion rather than luck.
    ``bmi``/``value`` come from a low-discrepancy sequence, so every row is still content
    unique and the fixture cannot trigger the duplicate detectors by accident.
    """
    n = int("".join(character for character in record_id if character.isdigit()) or 0) if index is None else index
    base = {
        "record_id": record_id,
        "patient_id": patient_id,
        "age": 40 + (n % CYCLE) // 2,
        "sex": "M" if (n // 2) % 2 else "F",
        "bmi": round(20.0 + _frac(n * _PHI) * 10.0, 4),
        "value": round(_frac((n + 1) * _PHI2) * 100.0, 4),
        "target": n % 2,
    }
    base.update(values)
    return base


def _frac(x: float) -> float:
    return x - math.floor(x)


def write_rows(path: Path, rows: list[dict[str, Any]], columns: list[str] | None = None) -> Path:
    columns = columns or (list(rows[0]) if rows else TABULAR_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def tabular(tmp_path: Path) -> Any:
    """Build a tabular dataset from per-split row lists.

    ``tabular(train=[...], test=[...])`` writes ``train.csv``/``test.csv`` plus
    ``dataset-doctor.yaml`` and returns the root directory.
    """

    def make(
        name: str = "ds",
        config: str | None = TABULAR_CONFIG,
        columns: list[str] | None = None,
        **splits: list[dict[str, Any]],
    ) -> Path:
        root = tmp_path / name
        root.mkdir(parents=True, exist_ok=True)
        for split_name, rows in splits.items():
            write_rows(root / f"{split_name}.csv", rows, columns)
        if config is not None:
            (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")
        return root

    return make


@pytest.fixture
def images(tmp_path: Path) -> Any:
    """Build a ``split/class/*.png`` image dataset from 8x8 integer arrays."""

    def make(name: str = "imgs", config: str | None = IMAGE_CONFIG, **splits: dict[str, list[np.ndarray]]) -> Path:
        root = tmp_path / name
        for split_name, by_class in splits.items():
            for label, patterns in by_class.items():
                directory = root / split_name / label
                directory.mkdir(parents=True, exist_ok=True)
                for index, pattern in enumerate(patterns):
                    image = Image.fromarray(pattern.astype(np.uint8), mode="RGB").resize((32, 32), Image.NEAREST)
                    image.save(directory / f"{index:03d}.png")
        if config is not None:
            (root / "dataset-doctor.yaml").write_text(config, encoding="utf-8")
        return root

    return make


@pytest.fixture
def pattern() -> Any:
    """A distinct, reproducible 8x8 RGB tile so perceptual hashes do not collide."""

    def make(seed: int) -> np.ndarray:
        rng = np.random.default_rng(seed)
        return rng.integers(0, 256, (8, 8), dtype=np.uint8)[..., None].repeat(3, axis=2)

    return make


@pytest.fixture
def run_audit() -> Any:
    """Audit a path in-process, with optional fingerprint/preset overrides."""

    def make(
        root: Path | str,
        fingerprint: str | None = None,
        preset: str | None = None,
        **kwargs: Any,
    ) -> AuditResult:
        path = Path(root)
        config = load_config(path, preset=preset, fingerprint=fingerprint)
        return audit_dataset(path, config=config, **kwargs)

    return make


def findings_for(result: AuditResult, rule_id: str) -> list[AuditFinding]:
    return result.by_rule(rule_id)


def status_of(result: AuditResult, rule_id: str) -> AuditStatus | None:
    outcome = result.rule(rule_id)
    return None if outcome is None else outcome.status


def worst(findings: list[AuditFinding]) -> Severity | None:
    ranked = [finding.severity for finding in findings if finding.severity is not None]
    return max(ranked, key=lambda severity: severity.rank) if ranked else None


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return tmp_path
