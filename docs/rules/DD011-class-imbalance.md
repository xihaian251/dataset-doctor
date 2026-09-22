# DD011 - Class Imbalance

| | |
| --- | --- |
| Category | `DISTRIBUTION` |
| Default severity | `LOW` (`HIGH` for a single class, `MEDIUM` for a vanishing minority) |
| Formal impact | `POTENTIAL` |
| Evidence type | `STATISTICAL` |
| Applies to | tabular, image |
| Requires | at least one discovered label |
| Detector | `dataset_doctor/detectors/distribution.py::detect_class_imbalance` |

## Definition

How unequal the class frequencies are - reported as effect sizes (ratio, minority share,
entropy, effective class count) rather than as a verdict about your model.

## Why It Matters

Imbalance is not corruption; it is a property of the world, and fraud detection and rare
disease are imbalance by design. It belongs in a *leakage* audit for one reason: on an
imbalanced mix the headline metric is nearly constant no matter how the minority class
performs, so "99% accuracy" can mean "the model never found the thing you care about". The
rule exists to make the number you report defensible, not to make your dataset look tidy.

## Detection

From the identity block's pooled `class_counts`, with the `<unlabeled>` bucket removed (a
missing label is not a class - see [DD010](DD010-missing-labels.md)):

- `imbalance_ratio = max(counts) / min(counts)`
- `minority_share = min(counts) / sum(counts)`
- `entropy_bits = H(counts)` in base 2; `effective_class_count = 2 ** H`, so 1200:1 on two
  classes reports `1.01 of 2` - one and a quarter classes' worth of information.

Fire when `imbalance_ratio > max_imbalance_ratio` (default **20.0**) **or**
`minority_share < min_minority_ratio` (default **0.02**). Both branches are reported, so you
can see which one tripped. Evidence carries the sorted class counts, the four statistics, the
five smallest classes, and the thresholds that were in force, so a re-run with different
settings cannot be mistaken for the same measurement.

Special cases:

- **fewer than two classes** (after dropping unlabelled) → `HIGH` / `WARNING` / `POTENTIAL`,
  titled *"Single-class label distribution"*, because accuracy on it equals the majority rate
  by construction.
- **no labels at all** → `InsufficientEvidence`, worded deliberately: *"no labels were
  discovered, so class balance cannot be measured. This is not a PASS."*
- **`policies.class_imbalance.enabled: false`** → `NOT_RUN` with that reason. This rule does
  honour `enabled`, unlike the leakage rules.

## False Positives

By construction this rule has no false positives about the arithmetic - only about relevance.
A long-tail catalog, a fraud set, a rare-disease cohort are all "failing" DD011 on purpose.
The recommended action says so:

> Report per-class and balanced metrics; suppress this rule with a reason if the long tail is
> the point of the dataset.

The other trap is pooling. Counts merge every split, so a dataset that is 50/50 in train and
1/99 in test reads as balanced here - that is [DD013](DD013-label-shift.md)'s job, and the
finding carries the limitation line *"Counts pool every split together; per-split class
coverage is reported by DD013."*

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| 1 distinct class | `HIGH` | `WARNING` | `POTENTIAL` |
| fired and `minority_share < 0.002` (i.e. < 1/10 of `min_minority_ratio`) | `MEDIUM` | `WARNING` | `POTENTIAL` |
| fired, minority share ≥ 0.002 | `LOW` | `WARNING` | `POTENTIAL` |

Never `BLOCKING`. Imbalanced data can support a valid evaluation with the right metric; the
rule's `POTENTIAL` impact is what moves a verdict to `FORMAL_EVAL_RISKY`, never to
`FORMAL_EVAL_INVALID`.

## Examples

Two synthetic tabular sets audited while writing this document - one minority row in a
361-row dataset, then in a 1201-row dataset - to show the `min_share / 10` boundary:

```text
DD011-0001 LOW    WARNING (POTENTIAL) Class imbalance: 360.0:1 (majority to minority)
2 classes over 361 labelled samples; largest/minority = 360.0, minority share 0.0028,
effective class count 1.02 of 2.

DD011-0001 MEDIUM WARNING (POTENTIAL) Class imbalance: 1,200.0:1 (majority to minority)
2 classes over 1201 labelled samples; largest/minority = 1200.0, minority share 0.0008,
effective class count 1.01 of 2.
```

A single minority row is a data-quality nuisance at 361 rows and a metric-defining problem at
1201, because the *share* is what determines whether a model can see the class at all - which
is why severity keys off `minority_share` and not off the ratio.

The image anomaly run in [DD010](DD010-missing-labels.md) also shows the two rules seeing one
situation from different angles: 63 near-unique "classes" produced
`DD011-0001 LOW ... Class imbalance: 2.0:1`, a true statement about a meaningless label
column. No shipped example fixture trips DD011 above `LOW`, so this rule has no dedicated
regression test either; see the coverage note in `docs/PROJECT_STATE.md`.

## Remediation

Nothing to remediate in the data - usually.

1. Report per-class precision/recall, macro-F1, PR-AUC, or a balanced accuracy, and state the
   minority count next to the headline number.
2. If the sample size genuinely cannot support the minority class, say so in the write-up;
   resampling cannot invent information that isn't in the file.
3. If the tail is intentional, suppress with a reason so the audit stays readable:

```yaml
suppress:
  - rule: DD011
    reason: "long-tail product catalog; imbalance is the subject of the dataset"
```

---

*Registry entry: `rules.py` `DD011`. Policy block: `policies.class_imbalance`
(`max_imbalance_ratio`, `min_minority_ratio`, `enabled`). Related:
[DD010](DD010-missing-labels.md), [DD012](DD012-feature-shift.md),
[DD013](DD013-label-shift.md).*
