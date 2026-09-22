# DD015 - Missingness Shift

| | |
| --- | --- |
| Category | `SCHEMA` |
| Default severity | `MEDIUM` at |delta| ≥ 0.3 · `LOW` otherwise |
| Formal impact | `POTENTIAL` |
| Evidence type | `STATISTICAL` |
| Applies to | tabular |
| Requires | at least two non-empty splits |
| Detector | `dataset_doctor/detectors/distribution.py::detect_missingness_shift` |

## Definition

The *pattern of what is missing* changes between splits: a column that was 2% empty in training
is 40% empty in the test set, or vice versa. The values that are present may be perfectly
comparable; the holes are not.

## Why It Matters

Two mechanisms, both silent. First, imputation: a median or a learned imputer is fitted to one
missingness pattern and applied to another, so the column's meaning shifts under the model.
Second, and closer to this tool's subject, missingness that correlates with the outcome (MNAR)
leaks through the missing indicator itself - "the lactate column is empty exactly when the
discharge diagnosis was already known" is a feature, and the model will use it. DD015 cannot
tell you whether the missingness is informative; it tells you the two splits are not the same
procedure, which is where that question starts.

## Detection

Same reference/target selection as [DD012](DD012-feature-shift.md) (the recognised train split,
or the first non-empty one, against every other non-empty split). For each column present in
both sides:

1. `rate = frame[column].isna().mean()` on each side.
2. Fire when `|rate_target − rate_reference| >= min_rate_delta` (default **0.1** = 10 points).
3. Rows are sorted by absolute delta, largest first, capped at 50 in the evidence.

`isna()` is the pandas notion of missing, so the tokens that became `NaN` on the way in
(`""`, `NA`, `null`, ...) count as missing - and a column whose placeholder survived as a string
does not. That is a loader question, not a statistics question; `dataset-doctor scan` shows the
dtypes so you can check.

The per-split rates are recorded under dynamically-named keys
(`<reference>_missing_rate`, `<target>_missing_rate`), so a finding for `train vs val` carries
`train_missing_rate` and `val_missing_rate`. The row counts are keyed `rows_train` /
`rows_test`, meaning *reference* and *target* rows.

## False Positives

- **Small splits have a coarse floor.** With 30 test rows, one missing cell moves the rate by
  0.033; three cells cross the default 0.1 threshold. `rows_test` is in the evidence for this
  judgement, and the honest fix is a bigger test split, not a bigger threshold.
- **A column that is genuinely sparse** (a lab only ordered for one ward) will differ across
  splits without anything being wrong, especially when the splits were not sampled by that
  stratification.
- **This rule does not detect MNAR.** It detects a change in the missing rate. Whether the
  missingness carries outcome information needs a model of why the value is absent, which no
  column comparison can supply.

## Severity

| Largest |delta| | Severity | Status | Formal impact |
| --- | --- | --- | --- | --- |
| ≥ 0.3 | `MEDIUM` | `WARNING` | `POTENTIAL` |
| ≥ 0.1 | `LOW` | `WARNING` | `POTENTIAL` |

Never blocking: a changed missingness pattern is an evaluation-protocol change you should know
about, not proof that held-out answers were fitted.

## Examples

A 90-row synthetic cohort built while writing this document: `sex` is left blank on every third
training row and complete in test - the shape of "we started recording sex properly after the
first export".

```text
DD015-0001 MEDIUM WARNING (POTENTIAL) STATISTICAL confidence=HIGH
Missingness shift between train and test
1 column(s) changed missing rate by >= 10% between train and test.
{ "columns": [ { "column": "sex", "train_missing_rate": 0.3333,
                 "test_missing_rate": 0.0, "delta": -0.3333 } ],
  "rows_train": 60, "rows_test": 30, "threshold": 0.1 }
```

The sign is informative here: the evaluation split is *more* complete than training, which is
the pattern a mid-study protocol change produces. The reverse sign - sparse test, complete
train - is the one to worry about, because it usually means the test rows had fewer
measurements taken, and an imputer trained on rich rows will fill values that were never
observed.

The nearest regression test is
`tests/test_structure.py::test_test28_nan_values_in_a_category_are_counted_not_crashed`, which
requires that blank cells be *attributed to some rule* rather than dropped silently. No shipped
example fixture fires DD015, so it is on the list in `docs/PROJECT_STATE.md` of rules verified
by hand-run data rather than by a dedicated test.

## Remediation

Find the stage where the pattern changed: a form that became mandatory, an export that dropped
empty columns, a device that started writing `NULL` instead of `""`. Then either repair the
data or state the protocol change in the evaluation write-up, and make sure any imputer is
fitted on a split whose missingness you actually expect at scoring time.

`policies.missingness_shift: {enabled: false}` turns the rule off as `NOT_RUN` (visible in the
coverage block); `{min_rate_delta: 0.2}` raises the floor if your splits are small and the noise
is constant.

---

*Registry entry: `rules.py` `DD015`. Policy block: `policies.missingness_shift`
(`min_rate_delta`, `enabled`). Related: [DD012](DD012-feature-shift.md),
[DD014](DD014-schema-drift.md), [DD010](DD010-missing-labels.md).*
