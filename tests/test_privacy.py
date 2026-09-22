"""What a report may contain once it leaves the machine that produced it.

`AGENTS.md` promises reviewers relative paths, ids and digests, and no raw PII values. Those
promises are about the rendered artefact, so they are tested on the artefact: a detector that
starts out honest can still be undone by a writer, and the tabular adapter's unreadable-file
entries used to be absolute paths that were copied verbatim into DD016 evidence, into
`location.paths` and into `coverage.unreadable_files`.

The assertions walk the *values* of the dumped report rather than searching serialised text:
on Windows a leaked `C:\\...` is escaped to `C:\\\\...` by `json.dumps`, so a substring
search would certify a leak as clean.

Two things are deliberately excluded, and the tests name them as exceptions so they cannot
widen by accident: `identity.root_path` (the invocation path, shown in the report header) and
the repair plan's commands, which are worthless unless copy-pasteable.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from conftest import TABULAR_CONFIG, row, write_rows

from dataset_doctor import audit_dataset
from dataset_doctor.reports import build_repair_plan, json_payload, render_html, render_markdown

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
pytestmark = pytest.mark.skipif(not EXAMPLES.is_dir(), reason="example fixtures are not present")


def _string_values(node: Any) -> Iterator[str]:
    if isinstance(node, dict):
        for value in node.values():
            yield from _string_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _string_values(value)
    elif isinstance(node, str):
        yield node


def _absolute(values: Iterator[str] | list[str]) -> list[str]:
    offenders = []
    for value in values:
        trimmed = value.strip()
        if re.match(r"^[A-Za-z]:[\\/]", trimmed) or trimmed.startswith(("/", "\\\\")):
            offenders.append(trimmed)
    return offenders


@pytest.mark.parametrize("fixture", ["leaky_patient_dataset", "leaky_image_dataset", "unsafe_group_leakage"])
def test_no_finding_or_coverage_entry_names_an_absolute_path(fixture: str, tmp_path: Path) -> None:
    """Audited by absolute path, so `str(root)` is available to leak by construction."""
    root = (EXAMPLES / fixture).resolve()
    report = audit_dataset(root).report

    for finding in report.findings:
        dumped = finding.model_dump(mode="json")
        values = list(_string_values(dumped))
        assert str(root) not in values, f"{finding.finding_id} leaks the invocation path"
        assert _absolute(values) == [], f"{finding.finding_id} carries an absolute path"
    coverage_values = list(_string_values(report.coverage))
    assert str(root) not in coverage_values
    assert _absolute(coverage_values) == []


def test_the_invocation_path_is_the_one_documented_exception(tmp_path: Path) -> None:
    """`root_path` echoes how the tool was called; no other field in the payload may."""
    root = tmp_path / "cohort"
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(24)])
    write_rows(root / "test.csv", [row(f"t{i:03d}", f"q{i:02d}", index=i + 40) for i in range(8)])
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")

    report = audit_dataset(root.resolve()).report
    payload = json.loads(json_payload(report))
    del payload["identity"]
    del payload["repair_plan"]

    assert report.identity.root_path == str(root.resolve())
    assert str(root.resolve()) not in list(_string_values(payload))


def test_an_unreadable_split_file_is_reported_by_its_declared_relative_path(tmp_path: Path) -> None:
    """The exact shape that used to write `str(self.root / path)` into three places at once."""
    root = tmp_path / "cohort"
    write_rows(root / "train.csv", [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(24)])
    write_rows(root / "test.csv", [row(f"t{i:03d}", f"q{i:02d}", index=i + 40) for i in range(8)])
    (root / "dataset-doctor.yaml").write_text(
        TABULAR_CONFIG + "splits:\n  train: train.csv\n  test: test.csv\n  holdout: declared_but_absent.csv\n",
        encoding="utf-8",
    )

    result = audit_dataset(root.resolve())
    unreadable = result.report.coverage["unreadable_files"]

    assert [item["path"] for item in unreadable] == ["declared_but_absent.csv"]
    assert str(root) not in json.dumps(unreadable)
    dd016 = result.by_rule("DD016")
    assert dd016, "an unreadable split is DD016's subject"
    assert dd016[0].evidence["files"][0]["path"] == "declared_but_absent.csv"
    assert "declared_but_absent.csv" in dd016[0].location.paths


def test_the_pii_rule_counts_matches_and_shows_no_value_in_any_format(tmp_path: Path) -> None:
    """DD021 exists to say "a column looks like contact details" about data someone else owns.

    The literal is the sensitive part, so it must survive neither the JSON nor the two
    human-readable renderings.
    """
    root = tmp_path / "cohort"
    secret = "chief.nurse@example.org"
    columns = ["record_id", "patient_id", "age", "sex", "bmi", "value", "target", "contact"]
    train = [row(f"r{i:03d}", f"p{i // 8:02d}", index=i) for i in range(40)]
    for index, record in enumerate(train):
        record["contact"] = secret if index < 2 else "masked"
    test = [row(f"t{i:03d}", f"q{i:02d}", index=i + 60) for i in range(10)]
    for record in test:
        record["contact"] = "masked"
    write_rows(root / "train.csv", train, columns)
    write_rows(root / "test.csv", test, columns)
    (root / "dataset-doctor.yaml").write_text(TABULAR_CONFIG, encoding="utf-8")

    report = audit_dataset(root.resolve()).report
    plan = build_repair_plan(report.findings, root=report.identity.root_path)
    rendered = "\n".join([json_payload(report, plan), render_markdown(report, plan), render_html(report, plan)])
    values = [value for finding in report.findings for value in _string_values(finding.model_dump(mode="json"))]

    hits = [finding for finding in report.findings if finding.rule_id == "DD021"]
    assert hits, "a column with contact-shaped values is exactly DD021's subject"
    assert hits[0].evidence["matching_rows"] == 2
    assert hits[0].evidence["values_shown"] is False
    assert secret not in rendered
    assert "example.org" not in rendered
    assert all(secret not in value for value in values)
