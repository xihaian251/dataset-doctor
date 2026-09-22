# DD019 - Split Drift

| | |
| --- | --- |
| Category | `VERSIONING` |
| Default severity | `CRITICAL` for a move into the test split · `HIGH` for any other move · `HIGH` for relabels |
| Formal impact | `BLOCKING` (moves) / `POTENTIAL` (relabels) |
| Evidence type | `DETERMINISTIC` |
| Confidence | `HIGH` - it is a comparison of two measured manifests, not an inference |
| Applies to | image + tabular |
| Requires | a baseline: `audit --baseline <name\|path>` |
| Detector | `dataset_doctor_audit/detectors/versioning.py::detect_version_drift` (sequences 2 and 3) |
| In V0.1 rule set | yes |

## Definition

Of the changes DD018 lists, the two that are not maintenance: samples that **crossed a split
boundary** between the baseline version and this one, and labels that **flipped** on samples
present in both. This is the rule the whole project is named around - the leakage that happens
between two audited versions rather than inside one - and it is why the tool distinguishes a
data quality issue from an evaluation validity issue.

## Why It Matters

A row that moves from `train` into `test` was, in the earlier version, available to the model.
If the number goes up across the two versions, nothing about the model has been shown: the
evaluation set changed underneath it. The severity is not rhetorical - the spec calls this "the
classic way for a published number to improve without the model improving", and it is the one
drift type that gets `BLOCKING` impact, so a single crossed row makes the verdict
`FORMAL_EVAL_INVALID`.

Relabelled rows are the softer version of the same problem: legitimate when an annotator
corrected a mistake, illegitimate when someone looked at the model's errors and then edited the
evaluation labels. The diff cannot tell those apart, so the finding states both readings
verbatim in `why_it_matters` instead of picking one.

## Detection

**Identity includes the split.** For tabular rows the sample id is
`stable_sample_id(split.name, declared_id)` (or path + row index when no id column is
declared), so a row that changes split *changes identity*: the join sees it as removed and
added. DD019 exists because `diff._match_by_content` pairs those two again by content digest
and records how it matched (`matched_by: "content"`) before the counts reach DD018. A move is
therefore never reported as an add plus a remove.

**Two findings, one diff.** `DD019-0001` is emitted when `diff.moved_samples` is non-empty,
`DD019-0002` when `diff.relabeled_samples` is. Both are `DETERMINISTIC` at `HIGH` confidence.
The move severity keys on `row["to"] == "test"`, and the counts in `why_it_matters` are
`into_test` / `out_of_test` from that same literal comparison.

**Sample references.** Descriptions and `evidence.moves[].sample` /
`evidence.changes[].sample` resolve through `AuditContext.display_id()`, so a reviewer gets
`test.csv::sr00010` (file + declared id value) instead of a hex digest. `affected_samples` and
`location.sample_ids` are filled from the row's `sample_id`, which for a content-paired move is
the **baseline-side** id - a hash this run's manifest cannot resolve. Both ids are in the
evidence (`sample_id` = baseline, `current_sample_id` = this run), which is what makes the
trace verifiable even where the display name is unavailable.

**Evidence keys and caps**: `moves` [50 rows, each with `from`, `to`, `sample`, `sample_id`,
`current_sample_id`, `matched_by`], `into_test`, `out_of_test`; and for relabels `changes` [50
rows with `from`, `to`, `sample`, `sample_id`]. Descriptions show the first 10 rows.

## False Positives and Limits

- **A re-split is a drift.** Regenerating train/test with a new seed produces hundreds of moves
  and no edits. The finding is still correct: the evaluation set is a different set, and old
  numbers do not transfer. Re-run the experiment, do not suppress the rule.
- **`into_test` matches the literal name `test`.** Split names come from the spec or from path
  inference, so a split called `eval`, `dev` or `val` escalates to `HIGH` instead of `CRITICAL`.
  It is still `FAIL` / `BLOCKING` and still invalidates the verdict - the escalation only
  changes severity, never the impact. A move into `validation` is `HIGH`.
- **Moves out of `test` count too**, and they are `HIGH`/`CRITICAL` in the same way: an
  evaluation set that silently shrank is also a different evaluation set.
- **Images need the content digest.** Two identical files in different folders pair by content;
  a re-encoded image does not, so it shows up as an add plus a remove (DD018) and DD019 stays
  silent. That silence is *not* a claim that nothing moved.
- **`dataset-doctor-audit diff` (snapshot vs snapshot, no audit)** reports the stored ids only - the
  raw `moved_samples` / `relabeled_samples` rows carry hashes and no `sample` key, because
  display resolution needs the audit context that maps ids back to id-column values.
- The baseline itself is assumed trustworthy. DD019 measures change relative to a snapshot; it
  cannot say whether the earlier version was the correct one.

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| ≥ 1 sample moved, `to == "test"` | `CRITICAL` | `FAIL` | `BLOCKING` |
| ≥ 1 sample moved, any other boundary crossing | `HIGH` | `FAIL` | `BLOCKING` |
| ≥ 1 label changed in both versions | `HIGH` | `WARNING` | `POTENTIAL` |
| Nothing moved or flipped | - | `PASS` (no finding) | - |
| No baseline supplied | - | `NOT_RUN` (`no baseline snapshot was supplied (--baseline)`) | - |

There is no ratio threshold and no policy-tunable floor: one crossed row is the finding.

## Examples

`examples/safe_tabular` (240 rows, 180 train / 60 test) copied and then: five `train.csv` rows
deleted, of which two were re-appended to `test.csv` (a move, not a removal), two brand-new rows
appended, and two `test.csv` labels flipped. Snapshot `v1` is the untouched copy; the audited
directory is the mutated one, 239 rows:

```text
DD019-0001 CRITICAL FAIL (BLOCKING) DETERMINISTIC confidence=HIGH
2 sample(s) moved between splits
test.csv::sr00010 train -> test; test.csv::sr00011 train -> test.
why_it_matters: 2 sample(s) entered the test split and 0 left it. Any metric from before the
  move was computed on a different evaluation set, so improvement across the two runs is not
  attributable to the model.
affected_count 2   affected_ratio 0.008368 (2 of 239)   auto_fix_available false
affected_samples ["092a0b6301b14339", "f27a004efffdf30b"]        <- baseline-side hashes
{ "moves": [ { "current_sample_id": "45e3acb2e40afe26", "from": "train",
               "matched_by": "content", "sample": "test.csv::sr00010",
               "sample_id": "092a0b6301b14339", "to": "test" }, ... ],
  "into_test": 2, "out_of_test": 0 }
recommended_action: Re-run the evaluation on one fixed split assignment, or publish the split
  manifest hash alongside the number.
```

The same directory with the two moved rows placed in `validation.csv` instead - so the inferred
split name is `val`, and the rows still left `train`:

```text
DD019-0001 HIGH FAIL (BLOCKING)
2 sample(s) moved between splits
validation.csv::sr00010 train -> val; validation.csv::sr00011 train -> val.
{ "into_test": 0, "out_of_test": 0, ... }
```

`HIGH`, not `CRITICAL`, and `BLOCKING` regardless - that run's verdict is also
`FORMAL_EVAL_INVALID`, with reasons
`["DD005 Entity leakage on 'patient_id': train / val: 3 samples (status FAIL)", "DD019 2 sample(s) moved between splits: 2 samples (status FAIL)"]`.
The DD005 line is the consequence, not a coincidence: a row that crosses into the evaluation
split carries its `patient_id` with it, which is exactly how [DD005](DD005-group-leakage.md)
then sees entity `s003` in two splits.

The relabel finding from the first run:

```text
DD019-0002 HIGH WARNING (POTENTIAL)
2 label(s) changed between versions
test.csv::er00001: 0 -> 1; test.csv::er00000: 0 -> 1.
affected_samples ["test.csv::er00001", "test.csv::er00000"]      <- resolvable, same id both sides
```

`POTENTIAL`, so relabels alone leave the verdict `RISKY` rather than `INVALID`.

Covered by `tests/test_diff.py::test_test16_a_row_crossing_the_boundary_is_a_move_not_an_add_and_a_remove`
(TEST 16), `::test_a_relabelled_row_that_also_moved_is_still_recognised_as_one_row`,
`::test_one_edited_cell_is_one_modified_sample_not_a_rewritten_file` and
`::test_reorganising_the_files_changes_nothing_about_the_samples`. The `val`-named variant above
was produced by a manual run (scratch fixture, `_doccheck/vd_val`) and is not in the suite.

## Remediation

DD019 is the one rule where the fix is never "apply it automatically" - `auto_fix_available` is
false because re-deriving someone else's split assignment would be this tool overwriting the
evaluation.

1. Re-run the affected metric on one frozen split assignment. If both numbers must stand,
   publish both with the dataset version.
2. If the move was intentional (a re-split, a leaked-entity purge), snapshot the *new* dataset
   as the baseline so future drift is measured against the set you actually evaluate on, and say
   so in the changelog.
3. Keep the split assignment under the same review process as the code:
   `dataset-doctor-audit audit ./data --save-snapshot v2 --baseline v1 -o report-v2` in CI fails on
   the drift instead of on a hunch.

`policies.split_drift: {severity: "..."}` retunes the displayed severity and
`{suppress: "<reason>"}` removes the rule from the verdict; `enabled: false` is **not** read by
this detector. Suppress either finding only with a written reason - suppressing `DD019` is
suppressing the tool's core claim, and the report keeps the reason visible.

---

*Registry entry: `rules.py` `DD019` ("Split Drift"). Policy block: `policies.split_drift`
(`severity`, `suppress`). Related: [DD018](DD018-version-drift.md) (the routine half of the same
diff), [DD005](DD005-group-leakage.md), [DD002](DD002-split-integrity.md),
[DD009](DD009-label-conflict.md).*
