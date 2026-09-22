# DD007 - Target Leakage

| | |
| --- | --- |
| Category | `LEAKAGE` |
| Default severity | `CRITICAL` (deterministic) / `MEDIUM` (candidate) |
| Formal impact | `BLOCKING` / `POTENTIAL` |
| Evidence type | `DETERMINISTIC` / `HEURISTIC` |
| Applies to | tabular |
| Requires | a label column (declared or inferred), at least two splits |
| Detector | `dataset_doctor_audit/detectors/leakage.py::detect_target_leakage` |

## Definition

A feature column that *is* the label, is a deterministic transform of it, or separates it
suspiciously cleanly. The label must be unknown at prediction time; a column from which the
label can be read off makes the evaluation measure arithmetic, not learning.

## Why It Matters

This is the leakage class that survives every other check. The rows are unique, the entities
are disjoint, the timestamps are in order, the schema matches — and the answer is sitting in
the input matrix. A model trained on it reaches near-perfect test accuracy and then fails on
live data with no diagnosable error, because nothing in the pipeline was wrong except one
column's provenance.

## Detection

Two levels, and the distinction is the whole point of the rule.

**Level 1 - deterministic (`DETERMINISTIC`, `CRITICAL`, `FAIL`, `BLOCKING`).** The feature
matrix is every split stacked together minus the split column, the declared group columns and
the declared id columns; rows whose label is missing are dropped. For each remaining column,
in order:

1. `str(feature) == str(label)` row for row → *"identical to the label"*. String comparison
   on purpose: a label copied into a text column is still the label.
2. Both directions of the deduplicated value mapping are unique → *"a deterministic
   relabeling of the label"*. This is a bijection: knowing one value determines the other
   exactly.
3. Every feature value maps to exactly one label value, **and** the feature has ≤ 20 distinct
   values → *"a deterministic function of the label"*. The cap is the false-positive guard:
   without it any row-unique column (one value per row) trivially determines its own label
   and every dataset with an undeclared id column would read as blocking leakage.
4. Numeric feature vs binary label, ≥ 3 values, non-zero spread, `|pearson r| >= 0.999999` →
   *"perfectly linearly correlated with the label"*. This catches the scaled or negated copy
   (`score = 100 - target`) that steps 1-3 miss.

If level 1 fires for a column, level 2 is skipped for it — one column never produces two
findings.

**Level 2 - candidate (`HEURISTIC`, `MEDIUM`, `WARNING`, `POTENTIAL`, confidence `LOW`).**
Fires when `single_feature_auc >= 0.95` **or** `normalized_mutual_info >= 0.6`.

- AUC is the Mann-Whitney rank statistic `(Σ ranks(positive) - n₊(n₊+1)/2) / (n₊·n₋)` with
  average ranks for ties, against the highest-ordered class. It exists only for a numeric
  column (≥ 80% of values parse as numeric with > 2 distinct values); otherwise the evidence
  records `single_feature_auc: null` and the description says
  *"AUC=not defined for a non-numeric column"* rather than inventing a number.
- Normalised mutual information is `I(feature; label) / H(label)`, so it is bounded: 1.0 means
  the column removes all label uncertainty. For a numeric column it is computed over quantile
  bins (`min(10, max(2, √n))`); for a categorical one over raw values.
- Columns in a problem with more than 50 classes are skipped entirely (there is no meaningful
  rank AUC), which is reported by silence in the candidate list, not as a pass.

## False Positives

- **Level 2 is where the false positives live, by construction.** A biomarker that genuinely
  predicts the disease looks *identical* in the data to a column recorded after the disease
  was known. No statistic separates them; only the answer to "was this value knowable before
  the outcome?" does. That is why a level-2 finding is titled `TARGET_LEAKAGE_CANDIDATE`,
  carries `confidence: LOW`, and is `POTENTIAL` rather than `BLOCKING` — it cannot invalidate
  your evaluation on its own.
- **Level 1 can be correct and still not be a bug**: when the label was *defined* from that
  column (a `died_in_hospital` label built out of the discharge disposition code), the
  finding is accurate — it is telling you the feature must not be in the model matrix, which
  is exactly the fix.
- **The ≤ 20 value cap means a high-cardinality many-to-one column is not level 1.** A 500-value
  code column that pins the label exactly shows up as a level-2 candidate instead (its
  mutual information is ≈ 1.0). It is still reported; it is reported one notch softer.
- **A column that is near-perfectly correlated with a binary label by design** (a derived
  risk band, a threshold of the label's own units) fires level 1. That is leakage: the model
  is being handed the answer through arithmetic.

## Severity

| Relation found | Evidence | Severity / status | Formal impact |
| --- | --- | --- | --- |
| identical / bijective relabeling / ≤20-value deterministic function / `|r| ≥ 0.999999` | `DETERMINISTIC`, `HIGH` confidence | `CRITICAL` / `FAIL` | `BLOCKING` |
| `AUC ≥ 0.95` or normalised MI `≥ 0.6` | `HEURISTIC`, `LOW` confidence | `MEDIUM` / `WARNING` | `POTENTIAL` |

`BLOCKING` puts the verdict at `FORMAL_EVAL_INVALID`. `POTENTIAL` can move it only as far as
`FORMAL_EVAL_RISKY`. A single level-1 finding is enough to invalidate the run — which is why
the deterministic checks are exact arithmetic and never thresholded.

## Examples

From `dataset-doctor-audit demo` on the 316-sample `leaky_tabular` fixture
(`examples/RESULTS.md`, verdict `FORMAL_EVAL_INVALID`), one column per level:

```text
DD007-0001 MEDIUM WARNING (POTENTIAL)  TARGET_LEAKAGE_CANDIDATE: 'visit_lactate' predicts the label unusually well
           AUC=1.000, normalised mutual information=0.979, 316 rows
DD007-0002 CRITICAL FAIL (BLOCKING)    Target leakage: 'discharge_code' is a deterministic relabeling of the label
           one-to-one mapping over 2 value pairs, 316 rows
```

The verdict section names `DD007-0002` as one of three blocking findings, with no requirement
to read the body: `discharge_code` is a two-value string that maps one-to-one onto `target`.

`examples/leaky_patient_dataset` adds the third shape: `DD007-0003` names `collected_at`, the
same column [DD006](DD006-temporal-leakage.md) flags as the inverted time column. Two rules,
one mistake, seen from two sides.

Regression coverage: `tests/test_leakage.py::test_a_non_numeric_leak_candidate_reports_mutual_info_without_an_auc`
builds a categorical culprit (`ward`) and asserts `single_feature_auc` is `None`, that the
description contains *"not defined for a non-numeric column"* rather than the string `None`,
and that the finding stays `WARNING` / `POTENTIAL`.

## Remediation

Confirm from the data pipeline's provenance — not from the column name — when each suspicious
value becomes known. Then drop the column **and anything derived from it** from the model
matrix, and re-audit: the finding must disappear on its own, not because a threshold moved.

Dataset Doctor will not do this for you. It never edits your data or your splits.

To narrow the heuristic without losing the deterministic checks:

```yaml
policies:
  target_leakage:
    min_single_feature_auc: 0.99   # fewer candidates, same blocking behaviour
    # heuristic: false             # level 2 off entirely; level 1 still runs
```

Note two config realities. `policies.target_leakage.enabled: false` is **not** consulted by
this detector — only `suppress:` is enforced centrally, so silencing the rule takes
`suppress: [{rule: DD007, reason: "..."}]`. And a `severity:` override applies to the whole
rule, so it flattens the deliberate gap between the deterministic and the heuristic finding;
use it only when you have read every finding and know which level you are overriding.

---

*Registry entry: `rules.py` `DD007`. Policy block: `policies.target_leakage`. Related:
[DD005](DD005-group-leakage.md), [DD006](DD006-temporal-leakage.md),
[DD008](DD008-identifier-leakage.md), [DD009](DD009-label-conflict.md).*
