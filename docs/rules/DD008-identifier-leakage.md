# DD008 - Identifier / Feature Leakage

| | |
| --- | --- |
| Category | `LEAKAGE` |
| Default severity | `MEDIUM` (id-like name) / `LOW` (plain high-cardinality column) |
| Formal impact | `POTENTIAL` |
| Evidence type | `HEURISTIC` |
| Applies to | tabular |
| Requires | readable table data (no label needed) |
| Detector | `dataset_doctor/detectors/leakage.py::detect_identifier_leakage` |

## Definition

A column that is essentially a row identifier - one distinct value per row - still sitting in
the feature matrix. Primary keys, file paths, UUIDs and export row numbers are the usual
examples. They carry no generalisable structure, but a high-capacity model can use them to
memorise which row went with which label.

## Why It Matters

An identifier is the cleanest way to leak a label you did not know you leaked. Trees split on
`record_id` without hesitation; a model with enough capacity learns the mapping from key to
outcome and reports it as skill. It is also the most common accidental column in a CSV export,
because the export includes everything.

## Detection

Per split, for every column that is **not** the label, not the split column, and not already
declared under `id_columns` or `groups.columns`:

1. `unique_ratio = nunique(dropna=True) / rows`.
2. Fire when `unique_ratio >= threshold` (default `0.98`).
3. `_name_suggests_id` checks the lowercased column name for `id`, `uuid`, `guid`,
   `filename`, `file_name`, `path`, `row_no`, `rownum`, `index`. The name sets **severity
   only** (MEDIUM vs LOW) - a name that merely looks like an identifier can never fire the
   rule by itself. Cardinality is the evidence; naming is a hint.
4. The evidence records shape statistics and never a value: `non_null`, `min_length`,
   `max_length`, `all_digits` (> 95% of values digit-only), plus `dtype` and the measured
   ratio against the threshold. Reports must not become a copy of your data.
5. Findings are deduplicated by column, keeping the first occurrence in split-name order - so
   a key that is near-unique in all three splits is reported once, attributed to `test`.

## False Positives

This rule fires on the widest, softest signal in the whole rule set, and says so:
`HEURISTIC` / `WARNING` / `POTENTIAL` / confidence `MEDIUM`. It cannot block an experiment.

- **Free text, timestamps and measurements are near-unique and legitimate.** A `notes` column,
  a `collected_at` with millisecond precision, or a float reading that never repeats, all
  clear 0.98 trivially. The limitation is printed on every finding: *"High cardinality alone
  is not leakage."*
- **Small splits invert the metric.** `unique_ratio` is computed per split, so a 12-row
  validation split makes almost any column near-unique. On a 10-row split the rule is noise;
  on a 100,000-row one it is meaningful.
- **Genuine high-cardinality features** - a `city` column where every town appears once, a
  product SKU that is legitimately predictive - are indistinguishable in the data from a key.
- **A declared key is not a finding.** Declaring the column under `id_columns` moves it out of
  the feature matrix for every rule that compares features, which is the designed answer: the
  tool stops guessing whether `record_id` is identity or signal.

## Severity

| Column | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| name matches an identifier marker | `MEDIUM` | `WARNING` | `POTENTIAL` |
| high cardinality only | `LOW` | `WARNING` | `POTENTIAL` |

Never `CRITICAL`, never `BLOCKING`: an identifier in the matrix is a strong prior that
something is wrong, not proof that the label is recoverable from it.

## Examples

The demo fixture ships with `id_columns: [record_id]`, and `dataset_doctor/demo.py` states
that this is why DD008 stays quiet there - a declared key is treated as identity. Remove that
one line and the same data produces a finding, measured from a run of this exact setup:

```bash
cp -r <demo>/leaky_tabular undeclared_id && sed -i '/id_columns/d' undeclared_id/dataset-doctor.yaml
dataset-doctor audit ./undeclared_id
```

```text
DD008-0001 MEDIUM WARNING (POTENTIAL) HEURISTIC confidence=MEDIUM
IDENTIFIER_FEATURE_CANDIDATE: 'record_id' is near-unique in 'test'
'record_id' takes 86 distinct values across 86 rows (unique ratio 1.000).

{ "column": "record_id", "unique_ratio": 1.0, "threshold": 0.98,
  "name_suggests_identifier": true, "dtype": "object",
  "example_shape": { "non_null": 86, "min_length": 7, "max_length": 8, "all_digits": false } }
```

Note what is *not* there: no identifier values. Enough shape to confirm the diagnosis
(7-8 character non-numeric strings, one per row), no payload.

No shipped example triggers this rule - every tabular fixture declares its key - so the
coverage note in `docs/PROJECT_STATE.md` records DD008 as verified by this style of manual
check rather than by a fixture.

## Remediation

Either the column is identity, or it is a feature.

- If it is identity: declare it. `id_columns: [record_id]` in `dataset-doctor.yaml` is the
  durable form; `dataset-doctor audit --id-column record_id` applies the same declaration to
  one run without writing any file. Either way the finding goes away because the tool stops
  treating it as signal - the data is untouched.
- If it might be a feature: check whether its value was knowable before the outcome, and
  whether it repeats across entities. A column that is genuinely informative at row level in
  a tabular dataset is rare enough to be worth a second look.

Adjust the bar rather than silencing the rule if your data is naturally high-cardinality:

```yaml
policies:
  identifier_leakage:
    unique_ratio: 0.999
```

`policies.identifier_leakage.enabled: false` is not read by this detector; to turn the rule
off outright, use `suppress: [{rule: DD008, reason: "..."}]`, which is recorded in the report.

---

*Registry entry: `rules.py` `DD008`. Policy block: `policies.identifier_leakage`. Related:
[DD003](DD003-exact-duplicate.md), [DD005](DD005-group-leakage.md),
[DD007](DD007-target-leakage.md), [DD021](DD021-pii-exposure.md).*
