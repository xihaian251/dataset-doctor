# DD010 - Missing Labels

| | |
| --- | --- |
| Category | `LABEL` |
| Default severity | `HIGH` in evaluation · `MEDIUM` > 2% · `LOW` otherwise |
| Formal impact | `POTENTIAL` / `NONE` |
| Evidence type | `DETERMINISTIC` (unlabelled) · `HEURISTIC` (cardinality anomaly) |
| Applies to | tabular, image |
| Requires | a label column or folder layout; `labels.source: none` opts out |
| Detector | `dataset_doctor_audit/detectors/labels.py::detect_missing_labels` |

## Definition

Samples present in the dataset with no label - and, for image folders, the related failure
where the "label" is not a class at all. Loader code drops unlabelled rows without announcing
it, so the dataset you audited and the dataset you trained on stop being the same size.

## Why It Matters

In the training split, unlabelled rows are a bookkeeping problem: the audited sample count and
the labelled sample count are different numbers and must not be quoted as one. In the
evaluation split they are a metric problem: the denominator of your accuracy shrinks because
a `NaN` slipped through, and nobody decided that it should.

## Detection

Two independent checks, both off the manifest rather than the raw frames, so the count is the
same one [DD001](DD001-dataset-identity.md) reports.

**Unlabelled samples.** A record with `label is None`. For images, a label is the parent
directory name, and `imagefolder.py` treats these directory names as *no label*:
`""`, `unknown`, `none`, `null`, `unlabeled`, `unmapped`, `-`. So an "unmapped" bucket in your
folder tree is counted as unlabelled rather than as a class. Findings are per-dataset, with
counts broken out by split and the evaluation splits named explicitly.

Severity ladder (`total` is every sample, `unlabeled` those without a label):

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| any unlabelled row inside a test/val split | `HIGH` | `WARNING` | `POTENTIAL` |
| none in evaluation, `unlabeled / total > 2%` | `MEDIUM` | `WARNING` | `NONE` |
| none in evaluation, ≤ 2% | `LOW` | `WARNING` | `NONE` |

**Label cardinality anomaly (images only).** With ≥ 20 labelled images, if
`unique_labels / labelled > 0.9` the "classes" are almost certainly instance folders, not
classes. Reported as `INCONCLUSIVE`, `HEURISTIC`, `MEDIUM`, `POTENTIAL` - the tool is saying
it cannot trust its own class statistics, not that your data is broken.

Exit states: tabular with no label column declared or inferable → `NOT_RUN`;
`labels.source: none` → `NOT_RUN` (*"labelling is out of scope by config"*); an empty manifest
→ `InsufficientEvidence`.

## False Positives

- **Semi-supervised and pretraining sets are deliberately unlabelled.** This rule reports them;
  it does not claim they are wrong. `suppress: [{rule: DD010, reason: "unlabelled pool is the design"}]`
  is the honest opt-out, and it stays visible in the report.
- **Instance-level and open-set tasks genuinely have near-unique labels**, which trips the
  cardinality check. The limitation on the finding says exactly that.
- **Images stored directly in the split root** (no class subfolder) count as unlabelled even
  when the split holds one class. Printed on every unlabelled finding.
- **A `val` split that exists but is not used** still raises the severity to `HIGH`. That is
  intentional - the file is in the dataset, so someone may score on it.

## Severity

Nothing in DD010 is `BLOCKING`. Missing labels shrink and distort a metric, but they do not
mean the model saw the test set. The distinction matters for the verdict: unlabelled test rows
leave the verdict at `FORMAL_EVAL_RISKY` at most, and the `HIGH` severity is what fails a
`--ci` gate.

The cardinality branch reports `INCONCLUSIVE`, which is a statement about the audit itself -
under `--strict` it fails the build, because a rule that could not conclude should not be
mistaken for a pass.

## Examples

Both shapes below come from runs taken while writing this document, on the demo
`leaky_tabular` fixture (316 samples, 8 columns).

Blanking `target` on 3 test rows and 5 train rows:

```text
DD010-0001 HIGH WARNING (POTENTIAL) DETERMINISTIC confidence=HIGH
Unlabelled samples: 8 of 316
Per-split unlabelled counts: test=3, train=5; unlabelled inside the evaluation split(s) ['test'].
{ "unlabeled_total": 8, "by_split": { "test": 3, "train": 5 }, "eval_split_hits": ["test"] }
```

The same fault kept out of evaluation shows the ladder working as designed - 2 blank train
cells (0.6%) → `LOW / NONE`; 20 blank train cells (6.3%) → `MEDIUM / NONE`.

For the cardinality anomaly, the `safe_image` fixture (63 images, `train/<class>/<file>`) was
rearranged so every image sits in its own folder. The audited tree is unchanged in content and
meaningless as a classification set:

```text
DD010-0001 MEDIUM INCONCLUSIVE (POTENTIAL) HEURISTIC confidence=MEDIUM
Label cardinality anomaly: 63 labels for 63 images
100% of labelled images have a distinct label, which is what a non-class directory layout looks
like when read as classes.
{ "unique_labels": 63, "labelled_samples": 63, "unique_ratio": 1.0,
  "sample_labels": ["test_test_bruise_000", ...] }
```

`DD010` has no numbered spec test of its own; the closest coverage is
`tests/test_structure.py::test_test28_nan_values_in_a_category_are_counted_not_crashed`, which
asserts that blank cells are attributed to a rule rather than dropped. `docs/PROJECT_STATE.md`
records DD010 as one of the rules whose detection is verified by hand-run fixtures rather than
by a dedicated regression test.

## Remediation

Label the missing rows, or remove them from the dataset deliberately and record that you did.
The failure mode this rule guards against is the *silent* version of the second option.

For the cardinality anomaly: fix the directory depth (`train/<class>/<image.png>`, not
`train/<image>/<image.png>`), or point `labels.column` at a real class field, then re-audit and
check that [DD011](DD011-class-imbalance.md) and [DD013](DD013-label-shift.md) start reporting
sensible class counts again.

---

*Registry entry: `rules.py` `DD010`. Policy block: `policies.missing_labels`. Related:
[DD001](DD001-dataset-identity.md), [DD009](DD009-label-conflict.md),
[DD011](DD011-class-imbalance.md), [DD013](DD013-label-shift.md).*
