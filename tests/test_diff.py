"""Fingerprint + diff: the second core innovation (spec section 220).

The point of `diff` is that it answers "what changed about the *experiment*", not "which
bytes differ". That distinction is what these tests lock down: an appended row is one row,
a row that crossed a split boundary is a move rather than an add plus a remove, and a file
that was merely reorganised changes nothing about the samples.

Spec test coverage: TEST 15 (v2 adds samples), TEST 16 (train -> test move is split drift),
TEST 17 (label changed), TEST 18 (repeated fingerprinting is stable).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import row, write_rows

from dataset_doctor import audit_dataset, diff_targets, load_config, snapshot_dataset
from dataset_doctor.models import AuditStatus

CONFIG = (
    "dataset:\n  type: tabular\nlabels:\n  column: target\ngroups:\n  columns: [patient_id]\n"
    "id_columns: [record_id]\npolicies: {}\n"
)


def _dataset(root: Path, **splits: list[dict[str, Any]]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for split_name, rows in splits.items():
        write_rows(root / f"{split_name}.csv", rows)
    (root / "dataset-doctor.yaml").write_text(CONFIG, encoding="utf-8")
    return root


def _rows(offset: int, count: int, patient_divisor: int = 8) -> list[dict[str, Any]]:
    return [
        row(f"r{offset + i:04d}", f"p{(offset + i) // patient_divisor:03d}", index=offset + i) for i in range(count)
    ]


def test_test15_appended_rows_are_added_and_nothing_else(tmp_path: Path) -> None:
    """A grow-only v2 must not look like a rewritten dataset."""
    v1 = _dataset(tmp_path / "v1", train=_rows(0, 40), test=_rows(100, 20))
    v2 = _dataset(tmp_path / "v2", train=_rows(0, 45), test=_rows(100, 20))

    diff = diff_targets(v1, v2)

    assert diff.comparable
    assert diff.summary.added == 5
    assert diff.summary.removed == 0
    assert diff.summary.modified == 0
    assert diff.summary.moved_between_splits == 0
    assert len(diff.added_samples) == 5, "the sample ids are stable hashes, so the count is the claim"


def test_test16_a_row_crossing_the_boundary_is_a_move_not_an_add_and_a_remove(tmp_path: Path) -> None:
    """The single most important diff case, and the one a naive implementation gets wrong.

    Counting it as "1 added / 1 removed" hides the fact that a training observation is now in
    the test set, so the audit of the moved version has to surface it as split drift.
    """
    train = _rows(0, 40)
    moved = train[7]
    test = _rows(100, 20)
    v1 = _dataset(tmp_path / "v1", train=train, test=test)
    v2 = _dataset(tmp_path / "v2", train=[item for i, item in enumerate(train) if i != 7], test=[*test, moved])

    diff = diff_targets(v1, v2)

    assert diff.summary.moved_between_splits == 1
    assert diff.summary.added == 0, "a move must not also be counted as new data"
    assert diff.summary.removed == 0
    assert diff.summary.modified == 0
    move = diff.moved_samples[0]
    assert {"train", "test"} == {move["from"], move["to"]}
    assert move["matched_by"] == "content"

    _, path = snapshot_dataset(v1, name="v1", directory=tmp_path)
    audited = audit_dataset(v2, baseline_snapshot=path)
    drift = [finding for finding in audited.by_rule("DD019") if "moved" in finding.title]
    assert drift, "the moved sample has to surface as split drift, not just as a diff row"
    assert drift[0].formal_impact.value == "BLOCKING"


def test_the_audit_baseline_finding_names_rows_a_reviewer_can_open(tmp_path: Path) -> None:
    """DD018's evidence is the changelog someone acts on, so a bare content hash is not enough.

    It also locks the honest half: finding-level change tracking cannot exist during an audit,
    because the diff is computed before this run's rules have produced any findings.
    """
    train = _rows(0, 40)
    v1 = _dataset(tmp_path / "v1", train=train, test=_rows(100, 20))
    v2 = _dataset(tmp_path / "v2", train=[*train, *_rows(200, 5)], test=_rows(100, 20))

    _, path = snapshot_dataset(v1, name="v1", directory=tmp_path, audit=True)
    audited = audit_dataset(v2, baseline_snapshot=path)

    drift = audited.by_rule("DD018")[0]
    assert drift.status is AuditStatus.WARNING
    # Added ids are ordered by content hash, not by insertion, so compare as a set.
    assert set(drift.evidence["added"]) == {f"train.csv::r{200 + index:04d}" for index in range(5)}
    assert drift.evidence["finding_changes"] == []
    assert any("finding_changes" in line for line in drift.limitations)


def test_test17_a_changed_label_is_a_label_change_not_a_new_sample(tmp_path: Path) -> None:
    left = _rows(0, 40)
    right = [dict(item) for item in left]
    right[3]["target"] = 1 - int(right[3]["target"])
    test = _rows(100, 20)
    v1 = _dataset(tmp_path / "v1", train=left, test=test)
    v2 = _dataset(tmp_path / "v2", train=right, test=test)

    diff = diff_targets(v1, v2)

    assert diff.summary.changed_labels == 1
    assert diff.summary.added == 0 and diff.summary.removed == 0
    assert diff.summary.modified == 0, "the observation did not change, only its answer"
    change = diff.relabeled_samples[0]
    assert str(change["from"]) != str(change["to"])


def test_a_relabelled_row_that_also_moved_is_still_recognised_as_one_row(tmp_path: Path) -> None:
    """Both axes at once: matching on row content alone would see an add plus a remove."""
    train = _rows(0, 40)
    moved = dict(train[9])
    moved["target"] = 1 - int(moved["target"])
    test = _rows(100, 20)
    v1 = _dataset(tmp_path / "v1", train=train, test=test)
    v2 = _dataset(tmp_path / "v2", train=[item for i, item in enumerate(train) if i != 9], test=[*test, moved])

    diff = diff_targets(v1, v2)

    assert diff.summary.added == 0 and diff.summary.removed == 0
    assert diff.summary.moved_between_splits == 1
    assert diff.summary.changed_labels == 1
    assert diff.moved_samples[0]["matched_by"] == "features"


def test_one_edited_cell_is_one_modified_sample_not_a_rewritten_file(tmp_path: Path) -> None:
    left = _rows(0, 40)
    right = [dict(item) for item in left]
    right[11]["bmi"] = 41.25
    test = _rows(100, 20)
    v1 = _dataset(tmp_path / "v1", train=left, test=test)
    v2 = _dataset(tmp_path / "v2", train=right, test=test)

    diff = diff_targets(v1, v2)

    assert diff.summary.modified == 1
    assert diff.summary.added == 0 and diff.summary.removed == 0
    assert diff.modified_samples[0]["content_changed"] is True


def test_reorganising_the_files_changes_nothing_about_the_samples(tmp_path: Path) -> None:
    """40 rows in one file, then the same 40 rows across two files in a directory."""
    train, test = _rows(0, 40), _rows(100, 20)
    v1 = _dataset(tmp_path / "v1", train=train, test=test)
    v2 = tmp_path / "v2"
    for split_name, rows in (("train", train), ("test", test)):
        directory = v2 / split_name
        directory.mkdir(parents=True, exist_ok=True)
        write_rows(directory / "part-0.csv", rows[: len(rows) // 2])
        write_rows(directory / "part-1.csv", rows[len(rows) // 2 :])
    (v2 / "dataset-doctor.yaml").write_text(CONFIG, encoding="utf-8")

    diff = diff_targets(v1, v2)

    assert diff.comparable
    assert diff.summary.added == 0 and diff.summary.removed == 0
    assert diff.summary.modified == 0 and diff.summary.moved_between_splits == 0


def test_a_diff_across_fingerprint_modes_is_refused(tmp_path: Path) -> None:
    """Spec sections 62-65: sample identity is derived differently per mode, so never guess."""
    root = _dataset(tmp_path / "ds", train=_rows(0, 40), test=_rows(100, 20))
    _, full = snapshot_dataset(root, name="full", directory=tmp_path, config=load_config(root))
    _, metadata = snapshot_dataset(
        root, name="meta", directory=tmp_path, config=load_config(root, fingerprint="metadata")
    )

    diff = diff_targets(full, metadata)

    assert not diff.comparable
    assert "fingerprint mode" in (diff.not_comparable_reason or "")


def test_unrelated_datasets_still_report_the_arithmetic(tmp_path: Path) -> None:
    v1 = _dataset(tmp_path / "left", train=_rows(0, 20), test=_rows(100, 20))
    v2 = _dataset(tmp_path / "right", train=_rows(500, 20, 4), test=_rows(700, 20, 4))

    diff = diff_targets(v1, v2)

    assert diff.summary.added == 40 and diff.summary.removed == 40
    assert diff.summary.moved_between_splits == 0


def test_test18_repeated_fingerprinting_is_stable(tmp_path: Path) -> None:
    """Same bytes and same config twice: the identity, the findings and the verdict agree."""
    root = _dataset(tmp_path / "ds", train=_rows(0, 40), test=_rows(100, 20))

    first = audit_dataset(root)
    second = audit_dataset(root)

    assert first.report.config_hash == second.report.config_hash
    assert first.identity.dataset_id == second.identity.dataset_id
    assert first.identity.manifest_hash == second.identity.manifest_hash
    assert [finding.finding_id for finding in first.report.findings] == [
        finding.finding_id for finding in second.report.findings
    ]
    assert first.report.eval_safety is second.report.eval_safety


def test_a_snapshot_of_an_unchanged_dataset_diffs_to_nothing(tmp_path: Path) -> None:
    root = _dataset(tmp_path / "ds", train=_rows(0, 40), test=_rows(100, 20))
    snapshot, path = snapshot_dataset(root, name="live", directory=tmp_path)

    assert snapshot.identity.num_samples == 60
    diff = diff_targets(root, path)
    assert diff.comparable
    assert diff.summary.added == 0 and diff.summary.removed == 0
    assert diff.summary.modified == 0 and diff.summary.moved_between_splits == 0


def test_an_unaudited_side_never_reports_findings_as_resolved(tmp_path: Path) -> None:
    """A bare scan has no findings, which is not the same as having no problems.

    Diffing an audited snapshot against a directory snapshot used to call every baseline
    finding "resolved" - the tool manufacturing its own silent PASS, and the audit path hit
    it too because the diff is computed before this run's rules produce anything.
    """
    root = _dataset(tmp_path / "ds", train=_rows(0, 40), test=_rows(100, 20))
    audited, path = snapshot_dataset(root, name="v1", directory=tmp_path, audit=True)

    assert audited.findings_digest.get("entries"), "the control side needs findings to compare"

    against_directory = diff_targets(path, root)
    assert against_directory.finding_changes == []
    assert against_directory.summary.resolved_findings == 0
    assert against_directory.summary.new_findings == 0

    # Same training data, half the evaluation set: the audited findings have to move.
    second = _dataset(tmp_path / "ds2", train=_rows(0, 40), test=_rows(100, 10))
    _, second_path = snapshot_dataset(second, name="v2", directory=tmp_path, audit=True)

    between_audits = diff_targets(path, second_path)
    assert between_audits.finding_changes, "two audited snapshots must still be comparable"
    assert any(row["change"] in {"changed", "resolved"} for row in between_audits.finding_changes)
