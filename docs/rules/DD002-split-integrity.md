# DD002 - Split Integrity

| | |
| --- | --- |
| Category | `SPLIT_INTEGRITY` |
| Default severity | `HIGH` |
| Formal impact | `BLOCKING` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular, image |
| Requires | declared or discovered splits |
| Detector | `dataset_doctor/detectors/structural.py::detect_split_integrity` |

## Definition

Whether the split structure the experiment assumes actually exists: are there at least
two splits, does each contribute samples, do two roles resolve to the same path, and is
one of the splits recognisable as the holdout?

## Why It Matters

Every cross-split rule - duplicates, entity leakage, temporal order, schema drift,
distribution shift - is defined *relative to a boundary*. If the boundary is missing,
empty or shared, those rules cannot answer anything, and a report that stays quiet about
it is worse than one that complains. An empty test split is the quietly dangerous case:
many loaders fall back to whatever data remains, so a "test accuracy" gets computed on
training data and looks entirely plausible.

DD002 is the rule that makes "the tool could not check" distinct from "the tool checked
and found nothing".

## Detection

Four independent checks, each with its own `metadata.reason`:

1. **`single_split`** - fewer than two splits were resolved. `INCONCLUSIVE`,
   `POTENTIAL`: the layout cannot answer the question, which is not the same as being
   wrong.
2. **`empty_split`** - a split was discovered but contributed 0 samples. `FAIL`,
   `BLOCKING`, `HIGH`.
3. **`shared_path`** - two declared split names resolve (after `expanduser` and
   `resolve()`) to the same filesystem path. `FAIL`, `BLOCKING`, `CRITICAL`: every sample
   in that path is in both splits by definition.
4. **`no_test_role`** - at least two splits exist but none maps to a test/eval role.
   `INCONCLUSIVE`, `MEDIUM`: leakage severity is ranked by which boundary it crosses, so
   without a named holdout, train/val-style findings stay at `HIGH` instead of `CRITICAL`.

Split roles come from the split *name* (`test`/`eval`/`validation`/`val`/`train`/`dev`/
`holdout`), canonicalised by the discovery layer and recorded as an *inference* in
`identity.metadata.inference_notes`. There is no `role:` key in `dataset-doctor.yaml`:
`splits:` is a plain name-to-path mapping, so if your holdout is named `kaggle`, the name
is what the role inference sees.

## False Positives

- **A deliberately missing test split** is a legitimate design - the holdout is an
  external benchmark. DD002 still reports `single_split`, and it should: the tool cannot
  certify evaluation safety from training data alone. Declare the benchmark as a second
  split if you want the cross-boundary rules to run.
- **A split column is not a shared path.** When splits are read out of one column
  (`temporal.split_column`), every role lives in the same file on purpose.
  `_path_collisions` returns early for that config; without the veto the tool reported
  the declared layout as the exact bug it is designed to avoid. This was a real bug,
  found and fixed, and it has a regression test.
- **Names the heuristics miss** (`kaggle`, `blind`, `challenge`) fall through to
  `no_test_role`. Rename the directory or the split key rather than arguing with the
  heuristic.

## Severity

`HIGH` for structural failures, `CRITICAL` when two roles point at one path, `MEDIUM`
when the holdout simply cannot be identified. Formal impact is `BLOCKING` for the two
cases that make a metric uninterpretable (empty eval split, shared path) and `POTENTIAL`
for the two that only limit coverage.

Suppression goes through the shared `suppress:` block and requires a reason, which stays
visible in the report as `SUPPRESSED`:

```yaml
suppress:
  - rule: DD002
    reason: "train only; evaluation is an external held-out benchmark we cannot ship"
```

## Examples

Measured from the test suite (`tests/test_structure.py`):

- `test_dd002_two_declared_splits_pointing_at_one_file_is_a_blocking_configuration` -
  train and test declared on one CSV: `CRITICAL`, `FAIL`, `BLOCKING`,
  `metadata.reason == "shared_path"`. `evidence.path` is the *declared, dataset-relative*
  path (`cohort.csv`); the resolved path is the grouping key and is never printed, because
  a report is written to be shared (`tests/test_privacy.py` asserts it suite-wide).
- `test_dd002_a_split_read_from_a_column_is_not_reported_as_a_shared_path` - the same
  file with `temporal.split_column: split` yields `split_sizes == {"train": 30,
  "test": 10}` and **no** `shared_path` finding.
- `test_test30_a_train_only_dataset_can_never_be_called_safe` - a train-only root is not
  `FORMAL_EVAL_SAFE`, and exits 1 under `--ci`.

## Remediation

Materialise the missing split, or declare the layout:

```yaml
splits:
  train: data/train.csv
  test: data/test.csv
```

If both roles genuinely read one file, that is a split column, and it belongs in
`temporal.split_column` - not in two `splits:` entries pointing at the same path.

---

*Registry entry: `rules.py` `DD002`. Related: [DD003](DD003-exact-duplicate.md),
[DD005](DD005-group-leakage.md), [DD014](DD014-schema-drift.md).*
