"""Dataset diff: v1 vs v2 at sample, split, label and finding level.

The join key problem is the whole difficulty here, so it is stated openly: images
are matched by manifest sample id (their relative path), with content-hash matching
recovering renames; tabular rows are matched by their row hash or declared id. A
diff between two fingerprint modes is refused rather than guessed at, because every
sample would look added-and-removed (spec sections 62-65).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .models import (
    DatasetDiff,
    DatasetSnapshot,
    DiffSummary,
    SnapshotRecord,
)

LEAKAGE_RULES = {"DD003", "DD005", "DD006", "DD007", "DD009", "DD019"}
MAX_LISTED = 2000


def compare_snapshots(
    left: DatasetSnapshot,
    right: DatasetSnapshot,
    left_source: str | None = None,
    right_source: str | None = None,
) -> DatasetDiff:
    diff = DatasetDiff(
        left=left_source or left.name,
        right=right_source or right.name,
        left_identity=left.identity,
        right_identity=right.identity,
    )
    if left.identity.dataset_type is not right.identity.dataset_type:
        diff.comparable = False
        diff.not_comparable_reason = (
            f"dataset type changed from {left.identity.dataset_type.value} to {right.identity.dataset_type.value}"
        )
        return diff
    if left.fingerprint_mode is not right.fingerprint_mode:
        diff.comparable = False
        diff.not_comparable_reason = (
            f"fingerprint mode changed from {left.fingerprint_mode.value} to "
            f"{right.fingerprint_mode.value}; sample identity is derived differently in each mode"
        )
        return diff

    left_records = {record.sample_id: record for record in left.records}
    right_records = {record.sample_id: record for record in right.records}
    shared = sorted(set(left_records) & set(right_records))

    moved: list[dict[str, Any]] = []
    relabeled: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    for sample_id in shared:
        before, after = left_records[sample_id], right_records[sample_id]
        row: dict[str, Any] = {"sample_id": sample_id}
        if before.split != after.split:
            moved.append({"sample_id": sample_id, "from": before.split, "to": after.split})
        if (before.label or "") != (after.label or ""):
            relabeled.append({"sample_id": sample_id, "from": before.label, "to": after.label})
        content_changed = features_differ(before, after)
        if content_changed or (content_of(before) is None and before.size != after.size):
            row["content_changed"] = content_changed
            row["digest_before"], row["digest_after"] = content_of(before), content_of(after)
            row["size_before"], row["size_after"] = before.size, after.size
            modified.append(row)

    unmatched_left = sorted(set(left_records) - set(right_records))
    unmatched_right = sorted(set(right_records) - set(left_records))
    paired = _match_by_content(left_records, right_records, unmatched_left, unmatched_right)
    # Same content that left one split and appeared in another is a move, which is the
    # finding that matters for leakage - not an unexplained add plus an unexplained remove.
    for row in paired:
        if row["split_changed"]:
            moved.append(
                {
                    "sample_id": row["removed"],
                    # A content-paired row has a different id on each side; the current-run id is
                    # the only one the audit can resolve to a file and row for the reader.
                    "current_sample_id": row["added"],
                    "from": row["left_split"],
                    "to": row["right_split"],
                    "matched_by": row["matched_by"],
                }
            )
        # A pair matched by content has a different id on each side, so the loop over shared
        # ids above could not have compared its labels.
        before_label = left_records[str(row["removed"])].label
        after_label = right_records[str(row["added"])].label
        if (before_label or "") != (after_label or ""):
            relabeled.append(
                {
                    "sample_id": row["removed"],
                    "current_sample_id": row["added"],
                    "from": before_label,
                    "to": after_label,
                    "matched_by": row["matched_by"],
                }
            )
    renames = [row for row in paired if not row["split_changed"]]
    paired_ids = {str(row["removed"]) for row in paired} | {str(row["added"]) for row in paired}
    removed = [sample_id for sample_id in unmatched_left if sample_id not in paired_ids]
    added = [sample_id for sample_id in unmatched_right if sample_id not in paired_ids]

    finding_changes, new_leakage, resolved_leakage, new_dupes, resolved_dupes = _finding_changes(left, right)

    diff.summary = DiffSummary(
        added=len(added),
        removed=len(removed),
        modified=len(modified),
        moved_between_splits=len(moved),
        changed_labels=len(relabeled),
        changed_metadata=len(renames),
        new_findings=sum(1 for row in finding_changes if row["change"] == "new"),
        resolved_findings=sum(1 for row in finding_changes if row["change"] == "resolved"),
        new_duplicate_pairs=new_dupes,
        resolved_duplicate_pairs=resolved_dupes,
        new_leakage=new_leakage,
        resolved_leakage=resolved_leakage,
    )
    diff.added_samples = added[:MAX_LISTED]
    diff.removed_samples = removed[:MAX_LISTED]
    diff.modified_samples = modified[:MAX_LISTED]
    diff.moved_samples = moved[:MAX_LISTED]
    diff.relabeled_samples = relabeled[:MAX_LISTED]
    diff.finding_changes = finding_changes[:MAX_LISTED]
    diff.eval_safety_change = {
        "left": left.findings_digest.get("eval_safety", "UNKNOWN"),
        "right": right.findings_digest.get("eval_safety", "UNKNOWN"),
        "changed": left.findings_digest.get("eval_safety") != right.findings_digest.get("eval_safety"),
        "manifest_hash_left": left.identity.manifest_hash,
        "manifest_hash_right": right.identity.manifest_hash,
        "renamed_samples": renames[:200],
        "truncated": max(len(added) - MAX_LISTED, len(removed) - MAX_LISTED, 0),
    }
    return diff


def content_of(record: SnapshotRecord) -> str | None:
    """The digest of *this sample*, not of the file that happens to carry it.

    A tabular record's ``sha256`` is its container's hash: many rows share one CSV, so
    comparing those would report every row of a file as modified after a single append,
    and would match unrelated rows as renames. ``row_sha256`` is the row's own content.
    """
    return record.row_sha256 or record.sha256


def features_differ(before: SnapshotRecord, after: SnapshotRecord) -> bool:
    """Whether the *observation* changed, keeping the label out of the comparison.

    ``row_sha256`` covers the label, so using it here would report a corrected annotation
    as an edited sample too - and the two axes mean different things: a changed label is a
    relabelling, a changed observation is a different measurement.
    """
    left, right = before.feature_sha256, after.feature_sha256
    if left and right:
        return left != right
    return bool(content_of(before) and content_of(after) and content_of(before) != content_of(after))


def _match_by_content(
    left_records: dict[str, SnapshotRecord],
    right_records: dict[str, SnapshotRecord],
    unmatched_left: list[str],
    unmatched_right: list[str],
) -> list[dict[str, Any]]:
    """Same sample at a different id: a rename or a move, not an add plus a remove.

    Two passes, strictest first - identical row content, then identical *feature* content,
    which is what catches a row that was relabelled *and* moved between splits.
    """
    matches: list[dict[str, Any]] = []
    left_pending, right_pending = list(unmatched_left), list(unmatched_right)
    for label, key_of in (("content", content_of), ("features", lambda record: record.feature_sha256)):
        if not left_pending or not right_pending:
            break
        found = _match_pass(left_records, right_records, left_pending, right_pending, label, key_of)
        matches.extend(found)
        consumed = {str(row["removed"]) for row in found} | {str(row["added"]) for row in found}
        left_pending = [sample_id for sample_id in left_pending if sample_id not in consumed]
        right_pending = [sample_id for sample_id in right_pending if sample_id not in consumed]
    return matches


def _match_pass(
    left_records: dict[str, SnapshotRecord],
    right_records: dict[str, SnapshotRecord],
    unmatched_left: list[str],
    unmatched_right: list[str],
    matched_by: str,
    key_of: Any,
) -> list[dict[str, Any]]:
    by_hash: dict[str, list[str]] = defaultdict(list)
    for sample_id in unmatched_right:
        digest = key_of(right_records[sample_id])
        if digest:
            by_hash[str(digest)].append(sample_id)
    out: list[dict[str, Any]] = []
    for sample_id in unmatched_left:
        record = left_records[sample_id]
        digest = key_of(record)
        if not digest:
            continue
        candidates = by_hash.get(str(digest))
        if not candidates:
            continue
        partner = candidates.pop(0)
        out.append(
            {
                "removed": sample_id,
                "added": partner,
                "sha256": str(content_of(record) or digest),
                "matched_by": matched_by,
                "left_split": record.split,
                "right_split": right_records[partner].split,
                "path_changed": record.relative_path != right_records[partner].relative_path,
                "split_changed": record.split != right_records[partner].split,
            }
        )
    return out


def _finding_changes(left: DatasetSnapshot, right: DatasetSnapshot) -> tuple[list[dict[str, Any]], int, int, int, int]:
    left_entries = _entries(left)
    right_entries = _entries(right)
    if not left_entries or not right_entries:
        # One side was never audited (`diff <snapshot> <directory>`, and the audit path itself,
        # where the diff is computed before the rules run). Reporting "resolved" for every
        # baseline finding would claim the problem went away when nothing measured it.
        return [], 0, 0, 0, 0
    rows: list[dict[str, Any]] = []
    new_leakage = resolved_leakage = new_dupes = resolved_dupes = 0
    for key in sorted(set(left_entries) | set(right_entries)):
        before, after = left_entries.get(key), right_entries.get(key)
        if before and not after:
            rows.append({"change": "resolved", "key": key, "before": before})
            resolved_leakage += int(before.get("rule_id") in LEAKAGE_RULES)
            resolved_dupes += int(before.get("rule_id") in {"DD003", "DD004"})
        elif after and not before:
            rows.append({"change": "new", "key": key, "after": after})
            new_leakage += int(after.get("rule_id") in LEAKAGE_RULES)
            new_dupes += int(after.get("rule_id") in {"DD003", "DD004"})
        elif before and after and _digest_of(before) != _digest_of(after):
            rows.append({"change": "changed", "key": key, "before": before, "after": after})
    return rows, new_leakage, resolved_leakage, new_dupes, resolved_dupes


def _entries(snapshot: DatasetSnapshot) -> dict[str, dict[str, Any]]:
    digest = snapshot.findings_digest or {}
    entries = digest.get("entries") or {}
    return {str(key): value for key, value in entries.items() if isinstance(value, dict)}


def _digest_of(entry: dict[str, Any]) -> tuple[Any, ...]:
    return (
        entry.get("affected_count"),
        tuple(sorted((entry.get("severities") or {}).items())),
        tuple(sorted((entry.get("statuses") or {}).items())),
    )


def diff_lines(diff: DatasetDiff) -> list[str]:
    """The terminal summary. Structured output stays in report.json."""
    if not diff.comparable:
        return [
            "Dataset Doctor / diff",
            "",
            f"{diff.left}  vs  {diff.right}",
            "",
            f"NOT COMPARABLE: {diff.not_comparable_reason}",
        ]
    summary = diff.summary
    lines = [
        "Dataset Doctor / diff",
        "",
        f"{diff.left}  vs  {diff.right}",
        "",
        f"Added samples:          {summary.added:,}",
        f"Removed samples:        {summary.removed:,}",
        f"Modified samples:       {summary.modified:,}",
        f"Moved between splits:   {summary.moved_between_splits:,}",
        f"Changed labels:         {summary.changed_labels:,}",
        f"Renamed (same content): {summary.changed_metadata:,}",
        "",
        f"New findings:           {summary.new_findings:,}  (leakage {summary.new_leakage:,})",
        f"Resolved findings:      {summary.resolved_findings:,}  (leakage {summary.resolved_leakage:,})",
        "",
        f"Formal evaluation: {diff.eval_safety_change.get('left')} -> {diff.eval_safety_change.get('right')}",
    ]
    if diff.moved_samples:
        lines.append("")
        lines.append("Split moves (first 10):")
        lines.extend(f"  {row['sample_id']}: {row['from']} -> {row['to']}" for row in diff.moved_samples[:10])
    if diff.relabeled_samples:
        lines.append("")
        lines.append("Label changes (first 10):")
        lines.extend(f"  {row['sample_id']}: {row['from']} -> {row['to']}" for row in diff.relabeled_samples[:10])
    return lines
