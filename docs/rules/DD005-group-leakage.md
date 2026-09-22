# DD005 - Group / Entity Leakage

| | |
| --- | --- |
| Category | `LEAKAGE` |
| Default severity | `CRITICAL` (train/test) / `HIGH` (other boundaries) |
| Formal impact | `BLOCKING` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular, image |
| Requires | `groups.columns` or `groups.entity_column`, and at least two splits |
| Detector | `dataset_doctor/detectors/leakage.py::detect_group_leakage` |

## Definition

The same real-world entity - one patient, one user, one device, one session, one source
video - contributing rows or images to more than one split. Duplication is about content;
this is about *identity*. Two ECG strips from the same patient look nothing alike and are
the same leak.

## Why It Matters

Almost every deployment claim is "this generalises to patients / users / devices we have
never seen". A per-row split cannot test that, because the model met the entity during
training. In clinical and sensor data this is the dominant failure mode, and it is
completely invisible to duplicate detection: the rows differ in every cell except the one
that names who they came from.

Repeated-measures data makes it worse, not better. A patient with 40 visits and 1 visit
contribute very different amounts of information, and a random split hands both sides of
the boundary to the same person.

## Detection

1. No group columns declared → `NotApplicable` and the rule reports `NOT_RUN`. Not a
   PASS, and the coverage section says so.
2. Declared columns absent from the data → `InsufficientEvidence` with the sentence
   *"This is not a PASS."*
3. For each available column, build `entity -> {split: row_count}` across all splits,
   skipping null/empty values (they identify nobody).
4. Entities present in more than one split are cross-split. One finding per split pair,
   `train/test` first.
5. `affected_count` is the total number of rows on both sides - not the number of
   entities - because the rows are what the model saw. The evidence carries the top 20
   entities by row count, with the per-split breakdown:
   `{"group_column": "patient_id", "entities": 12, "examples": [{"entity": "p07", "splits": {"test": 3, "train": 9}}]}`.
6. If nothing crosses the boundary but the column is near-unique overall (unique ratio
   > 0.98), emit a `LOW` / `FormalImpact.NONE` advisory instead - see False Positives.

## False Positives

- **A column named `patient_id` that is actually a per-row primary key** gives one group
  per sample: it can hide nothing, and DD005 correctly finds no leakage. The `LOW`
  advisory exists because the *declaration* is then probably wrong - you named a row id
  where you meant an entity id, and your split is still ungrouped. It is `NONE`, not
  `POTENTIAL`, so it cannot drag a clean dataset's verdict down. Pinned by
  `tests/test_leakage.py::test_a_row_unique_group_column_is_an_advisory_not_a_leakage_finding`.
- **A column that repeats by design as a grouping factor** - hospital site, machine,
  batch - is not an entity whose reuse invalidates the test. If the experiment claims
  site-level generalisation it does; if it claims within-site prediction it does not.
  Declare the column the experiment actually depends on.
- **Different entities on either side are not flagged.** Spec TEST 6:
  `test_test06_disjoint_entities_are_not_flagged` asserts `DD005 == []` and
  `FORMAL_EVAL_SAFE` for a cohort where `patient_id` repeats *within* each split but never
  across the boundary. This is the single most important non-firing case in the tool.
- **Un-grouped by default.** With no declaration the rule does not guess an entity column,
  because guessing here would either stay silent or accuse the wrong column.

## Severity

| Boundary | Status | Severity | Formal impact |
| --- | --- | --- | --- |
| train / test | `FAIL` | `CRITICAL` | `BLOCKING` |
| train / val, val / test | `FAIL` | `HIGH` | `BLOCKING` |

`BLOCKING` either way: a val split contaminated by test entities still corrupts model
selection, which propagates into the reported test number without ever crossing the
train/test line.

One consequence of ranking by *name* rather than by inferred role: a holdout called
`blind_eval` never produces the `CRITICAL` pair, only `HIGH`. The finding and its formal
impact are identical; rename the split to `test` if you want the ranking to say so.

## Examples

Measured from `dataset-doctor demo`:

```text
CRITICAL DD005-0001 Entity leakage on 'patient_id': test / train (66 samples, test)
```

From `examples/RESULTS.md`, `leaky_patient_dataset` (309 samples, one cohort, three
splits) produces three DD005 findings at once:

```text
DD005-0001 CRITICAL FAIL (BLOCKING) - test / train
DD005-0002 HIGH     FAIL (BLOCKING) - test / val
DD005-0003 HIGH     FAIL (BLOCKING) - train / val
```

and `unsafe_group_leakage` (270 samples) is the isolation case: shared patients with
**no** duplicate rows, so DD003 stays silent and DD005 is the only thing that speaks -
`tests/test_examples.py::test_shared_entities_are_found_without_any_row_being_a_duplicate`.

## Remediation

Re-split with the entity as the unit, into a **new** directory:

```bash
dataset-doctor split ./cohort.csv --group-by patient_id --output ./cohort_grouped
```

The command refuses to overwrite a non-empty target, records the seed and the assignment
manifest, and leaves the source untouched. Then re-audit: the finding must disappear
rather than be explained away. `tests/test_splitting.py::test_the_grouped_output_of_the_same_data_passes_the_leakage_rules`
asserts the fix closes the leak, and
`test_a_row_wise_split_of_the_same_data_does_leak_and_the_tool_says_so` asserts the naive
alternative still reports it.

---

*Registry entry: `rules.py` `DD005`. Policy block: `policies.group_leakage`. Related:
[DD003](DD003-exact-duplicate.md), [DD006](DD006-temporal-leakage.md),
[DD008](DD008-identifier-leakage.md).*
