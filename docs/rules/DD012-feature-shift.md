# DD012 - Feature / Distribution Shift

| | |
| --- | --- |
| Category | `DISTRIBUTION` |
| Default severity | `HIGH` ≥ 0.8 · `MEDIUM` ≥ 0.5 · `LOW` otherwise (largest effect in the pair) |
| Formal impact | `POTENTIAL` |
| Evidence type | `STATISTICAL` |
| Applies to | tabular (images are [DD017](DD017-image-property-shift.md)) |
| Requires | at least two non-empty splits; feature columns that survive label/id/split removal |
| Detector | `dataset_doctor/detectors/distribution.py::detect_feature_shift` |

## Definition

The input distribution of the evaluation split differs from the training split: same columns,
different contents. One finding per comparison (`train` vs `test`, `train` vs `val`, ...),
listing the columns that moved and how far.

## Why It Matters

Covariate shift is the ordinary, non-scandalous version of a broken evaluation, and it is the
one most often mistaken for a leak. If test BMI sits two units above train BMI, the reported
accuracy is a statement about a population the model was not fitted on - which may be exactly
the point (a harder benchmark, a prospective cohort) or an artefact of collection. **The data
cannot tell which**, so this rule deliberately cannot produce an invalid verdict; see
`docs/METHODOLOGY.md`.

## Detection

Reference split = the recognised `train` split, else the first non-empty one. Every other
non-empty split is compared against it. For each feature column (label, `id_columns`,
`groups.columns` and the split column already removed):

**Numeric** (needs ≥ 5 non-null values on each side):

| Statistic | Role |
| --- | --- |
| `std_mean_diff` = (mean_ref − mean_target) / pooled SD | trigger (`abs >= min_std_mean_diff`, default **0.2**) |
| PSI over 10 shared quantile bins | trigger (`>= min_psi`, default **0.2**), *only where usable* - see below |
| KS statistic + p-value, then Benjamini-Hochberg over the columns that crossed a trigger | evidence, never a trigger |
| Wasserstein and normalised Wasserstein (÷ pooled p95−p5) | supporting effect size |

**Categorical:** total-variation distance on the union of levels, trigger `tv >= min_smd / 2`
(so a 10-point mix change on a binary column reads at the same magnitude as a 0.2 SMD), with
Jensen-Shannon as support and `unseen_in_train` counted. To stay on one severity scale the row
reports `abs_smd = 2 * tv` and carries **no p-value** - which is stated in the finding rather
than left as a blank. A column with more than 200 distinct values is skipped as
identifier-like; that question belongs to [DD008](DD008-identifier-leakage.md).

**The PSI noise floor.** With B quantile bins and no real shift, PSI still averages about
`(B − 1) / n_target`, because every near-empty bin contributes `(1/n)·ln((1/n)/ε)`. On a 30-row
split that is 0.3 - above the conventional 0.2 cutoff, so PSI would "detect" shift in a
perfectly matched pair. The rule therefore only lets PSI trigger when
`(PSI_BINS - 1) / n_target < min_psi`; each row records `psi_trigger_usable`, and the value is
still reported either way. The threshold block in the evidence prints the computed floor.

**Multiplicity.** Benjamini-Hochberg is applied across the numeric columns that crossed a
trigger at `fdr_alpha` (default 0.05), and each row gets `fdr_significant` plus
`adjusted_pvalue`. The p-values are read back out of the *sorted* evidence rows, so a flag
cannot be attached to the wrong column -
`tests/test_examples.py::test_an_fdr_flag_never_lands_on_another_columns_evidence` pins that.

## False Positives

- **Significance is not the trigger, on purpose.** With 100k-row splits a 0.01 SMD is
  "significant" and meaningless. Severity comes from effect size alone; the p-value is printed
  so you can see whether the test was under- or over-powered.
- **Intentional shift.** A dataset that deliberately holds out a harder population should fire
  this rule; the correct response is to write that down, not to make the finding disappear.
- **Small evaluation splits** produce large PSI and KS noise. `psi_trigger_usable: false` is
  the rule admitting it cannot measure this; `min_std_mean_diff` still works at n=10 but with
  wide confidence.
- **Joint shift is invisible here.** Every test is per-column: a covariance change with
  unchanged marginals passes. The limitation is printed on the finding, because a clean DD012
  is not proof of a stable joint distribution.

## Severity

Rated on the largest `abs_smd` in the comparison, then carried by the whole finding:

| Largest \|SMD\| | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| ≥ 0.8 | `HIGH` | `WARNING` | `POTENTIAL` |
| ≥ 0.5 | `MEDIUM` | `WARNING` | `POTENTIAL` |
| below 0.5 (triggered via PSI or a categorical TV) | `LOW` | `WARNING` | `POTENTIAL` |

`POTENTIAL` always. A drift finding can raise the verdict to `FORMAL_EVAL_RISKY` and can fail
a `--ci` gate, but no amount of distribution shift makes a test set *invalid* in the sense
this tool reserves for contamination - one of the three statements
[`docs/METHODOLOGY.md`](../METHODOLOGY.md) publishes verbatim.

## Examples

`examples/shifted_tabular` (260 samples) is the control for this rule: the test population was
rebuilt to be measurably different, with **no leakage planted**. Measured:

```text
DD012-0001 HIGH WARNING (POTENTIAL) STATISTICAL confidence=MEDIUM
Feature distribution shift: train vs test (4 column(s))
4 of 5 feature column(s) exceed the shift thresholds (|std mean diff| >= 0.2, or PSI >= 0.2 on
splits large enough for PSI to clear its own noise floor); largest effect |SMD| = 1.36.
Benjamini-Hochberg across the 3 numeric column(s) that crossed a threshold at FDR 0.05;
categorical rows report an effect size only.

column          kind          abs_smd   ks_pvalue   adj_p     fdr_significant
age             numeric       1.3592    1.8e-16     0.0       True
bmi             numeric       1.1652    3.3e-11     0.0       True
sex             categorical   0.3367    -           -         None
visit_lactate   numeric       0.1252    0.7647      0.764726  False
```

Read that table as a set of four different statements: two columns moved a lot and the test is
powered enough to say so; one categorical column changed its mix (`abs_smd` here is `2 × TV`,
no p-value exists); and `visit_lactate` crossed on PSI alone with `|SMD| = 0.13` and a
non-significant KS test - a real shape change, an unreliable location change, and the reason
the trigger is an *or*.

The fixture's verdict is `FORMAL_EVAL_RISKY`, and `exit_code()` with default settings is **0** -
asserted by
`tests/test_examples.py::test_distribution_shift_is_reported_as_a_risk_and_not_as_a_blocked_evaluation`.

Other coverage: `test_test09_a_shifted_feature_is_measured_with_effect_size` (a planted BMI
shift must be named with `|SMD| > 1.0`) and `test_test10_identical_distributions_are_not_flagged_in_volume`
(120 vs 60 rows from the same generator must produce nothing at `MEDIUM` or worse - the
no-news test that keeps this rule trustworthy).

## Remediation

Decide whether the shift is the design or a defect; the tool cannot.

- If intentional: document it, and choose an evaluation that matches the claim (per-cohort
  metrics, a test set from the deployment population).
- If a collection artefact: find the stage that changed (a new device, a new site, a changed
  assay) and rebuild the split from before/after consistently.
- If it is real and unavoidable: reweight or accept it, and report the shifted columns next to
  the metric.

Suppressing DD012 is available (`suppress: [{rule: DD012, reason: "..."}]`) but the honest
config change is usually per-rule thresholds, since what counts as "moved" depends on the
population:

```yaml
policies:
  feature_shift:
    min_std_mean_diff: 0.3
    min_psi: 0.25
    fdr_alpha: 0.10
    enabled: true      # honoured by this rule; false => NOT_RUN, visible in coverage
```

---

*Registry entry: `rules.py` `DD012`. Policy block: `policies.feature_shift`. Related:
[DD013](DD013-label-shift.md), [DD015](DD015-missingness-shift.md),
[DD014](DD014-schema-drift.md), [DD017](DD017-image-property-shift.md).*
