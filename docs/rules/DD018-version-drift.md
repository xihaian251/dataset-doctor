# DD018 - Version Drift

| | |
| --- | --- |
| Category | `VERSIONING` |
| Default severity | `MEDIUM` when ≥ 5% of samples changed · `LOW` for anything less |
| Formal impact | `POTENTIAL` (the drift DD019 measures out of the same diff is `BLOCKING`) |
| Evidence type | `DETERMINISTIC` |
| Applies to | image + tabular |
| Requires | a baseline: `audit --baseline <name\|path>`, or two snapshots for `dataset-doctor diff` |
| Detector | `dataset_doctor/detectors/versioning.py::detect_version_drift` |
| In V0.1 rule set | yes |

## Definition

What changed between the dataset you audited then and the dataset you are auditing now:
samples added, removed and modified - plus, in the same diff, the labels that flipped and the
rows that crossed a split boundary. This is the fingerprint half of the tool's second claim:
a dataset is not a folder of files, it is a set of identities you can compare across time.

## Why It Matters

"I re-ran the same experiment and got a different number" almost always has a data
explanation. A metric computed on v1 and a metric computed on v2 answer different questions,
and unless the difference is written down somewhere reviewable, the comparison silently
becomes a claim about the model. DD018 writes it down: counts, and the ids of the rows behind
the counts.

Additions and removals are routine maintenance. The audit-relevant changes are the two the
same diff produces - a relabelled evaluation row and a row that moved into the test split -
and those are escalated to [DD019](DD019-split-drift.md) with their own severity.

## Detection

**Getting a baseline.** Snapshots live inside the dataset they describe, under
`.dataset-doctor/snapshots/<name>.json`, written by either:

```bash
dataset-doctor audit ./data --save-snapshot v1     # audit + snapshot in one pass
dataset-doctor snapshot ./data --name v1           # snapshot only
```

`--baseline` accepts that name, a dataset id, or a path to a `.json` file.

**The join.** Records are matched by sample id (relative path for images, row hash for tabular
rows). Unmatched rows on both sides are then paired by content, which is what lets a rename -
or a row that also changed its label - be recognised as *the same observation in a different
place* instead of an unexplained add plus an unexplained remove. Each paired row records how
it was matched (`matched_by: content` / `features`).

**Refusal over guessing.** If the two sides differ in dataset type or fingerprint mode, the
diff is not computed and the rule reports `Baseline snapshot not comparable` at `MEDIUM` /
`INCONCLUSIVE` / `NONE`: different modes derive sample identity differently, so every sample
would look added-and-removed.

**Severity arithmetic.** `(added + removed + modified) / num_samples >= 0.05` → `MEDIUM`,
otherwise `LOW`. Relabels and split moves are deliberately *not* in that numerator; they are
never routine maintenance, and burying them in a percentage of edits would dampen them.

**Evidence keys** (caps in brackets): `left`, `right`, `added` [50], `removed` [50],
`modified` [20], `relabelled` [20], `finding_changes` [20]. Sample references are resolved to
something openable - `train.csv::sr09000` is `<file>::<declared id column>`, falling back to
`<file>#row=<index>` when no id column is declared.

**Finding-level changes are not available during an audit**, and the finding says so in its
`limitations`: the baseline diff is computed before this run's rules produce findings, so the
right-hand side has no findings to compare. Reporting the baseline's findings as "resolved"
would be this tool manufacturing its own silent PASS. Use two *audited* snapshots:

```bash
dataset-doctor diff .dataset-doctor/snapshots/v1.json .dataset-doctor/snapshots/v2.json
```

## False Positives

- **Re-materialised splits.** Regenerating the train/test assignment with a new seed makes
  almost every row look moved. The finding is correct - the evaluation set is a different set
  - even though nothing was edited. If that is what happened, re-run the baseline experiment.
- **A touched file is not a modification.** Snapshots store path, split, label, size and
  content digest, not mtime. Re-stamping timestamps, or re-serialising a Parquet file whose
  rows are identical, produces no `modified` rows.
- **A renamed file is one sample, not two**, but only if its content survived the rename - a
  rename *plus* a re-encode shows as removed and added.
- **Different machines.** `left` and `right` are labels, and the current side is labelled with
  its resolved absolute path, so the text of a report is not byte-identical across machines.
  The hashes it cites are.

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| Sides not comparable (mode or type changed) | `MEDIUM` | `INCONCLUSIVE` | `NONE` |
| ≥ 5% of samples added / removed / modified | `MEDIUM` | `WARNING` | `POTENTIAL` |
| Any change at all, below that | `LOW` | `WARNING` | `POTENTIAL` |
| Nothing changed | - | `PASS` (no finding) | - |
| No baseline supplied | - | `NOT_RUN` (`no baseline snapshot was supplied (--baseline)`) | - |

## Examples

A 240-row control fixture (`examples/safe_tabular`, copied), then: five training rows deleted,
two brand-new rows appended, two rows moved into `test.csv`, and two evaluation labels flipped.
`audit --baseline v1`:

```text
DD018-0001 LOW WARNING (POTENTIAL) DETERMINISTIC
Dataset changed since baseline (v1 -> C:\Users\‹elided›\Documents\Qoder\2026-09-20\858e417c\_doccheck\vd)
Added 2, removed 3, modified 0, relabelled 2, moved between splits 2.
{ "left": "v1",
  "right": "C:\\Users\\‹elided›\\Documents\\Qoder\\2026-09-20\\858e417c\\_doccheck\\vd",
  "added": ["train.csv::sr09000", "train.csv::sr09001"],
  "removed": ["1f0423c0465ba918", "94c0ff3150cd9a92", "b0623c86878d39af"],
  "modified": [],
  "relabelled": [ { "sample": "test.csv::er00001", "sample_id": "0f2e05c4978df25e",
                    "from": "0", "to": "1" }, ... ],
  "finding_changes": [] }
limitations:
  - Removed samples are identified by content hash only: they exist in the baseline, so this
    run has no row path or id column to resolve them against.
  - Finding-level change tracking (`finding_changes`) is empty during an audit, because the
    diff is computed before this run's rules have produced findings. ...
```

Only the run directory is elided here (it carries the machine's account name); everything else
is the report's own text. `right` is the *resolved absolute path* of the audited directory,
which is why the two sides of a diff read so differently on a borrowed laptop.

`LOW`, not `MEDIUM`, because the numerator is 5 of 239 samples. The relabels and moves in the
same evidence are what produce the `CRITICAL` / `HIGH` pair in
[DD019](DD019-split-drift.md), and that run's verdict is `FORMAL_EVAL_INVALID`.

The same baseline audited with `--fingerprint metadata` instead of `full` refuses to compare:

```text
DD018-0001 MEDIUM INCONCLUSIVE (NONE)
Baseline snapshot not comparable
v1 and ‹elided absolute path› cannot be diffed sample-for-sample: fingerprint mode changed from full to
metadata; sample identity is derived differently in each mode
```

Re-auditing the unchanged fixture against a snapshot of itself produces `DD018` and `DD019`
both `PASS` with zero findings - the only way this rule says "nothing moved" is by having
measured both sides.

Diffing the two *audited* snapshots of that mutation, finding level:

```text
v1.json -> v2.json   240 -> 239 samples
  added 2   removed 3   modified 0   moved_between_splits 2   changed_labels 2
  new_findings 1        resolved_findings 0        new_leakage 1
  verdict   FORMAL_EVAL_SAFE -> FORMAL_EVAL_INVALID
  changed DD001|dataset   Dataset identified: ds_38e4e976 -> ds_ba648e62 (240 -> 239)
  new     DD005|cross_split|test|train   Entity leakage on 'patient_id': test / train
  changed DD012|cross_split|train|test   Feature distribution shift (60 -> 62)
```

The `new DD005` line is the same two moved rows seen from the other side: a row crossing into
test brings its `patient_id` with it, so `s003` now appears in both splits.

Covered by `tests/test_diff.py::test_test15_appended_rows_are_added_and_nothing_else` (TEST 15),
`::test_a_diff_across_fingerprint_modes_is_refused`,
`::test_a_snapshot_of_an_unchanged_dataset_diffs_to_nothing`,
`::test_the_audit_baseline_finding_names_rows_a_reviewer_can_open` (display ids and the empty
`finding_changes`), and
`::test_an_unaudited_side_never_reports_findings_as_resolved`.

## Remediation

Snapshot every dataset a published number came from, then diff before comparing numbers
across runs:

```bash
dataset-doctor audit ./data --save-snapshot v2 --baseline v1 -o report-v2
```

Record the dataset version (`dataset_id` + `manifest_hash`, both in every report) next to the
metric, not in a separate table. If the drift is real and intended, say so in the changelog -
that is what the `added` / `removed` / `relabelled` lists are for.

`policies.version_drift: {severity: "low"}` overrides the escalation and
`{suppress: "<reason>"}` removes the rule from the verdict; `enabled: false` is **not** read by
this detector. The rule cannot be answered at all without a baseline, which is why it shows up
as `NOT_RUN` in most first-run reports.

---

*Registry entry: `rules.py` `DD018`. Policy block: `policies.version_drift`
(`severity`, `suppress`). Related: [DD019](DD019-split-drift.md) (the blocking half of the same
diff), [DD001](DD001-dataset-identity.md) (what is being compared),
[DD002](DD002-split-integrity.md), [DD009](DD009-label-conflict.md).*
