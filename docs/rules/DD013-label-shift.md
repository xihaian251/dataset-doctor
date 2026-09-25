# DD013 - Label Distribution Shift

| | |
| --- | --- |
| Category | `DISTRIBUTION` |
| Default severity | `HIGH` at TV ≥ 0.30 · `MEDIUM` ≥ 0.15 · `LOW` otherwise |
| Formal impact | `POTENTIAL` |
| Evidence type | `STATISTICAL` |
| Applies to | tabular, image |
| Requires | at least two non-empty splits, labels present in both compared splits |
| Detector | `dataset_doctor_audit/detectors/distribution.py::detect_label_shift` |

## Definition

P(y) differs between the reference split and another split: the class mix of the test set is
not the class mix the model was fitted on. This is shift in the *label*, which changes what a
headline accuracy number means even when the model and the features are untouched.

## Why It Matters

Accuracy is a weighted average over classes, and the weights are the class shares. Change the
prevalence and you change the metric with a fixed confusion matrix - so two runs on differently
balanced test sets are answering different questions, which is exactly how "our score went
down" turns into a phantom model regression. Unlike [DD009](DD009-label-conflict.md), nothing
here is wrong with the data; what needs defending is the comparison.

## Detection

Same reference/target selection as [DD012](DD012-feature-shift.md): the recognised `train`
split (or the first non-empty one) compared against every other non-empty split.

1. Count labels per split. A table supplies them from the label column (`dropna`, stringified)
   when the split has a frame *and* that frame carries the column; otherwise they come from the
   manifest's labelled records - which is the image path, since a folder layout has no table at
   all. That fallback is the only route labels take for `split/class/*.png` datasets, so when it
   sat behind `if frame is None or frame.empty: return {}` the rule answered `PASS` for every image
   dataset it was pointed at (`docs/PROJECT_STATE.md` section 4, defect 9).
2. Union the supports so a class present only in one split is not silently dropped: its share
   on the missing side is 0, and it appears in `largest_movers`. `common_support_classes` in the
   evidence counts the labels present on *both* sides; when it is 0 the description says so,
   because the number below is then comparing two vocabularies rather than two proportions.
3. `tv = ½ Σ |p_i − q_i|` (total variation, bounded [0, 1]);
   `js = √(JSD)` reported as a distance for the same reason - it is the more readable of the two
   when one class has vanished.
4. Fire when `tv >= min_tv_distance` (default **0.05**).
5. Rank classes by absolute share change, capped at 20, and report each side's share.

A split with no labels at all is skipped (`continue`) rather than reported as a shift to a
point mass - the missing labels belong to [DD010](DD010-missing-labels.md).

## False Positives

- **Two spellings of one class reach total variation 1.000.** Measured on the official UCI Adult
  files: `adult.data` writes `<=50K`, `adult.test` writes `<=50K.`, so the two supports are
  disjoint, `common_support_classes` is 0, and the rule reports `tv 1.000` / `HIGH` - while the
  same two splits, after the dot is removed from the labels, differ by `tv 0.0046` and the rule
  passes. That is why the finding states the arithmetic it is doing: a re-encoding and a
  genuinely disjoint class set deserve the same number and not the same interpretation. The
  categories that appear on one side only are named by [DD014](DD014-schema-drift.md).
- **A normal-only training split fires the rule by construction.** Anomaly detection datasets
  keep the defective cases in test and train on defect-free samples, so train is a point mass and
  test is a mix - the upper part of the scale is the *design*. Measured at 0.759 and 0.742 on the
  two official MVTec AD categories that the fourth real-world acceptance audited, both
  `HIGH`/`WARNING`/`POTENTIAL`. Read it as a statement about the comparison, not a fault: for this
  protocol the right headline is per-class or image-level AUROC on the enriched test set, and the
  finding is what tells a reader importing a tabular habit that the shares are not comparable.
- **Enriched test sets are a design choice.** Balancing evaluation on rare classes is standard
  practice, and this rule will fire every time. The limitation is printed on the finding:
  *"A test set deliberately enriched for rare cases is a design choice, not an error. Report
  it as the evaluation protocol instead of 'fixing' it."*
- **A small test split has a coarse TV floor.** With 20 test rows, one extra positive moves
  the share by 0.05 and trips the default threshold. `test_total` is in the evidence for
  exactly this judgement.
- **`train_total` / `test_total` are named after the usual case.** When the reference split is
  not literally `train` (a train-only naming, or a `val` reference), those two keys still mean
  *reference* and *target* counts. The finding's `source_split` / `target_split` are
  authoritative.

## Severity

| Total variation | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| ≥ 0.30 | `HIGH` | `WARNING` | `POTENTIAL` |
| ≥ 0.15 | `MEDIUM` | `WARNING` | `POTENTIAL` |
| ≥ 0.05 | `LOW` | `WARNING` | `POTENTIAL` |

`POTENTIAL` in every case, by the same reasoning as DD012 and one of the three statements this
tool publishes verbatim: *distribution shift does not automatically mean invalid evaluation*.
A prevalence change can push the verdict to `FORMAL_EVAL_RISKY`; only contamination
(`BLOCKING`) can invalidate it.

## Examples

`examples/shifted_tabular` plants covariate **and** label shift with no leakage, so it produces
the pair of findings that most often get confused for one problem. Measured from the same run
quoted in [DD012](DD012-feature-shift.md):

```text
DD013-0001 HIGH WARNING (POTENTIAL) STATISTICAL confidence=HIGH
Label distribution shift: train vs test
P(target) differs between train and test: total variation 0.362, Jensen-Shannon distance 0.263.

class  train_share  test_share
1        0.4050      0.7667
0        0.5950      0.2333
train_total 200   test_total 60   threshold 0.05
```

Class `1` goes from 40.5% of training to 76.7% of the test set - a TV of 0.36, past the `HIGH`
line. The finding is not saying this is a mistake; it is saying that an accuracy number from
this test set is not comparable to one from a 40/60 mix, and that the report should carry both
shares.

Together with DD012-0001 this fixture is why the verdict is `FORMAL_EVAL_RISKY` rather than
`FORMAL_EVAL_SAFE`, and why `exit_code()` is still 0 without `--ci`.

The same rule on a folder-layout image dataset, `examples/corrupt_image`, measured from the
images' directory names with no table anywhere in the dataset:

```text
DD013-0001 HIGH WARNING (POTENTIAL) STATISTICAL confidence=HIGH
Label distribution shift: train vs test
P(y) differs between train and test: total variation 0.400, Jensen-Shannon distance 0.405.

class  train_share  test_share
scratch    0.6000      1.0
bruise     0.4000      0.0
train_total 30   test_total 6   common_support_classes 1   threshold 0.05
```

`bruise` disappears from the test split, which is the case the union support exists for: its
share on that side is 0, not absent. `examples/safe_image`, whose two splits carry the same
proportions, stays `FORMAL_EVAL_SAFE` with DD013 `PASS` - the check that the image path is a
measurement and not just a reason to fire.

## Remediation

None is owed - the dataset is not broken.

1. Choose the test mix that matches the claim you intend to make, and state it.
2. Report prevalence-insensitive metrics (per-class recall, macro-F1, PR-AUC) alongside any
   weighted number.
3. If the shift is a collection artefact, rebuild the split with the same sampler as train -
   then re-audit and confirm TV falls.
4. Intentional? Then `policies.label_shift: {min_tv_distance: 0.15}` moves the noise floor, or
   `suppress: [{rule: DD013, reason: "test set is deliberately enriched 3:1 on class 1"}]`
   records it as protocol. `enabled: false` is honoured and shows up as `NOT_RUN` in the
   coverage block, which is better than silence.

---

*Registry entry: `rules.py` `DD013`. Policy block: `policies.label_shift` (`min_tv_distance`,
`enabled`). Related: [DD011](DD011-class-imbalance.md), [DD012](DD012-feature-shift.md),
[DD010](DD010-missing-labels.md).*
