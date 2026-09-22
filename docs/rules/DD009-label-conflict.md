# DD009 - Label Conflict

| | |
| --- | --- |
| Category | `LABEL` |
| Default severity | `CRITICAL` across splits · `HIGH` inside evaluation · `MEDIUM` inside train |
| Formal impact | `BLOCKING` / `BLOCKING` / `POTENTIAL` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular, image |
| Requires | labelled records; for images, content hashing (not `metadata` fingerprint mode) |
| Detector | `dataset_doctor/detectors/labels.py::detect_label_conflicts` |

## Definition

The same content, two different labels. One input appears more than once in the dataset and
the copies disagree about the answer. This is deterministic: equal hash, unequal label. No
threshold, no statistic, no opinion.

## Why It Matters

A contradictory pair sets an irreducible floor on accuracy - the best a model can do on that
input is guess - and it poisons any metric that counts the same input as both right and
wrong. When the copies straddle a split boundary it is worse than noise: one copy teaches the
model the answer and the other grades it.

## Detection

1. Group every record by its content key:
   - **images**: `sha256` of the file bytes. `fingerprint: metadata` means the bytes were
     never hashed, so the rule reports that it could not conclude instead of passing.
   - **tables**: `feature_sha256` - every column *except* the label, the split column and the
     declared `id_columns`. The label is excluded by necessity (it is what is being compared)
     and ids are excluded so a per-row key cannot break the grouping. If a table has no
     feature hash, the rule falls back to `row_sha256`.
2. A group is a conflict when `len({member.label}) > 1`.
3. Classify by *where* the conflict lives, then emit at most three findings (one per scope),
   largest groups first:

| Scope | Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- | --- |
| `cross_split` | the group spans more than one split | `CRITICAL` | `FAIL` | `BLOCKING` |
| `within_split` (eval) | all members in one test/val split | `HIGH` | `FAIL` | `BLOCKING` |
| `within_split` (train) | all members in a non-evaluation split | `MEDIUM` | `WARNING` | `POTENTIAL` |

Evidence carries the truncated content hash (16 hex), the label set, and up to 10 members per
group with `sample_id`, `split` and `label`, capped at the 20 largest groups.

## False Positives

- **Coarse tabular feature vectors collide legitimately.** With four integer columns and 500
  rows, two genuinely different patients can share a feature hash. The finding is still
  correct as a *question* - the model cannot separate these two rows - but the fix may be
  richer features, not relabelled data. The limitation is printed on the finding.
- **Near-identical images with different labels are not this rule.** A JPEG recompressed to
  different bytes has a different `sha256`, so it is not a conflict; the ambiguity belongs to
  labelling policy and surfaces under [DD004](DD004-near-duplicate.md) instead.
- **A label column encoding provenance rather than a class** (a batch id, a reviewer initial)
  makes every content group look contradictory. That is a config error, and the group sizes
  in the evidence make it obvious in seconds.

## Severity

The evidence is identical in all three cases. Only the *location* changes the price, and that
distinction is the core claim of this tool:

- across a boundary: contamination - the reported metric is invalid;
- inside the evaluation split: the score itself is uninterpretable - still blocking, because
  no number from that split can be defended;
- inside train only: label noise - real, worth fixing, and **not** a reason to invalidate a
  test-set measurement. Reporting it as leakage would be pricing a data-quality problem as an
  evaluation-validity problem.

## Examples

`examples/unsafe_label_conflict` (264 samples, `FORMAL_EVAL_INVALID`) plants four pairs of
rows whose features are identical and whose labels disagree across the boundary. Measured:

```text
DD009-0001 CRITICAL FAIL (BLOCKING) DETERMINISTIC
Conflicting labels on identical content (4 group(s), across splits)
4 content group(s) hold the same data under different labels; 8 samples are involved.

{ "content_hash": "ef7828732751259e", "labels": ["0", "1"],
  "members": [ { "sample_id": "44f15b38c8d67f52", "split": "test",  "label": "1" },
               { "sample_id": "49f081978b4c8cb4", "split": "train", "label": "0" } ] }
```

The same feature vector, `test` answered `1` and `train` answered `0`. Nothing about this
finding is a judgement call.

`examples/unsafe_image_label_conflict` (56 samples) is the image path - one image filed under
three classes, reported alongside the DD003 duplicate it also creates.

The three scopes each have a regression test, and the third one exists specifically to prove
the tool does not over-reach:

- `tests/test_leakage.py::test_test04_identical_content_with_conflicting_labels_is_critical`
  → `CRITICAL`, `scope == "cross_split"`;
- `tests/test_leakage.py::test_conflicting_labels_inside_the_evaluation_split_stay_blocking`
  → `HIGH`, `BLOCKING`, and the verdict is `FORMAL_EVAL_INVALID`;
- `tests/test_leakage.py::test_conflicting_labels_inside_train_alone_are_label_noise_not_leakage`
  → `MEDIUM`, `POTENTIAL`, and the verdict is **not** `FORMAL_EVAL_INVALID`.

## Remediation

Decide one label per content hash: majority vote, expert review, or a documented tie-break.
Then re-audit and confirm the group is gone.

Dataset Doctor will not relabel for you - it has no opinion about which of the two answers is
right, and picking one silently would be the worst kind of automatic fix.

If the collisions are an artefact of a coarse feature encoding, the honest response is to add
the columns that distinguish the cases (or to declare them under `id_columns` if they are
identity), not to suppress the rule.

---

*Registry entry: `rules.py` `DD009`. Policy block: `policies.label_conflict`. Related:
[DD003](DD003-exact-duplicate.md), [DD004](DD004-near-duplicate.md),
[DD010](DD010-missing-labels.md).*
