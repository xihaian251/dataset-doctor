# DD004 - Near Duplicate

| | |
| --- | --- |
| Category | `DUPLICATE` |
| Default severity | `HIGH` (cross-split) / `LOW` (within-split) |
| Formal impact | `POTENTIAL` (cross-split) / `NONE` (within-split) |
| Evidence type | `HEURISTIC` |
| Applies to | image |
| Requires | `imagehash` (the `image` extra), decodable images, `--fingerprint full` |
| Detector | `dataset_doctor/detectors/duplicates.py::detect_near_duplicates` |

## Definition

Pairs of images that are not byte-identical but are perceptually almost the same,
measured as the Hamming distance between their 64-bit pHash values. Cross-boundary pairs
are leakage *candidates*; same-split pairs are redundancy.

## Why It Matters

Burst photography, re-exported screenshots, recompressed downloads and augmented copies
defeat a checksum but not a human looking at two thumbnails. If the same physical scene is
in train and in test, the evaluation is partly measuring recall of the training images -
the same failure DD003 catches, one compression step away from being visible.

Near-duplication is also the reason this rule cannot be allowed to speak as loudly as
DD003 does. Similarity is a threshold choice, not a fact.

## Detection

1. pHash (`imagehash.phash`) per decodable image, computed during fingerprinting. Images
   with no hash - corrupt or skipped - are excluded and the exclusion is announced via an
   adapter note so it appears in the coverage section: *"N sample(s) had no pHash ...
   outside DD004 coverage"*.
2. **Candidate generation by bit-band collision, not an O(N²) sweep.** Two 64-bit hashes
   within Hamming distance `t` must agree exactly on at least one of `t+1` disjoint bit
   bands, so band collisions are a *superset* of the true matches - no recall is lost to
   the index. Bands are `t+1` in count over `len(hex)*4` bits.
3. Distances are computed only for candidate pairs; `<= t` survives.
4. Byte-identical pairs are removed and left to DD003, and the removal is stated in the
   finding's limitations - one fault, one price.
5. Remaining pairs are grouped by split pair (`train/test` first), reported as cross-split
   or within-split; up to 20 pairs per finding with both hashes, distance, labels, sizes.
6. If any bucket exceeded `max_bucket_size`, an extra `INCONCLUSIVE` finding says the
   search was truncated and coverage is incomplete.

Defaults: `hamming_threshold: 6`, `method: phash`, `max_bucket_size: 200`, all under
`policies.near_duplicate`. `method` other than `phash` reports `UNSUPPORTED` rather than
silently substituting.

## False Positives

This is where DD004 earns its `HEURISTIC` label, and the finding text says so:

- **The threshold is dataset-dependent by construction.** `hamming_threshold: 6` was set
  by policy, not derived from your images. Uniform, logo-like or tile-heavy imagery
  collides at any threshold - which is exactly what the `max_bucket_size` truncation
  finding is about.
- **pHash does not survive crops, rotations, EXIF orientation or heavy recompression.** A
  clean DD004 does *not* prove the absence of visual duplication, and the finding says
  that in its own limitations field.
- **Brightness/colour variants of one image are legitimately different data** in a
  dataset that deliberately augments. Then the pairs are expected, and the finding is
  information rather than a fault.
- **Within one split, visual similarity is redundancy, not leakage** - `LOW`,
  `FormalImpact.NONE`.

Boundary behaviour is pinned by a test rather than by argument:
`tests/test_leakage.py::test_test31_near_duplicate_boundary_is_the_threshold_itself`
checks that distance == threshold is a match and threshold + 1 is not.

## Severity

| Scope | Status | Severity | Formal impact |
| --- | --- | --- | --- |
| cross-split | `WARNING` | `HIGH` | `POTENTIAL` |
| within split | `WARNING` | `LOW` | `NONE` |
| bucket truncation | `INCONCLUSIVE` | `LOW` | `NONE` |

Confidence is `MEDIUM` at best, and no DD004 finding can produce
`FORMAL_EVAL_INVALID` on its own - a heuristic must not block an experiment by itself. It
can and does raise `FORMAL_EVAL_RISKY`.

## Examples

From `examples/RESULTS.md`, `unsafe_near_duplicate` (perceptually identical images placed
across the boundary, no byte identity anywhere):

```text
| FORMAL_EVAL_RISKY  53 samples / 21 rules |
  - DD004-0001 HIGH WARNING (POTENTIAL) - test / train
```

`DD003` is silent in that fixture, and
`tests/test_examples.py::test_the_perceptual_hash_finds_a_pair_that_no_checksum_can_see`
asserts exactly that. The mixed `leaky_image_dataset` reports DD003 *and* DD004 on the
same train/test boundary - 10 exact groups and 6 near pairs - at different severities.

## Remediation

Inspect the cited pairs (the report shows both hashes and both paths). Then either accept
them as natural variation and record why, or de-duplicate under an explicit rule and
re-audit. Raising `hamming_threshold` to make a finding disappear changes what the tool
will look at next time; the honest move is to state the threshold you used and keep it in
`config_hash`.

---

*Registry entry: `rules.py` `DD004`. Policy block: `policies.near_duplicate`. Related:
[DD003](DD003-exact-duplicate.md), [DD017](DD017-image-property-shift.md).*
