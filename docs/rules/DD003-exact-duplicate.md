# DD003 - Exact Duplicate

| | |
| --- | --- |
| Category | `DUPLICATE` |
| Default severity | `CRITICAL` (cross-split) / `MEDIUM` (within-split) |
| Formal impact | `BLOCKING` (cross-split) / `POTENTIAL` (within-split) |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular, image |
| Requires | content hashes (`--fingerprint full` or `sampled`) |
| Detector | `dataset_doctor_audit/detectors/duplicates.py::detect_exact_duplicates` |

## Definition

Two samples whose *content* is identical. For images that is `sha256` of the file bytes;
for tables it is `row_sha256`, the hash of every column except the split column. The
groups are then classified by where their members sit: on both sides of a split boundary,
or repeated inside one split.

These are two different problems and DD003 reports them as two different findings.

## Why It Matters

A duplicate *across* the boundary means the holdout was also fitted. The reported metric
is then a mixture of generalisation and recall, and no amount of downstream care -
cross-validation, hyperparameter choice, a bigger test set - recovers its meaning. This
is the single most common way an ML result is accidentally wrong, and it is invisible to
any tool that looks only at data cleanliness.

A duplicate *within* one split does not touch the boundary. It over-weights that sample in
the loss and shrinks the effective sample size. That is real, and it is `MEDIUM`/
`POTENTIAL`, but calling it a leak would be exactly the conflation this project exists to
avoid.

## Detection

1. Require content hashes (`ctx.needs_content_hashes()`); if the fingerprint mode left
   them absent, raise `InsufficientEvidence` - the rule reports as not run, never as PASS.
2. Skip records marked `hash_sampled: false` so a `--sample` run only compares what it
   actually hashed, and records the reduced coverage.
3. Group by the content key; keep groups with more than one member.
4. Split the groups by `len({record.split}) > 1`.
5. For cross-split groups, emit **one finding per split pair** (`train/test` first, then
   pairs involving `test`, then the rest) so the boundary that matters is the first line
   of the report.
6. For within-split groups, emit one finding per split, and report
   `redundant_copies = sum(len(group) - 1)`.

Evidence carries the duplicate-group count, the hash key used, and up to 20 groups with
up to 10 members each - sample id, split and label per member - so a reviewer can open
the two files and confirm it by eye.

Note the consequence of hashing whole rows: if a dataset has a column that is unique per
row (an id), no two rows can ever share `row_sha256`, and identical *content* hides behind
different ids. `tests/test_leakage.py::test_test02_same_bytes_under_different_names_still_detected`
and `test_test19_identical_bytes_on_two_paths_have_two_sample_ids` pin the image behaviour;
for tables the mitigation is `id_columns:` so ids are excluded from feature comparison,
and DD009's separate `feature_sha256` key.

## False Positives

- **Within-split repetition is not leakage.** It is reported separately, at lower
  severity, with `FormalImpact.POTENTIAL`.
- **Synthetic, tiled or placeholder imagery legitimately repeats** - backgrounds, masks,
  augmentation frames, logo screens. Cross-split findings on those are true facts about
  wrong bookkeeping, not always a wrong conclusion; the evidence list is there so you can
  look.
- **A re-saved file is a different file.** Byte hashing is exact: recompression, EXIF
  rewriting or a different row order in a CSV defeats it. That is DD004's job, not a
  weakness of this rule's claim - DD003 only ever asserts what it measured.
- **Cross-split exact duplicates necessarily imply shared entity content.** In fixtures
  where a duplicated row also carries a repeated `patient_id`, DD005 fires alongside
  DD003. That is not a double count: one is content identity, the other is group identity,
  and they have different fixes.

## Severity

| Scope | Status | Severity | Formal impact |
| --- | --- | --- | --- |
| cross-split train/test | `FAIL` | `CRITICAL` | `BLOCKING` |
| cross-split involving test or train | `FAIL` | `HIGH` | `BLOCKING` |
| within one split | `WARNING` | `MEDIUM` | `POTENTIAL` |

The only judgement in the whole rule is which side of the boundary the group straddles.
The identity itself is arithmetic.

## Examples

From `dataset-doctor-audit demo`, measured:

```text
=== leaky_tabular ===  316 samples -> FORMAL_EVAL_INVALID
CRITICAL DD003-0001 Cross-split exact duplicates: test / train (12 samples, test)
```

with 6 identical content groups, e.g. `row_sha256: 8725959b92b970da` shared by
`52cbe5a540541b0d` (test) and `3c9ece88dd8b78e2` (train).

The image side, from `examples/RESULTS.md`:

| fixture | finding | severity |
| --- | --- | --- |
| `unsafe_image_duplicate` | DD003-0001 test / train | `CRITICAL` / `BLOCKING`, verdict `FORMAL_EVAL_INVALID` |
| `unsafe_image_label_conflict` | DD003-0001 test / train | `CRITICAL`, beside DD009-0001 |
| `leaky_image_dataset` | DD003-0001 test / train | `CRITICAL`, 10 planted duplicate groups |

Spec test mapping: TEST 1 (identical image in train and test is CRITICAL), TEST 2 (same
bytes under different names), TEST 3 (same *filename*, different bytes -> not a duplicate),
TEST 19 (identical bytes on two paths are two samples).

## Remediation

Remove one member of each cross-split group - keep the earliest, or drop it from train -
then **re-audit**. The tool will not do this for you: deleting a user's data on the
strength of a hash is not a decision an audit tool gets to make alone.

If the duplicates are a bookkeeping artefact of the split itself, re-split group-safe:

```bash
dataset-doctor-audit split ./data/train.csv --group-by patient_id --output ./data_resplit
```

`examples/unsafe_duplicate` and `tests/test_splitting.py::test_the_grouped_output_of_the_same_data_passes_the_leakage_rules`
show the fault and its disappearance after the fix.

---

*Registry entry: `rules.py` `DD003`. Policy block: `policies.exact_duplicate`. Related:
[DD004](DD004-near-duplicate.md), [DD005](DD005-group-leakage.md),
[DD009](DD009-label-conflict.md).*
