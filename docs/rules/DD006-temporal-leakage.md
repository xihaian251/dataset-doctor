# DD006 - Temporal Leakage

| | |
| --- | --- |
| Category | `LEAKAGE` |
| Default severity | `HIGH` |
| Formal impact | `BLOCKING` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular |
| Requires | `temporal.column`, at least two splits, `temporal.train_before_test` |
| Detector | `dataset_doctor_audit/detectors/leakage.py::detect_temporal_leakage` |

## Definition

Training rows dated at or inside the evaluation window. For a forecasting task - "predict
next-quarter demand", "predict discharge from the first 24 hours" - any training record
that post-dates the start of the test period contains information that did not exist when
the prediction was supposed to be made.

## Why It Matters

Time is the one feature a production system cannot cheat with. A model trained on 2026
data and evaluated on 2024 will look excellent and then meet a world it has not seen yet -
in the wrong direction. The failure is invisible in aggregate metrics: the split sizes are
perfect, the schema matches, the labels are clean.

## Detection

1. `temporal.column` unset → `NOT_RUN`. `train_before_test: false` → `NOT_RUN` with the
   reason *"policy does not require train to precede test, so time overlap is not an error
   here"*. The rule is **policy-driven**, because whether overlap is a bug is a question
   about the task, not about the bytes.
2. Parse the column with `pd.to_datetime(errors="coerce")` per split. Fewer than two
   splits with a parseable column → `InsufficientEvidence`.
3. Take each train-role split (falling back to a split literally named `train`) against
   each test-role split.
4. `violating = count(train_time >= min(test_time))`. Any violation fires.
5. Unparseable values are **excluded from the comparison and counted in the evidence**
   (`unparseable_timestamps`) and in the limitations, so a column that is 40% garbage
   cannot read as a clean pass.

The statistic is deliberately coarse - a single boundary comparison, not per-row ordering -
because it answers "does the training window reach into the evaluation window", which is
the claim that needs defending.

## False Positives

- **Overlapping time ranges are legitimate for i.i.d. tasks.** A random sample of
  historical events should overlap in time. This rule fires only because the policy says
  the task forecasts the future; set `temporal.train_before_test: false` and it stands
  down, in the open, as `NOT_RUN`.
- **A column that is not really the event time** - `last_modified`, an ETL timestamp, an
  export date - will produce a real finding about the wrong quantity. The evidence prints
  `train_max` and `test_min` so this is checkable in seconds.
- **Records that cluster on a boundary** (bulk imports, midnight batches) can produce a
  handful of violating rows that are an artefact of rounding. The count is in the finding;
  a 3-row violation and a 30,000-row violation are not the same decision.
- **Timezone-naive parsing** mixes local and UTC stamps. `utc=False` is used deliberately
  so a declared column parses predictably, but a mixed-zone column needs fixing at source.

## Severity

`HIGH` / `FAIL` / `BLOCKING`, always. Not `CRITICAL`: a temporal inversion is a smaller
contaminated region than an entity that appears on both sides, and severity differences
between blocking findings should not be inflated. A `BLOCKING` finding is enough to make
the verdict `FORMAL_EVAL_INVALID`.

## Examples

`examples/leaky_patient_dataset` is built for this: one `cohort.csv` with a `split` column
and a `collected_at` column, where train was collected in 2026, val in 2025 and test in
2024 - the exact inversion a "we appended the newest data to train" refactor produces.
Measured from `examples/RESULTS.md` (309 samples, `FORMAL_EVAL_INVALID`):

```text
DD006-0001 HIGH FAIL (BLOCKING) - train rows dated at or after test
```

and `tests/test_examples.py::test_the_mixed_clinical_fixture_catches_the_temporal_inversion_too`
asserts it fires. DD007-0003 additionally names `collected_at` as a predictive feature
candidate, which is the same underlying mistake seen from the other side.

## Remediation

Split by time: earliest in train, latest in test, with an embargo window between them if
records cluster near the boundary. Materialise it as a new split rather than editing the
old one, then re-audit and confirm DD006 goes quiet.

If the task genuinely is i.i.d. over history, say so in the config - the point of the rule
is that the assumption is written down, not that it is enforced.

---

*Registry entry: `rules.py` `DD006`. Policy block: `policies.temporal_leakage`. Related:
[DD005](DD005-group-leakage.md), [DD007](DD007-target-leakage.md).*
