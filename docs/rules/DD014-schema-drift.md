# DD014 - Schema Drift

| | |
| --- | --- |
| Category | `SCHEMA` |
| Default severity | `HIGH` (presence, dtype) · `MEDIUM` (unseen categories) |
| Formal impact | `BLOCKING` / `POTENTIAL` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular |
| Requires | at least two non-empty splits of readable data |
| Detector | `dataset_doctor/detectors/structural.py::detect_schema_drift` |

## Definition

The splits are not the same table. Three distinct failures share this rule: a column present in
one split and absent in another, a column the loader parses as a different type per split, and
a categorical value that appears in evaluation but never in training.

## Why It Matters

This is the class of problem that presents as a model bug. A silently dropped column changes
the feature matrix without changing any code; a column parsed as string in test lands every
value in the encoder's unknown bucket; an unseen category is predicted by a fallback rather
than by training. None of these corrupt the *labels*, but all of them make the number
meaningless, and they are invisible in a notebook that only prints accuracy.

## Detection

Presence and dtype compare every non-empty split against `sorted(frames)[0]` - the
**alphabetically** first one, which is usually `test`, not `train`. That is a deliberate
simplicity: a schema mismatch is symmetric, and the finding names both sides. Category drift
instead uses the role-aware reference (the recognised `train` split, falling back to the first
split) against each test/val split, because "unseen" only has a direction.

1. **Presence** (`kind: presence`) - columns in the reference missing from the other split
   (`missing_in_target`) and columns only in the other split (`extra_in_target`). Both lists
   are named in the description, capped at 10 entries each in prose and complete in the
   evidence.
2. **dtype** (`kind: dtype`) - per column, the loader-inferred type per
   (`describe_dtype`: `int`, `float`, `bool`, `string`, `string:null-like`, `datetime`,
   `category`, `bytes`). Any column whose set of per-split types has more than one member is a
   conflict; up to 50 columns are carried in the evidence and 10 in the description.
3. **Unseen categories** (`kind: category_levels`) - for each non-numeric column shared by the
   train-role split and an evaluation split, values present in the evaluation split and absent
   from train. Up to 20 values per column.

**Identifier guard.** A near-unique column is *expected* to be unseen in test - flagging it
would bury the real categorical drift in a wall of keys. A column is skipped when it is
declared under `id_columns`/`groups.columns`, or when it has more than 90% distinct values in
a split of at least 10 rows (`IDENTIFIER_UNIQUE_RATIO = 0.9`,
`MIN_ROWS_FOR_UNIQUE_RATIO = 10`). The skip is not silent: every finding lists
`identifier_columns_skipped`.

## False Positives

- **dtype is inference, not a stored schema.** A column of `40`, `41`, `42` is `int` and a
  column with one `40.5` becomes `float` - a real difference in what the loader hands your
  encoder, but not evidence anyone wrote two schemas. The limitation is printed on the finding.
- **`string` vs `int` on the same numbers** happens when one split has an empty cell: pandas
  keeps an all-numeric column with a hole as `object`. Fix the missing value or parse
  explicitly; do not suppress.
- **A small evaluation split invents unseen categories.** With 10 test rows, one rare level you
  never sampled in train is arithmetic, not drift. The counts per split are in the finding.
- **Presence is reported once per pair.** A column renamed in test shows as one missing *and*
  one extra - that is two columns in the description and one real edit.

## Severity

| Kind | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| presence mismatch | `HIGH` | `FAIL` | `BLOCKING` |
| dtype mismatch | `HIGH` | `FAIL` | `BLOCKING` |
| unseen categories | `MEDIUM` | `WARNING` | `POTENTIAL` |

The first two are blocking for the same reason a leak is: the thing being scored is not the
thing being fitted, so no number from that run can be transferred. They are not `CRITICAL`
because the defect is structural rather than a contamination of held-out answers. Unseen
categories are `POTENTIAL` - a fallback bucket is a real loss of information, and usually a
known cost of a particular encoder.

## Examples

A 90-row synthetic table built while writing this document: train has `age` as integers, test
has one `40.5`, and test contains a site level that never appears in train.

```text
DD014-0001 HIGH FAIL (BLOCKING) DETERMINISTIC
Column dtype differs across splits (1 column(s))
age: test=float, train=int
{ "columns": [ { "column": "age", "types": { "test": "float", "train": "int" } } ] }

DD014-0002 MEDIUM WARNING (POTENTIAL) DETERMINISTIC
Unseen categories in test
1 category value(s) appear in test but never in train across 1 column(s).
{ "columns": { "site": ["C"] }, "identifier_columns_skipped": ["record_id"] }
```

Note the second line's `identifier_columns_skipped`: `record_id` is 100% distinct in both
splits and would otherwise have produced a 30-value "unseen category" finding.

Renaming a column instead produces the presence shape, which also shows the alphabetical
reference in the title:

```text
DD014-0001 HIGH FAIL (BLOCKING) Schema mismatch between test and train
1 column(s) present in test but not train: gender; 1 column(s) only in train: sex.
{ "reference": "test", "missing_in_target": ["gender"], "extra_in_target": ["sex"] }
```

The two lists are the same edit seen twice, and reading them side by side is how a rename is
recognised rather than assumed.

## Remediation

Rebuild the splits from one schema: a shared loader with an explicit dtype map, or an
explicit `splits:` block over files that were written by the same export. Then re-audit and
require the rule to go quiet - a `BLOCKING` DD014 finding is not something to gate around.

For unseen categories specifically: either add the missing levels to training (a broader
sample), or make the encoder's handling explicit and say so in the write-up. Truncating the
test set to levels train has seen changes the population being scored, which is a different
- and usually worse - mistake.

Config surface, precisely:

```yaml
policies:
  schema_drift:
    enabled: false       # whole rule -> NOT_RUN, visible in the coverage block
  category_drift:
    enabled: false       # only the unseen-level check is skipped; presence and dtype still run
```

A `severity:` override on either block applies per *rule*, so it flattens the
`HIGH`/`MEDIUM` gap between the structural kinds and the category kind at once - use
`suppress:` with a reason when only the category noise is the problem.

---

*Registry entry: `rules.py` `DD014`. Policy blocks: `policies.schema_drift` (the rule, and
where `severity` overrides land) and `policies.category_drift` (the unseen-level check only).
Related: [DD002](DD002-split-integrity.md), [DD012](DD012-feature-shift.md),
[DD008](DD008-identifier-leakage.md).*
