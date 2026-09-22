# DD017 - Image Property Shift

| | |
| --- | --- |
| Category | `DISTRIBUTION` |
| Default severity | `LOW` at \|SMD\| ≥ 0.5 · `MEDIUM` at \|SMD\| ≥ 1.5 |
| Formal impact | `POTENTIAL` |
| Evidence type | `STATISTICAL` (confidence `MEDIUM`) |
| Applies to | image |
| Requires | `--fingerprint full` (or `sampled`) and ≥ 5 decoded images per split per property |
| Detector | `dataset_doctor/detectors/distribution.py::detect_image_property_shift` |

## Definition

The cheap, physically-grounded properties of the pixels themselves - width, height, aspect
ratio, luma mean, luma spread - are distributed differently in the evaluation split than in
training. It is the image counterpart of [DD012](DD012-feature-shift.md), and it is usually
either a preprocessing accident or evidence that the two splits were not collected by the same
procedure.

## Why It Matters

Networks happily use whatever separates the splits. If every test image is 1024×1024 and every
training image was resized to 512, "resolution" is a feature the model never had to learn to
ignore. Unlike tabular shift, image property shift is often *self-inflicted*: a different
export script, a camera that switched white balance mid-study, a second scraping pass with
different compression. Those are fixable, and the report is where you find out.

The rule stops at the effect size. Whether a luminance gap invalidates your evaluation depends
on whether deployment images look like the test images - a task judgement no pixel statistic
can make.

## Detection

1. Collect `width`, `height`, `brightness`, `contrast` per record from the adapter's decode
   pass, plus a derived `aspect_ratio = width / height`. Records that were never decoded
   (`inspected: false`) and corrupt records (no `width`) are skipped, not guessed.
2. Reference split = the first split with the `train` role, else the alphabetically first.
   One finding per *other* split, in sorted order (`DD017-0001`, `-0002`, ...).
3. For each property, require **≥ 5 values on both sides**; then
   `std_mean_diff(a, b) = (mean_b − mean_a) / pooled_sd` with `ddof=1`.
4. Fire when `|SMD| >= 0.5`. `ks_statistic` (two-sample maximum discrepancy) is recorded next
   to it as supporting evidence, with **no p-value** - on 6-image splits a KS test would be
   theatre.

`brightness` and `contrast` are the mean and standard deviation of the luma channel, computed
from the histogram (`imagefolder.py::luminance_stats`), rounded to 2 decimals.

The 0.5 floor is a literal in the detector and is echoed in the evidence as
`min_std_mean_diff: 0.5`. It is **not** read from policy: `policies.image_property_shift`
accepts `enabled`, `severity` and `suppress`, and a `min_std_mean_diff:` key there is ignored.

If fewer than two splits have decoded pixel data, the rule answers
`InsufficientEvidence` ("fewer than two splits have decoded pixel metadata; re-run with
`--fingerprint full`") rather than PASS. Under `--fingerprint metadata` it is `INCONCLUSIVE` -
`examples/corrupt_image` in that mode reports `rules_inconclusive: ['DD004', 'DD016', 'DD017']`.

## False Positives

- **Small splits.** With 6 images per side, one unusual file moves the mean noticeably. The
  confidence on this rule is `MEDIUM` for that reason even when the whole split is measured.
- **A legitimate stratified design.** Splits deliberately ordered by resolution or lighting
  (easy→hard curriculum, or a hard-test protocol) will fire, and that is the dataset working
  as intended - the fix is to state the protocol, not to equalise the pixels.
- **Different aspect ratios from different crops of the same source** are arithmetic, not
  drift: the width and height means move together while the object stays the same.
- **Zero within-group variance.** If every image on one side is a solid colour, the pooled SD
  is 0 and the ratio is undefined: the description prints `|SMD| inf` and the evidence field
  serialises as `null` (the JSON writer maps non-finite floats to `null`). The difference that
  fired is real; its magnitude is simply not expressible as a standardised distance.
- **Colour changes with matched luminance are invisible here** - see the limitation below.

## Severity

| Largest |SMD| | Severity | Status | Formal impact |
| --- | --- | --- | --- | --- |
| ≥ 1.5 | `MEDIUM` | `WARNING` | `POTENTIAL` |
| ≥ 0.5 | `LOW` | `WARNING` | `POTENTIAL` |

No threshold makes this rule blocking: a distribution difference is not proof that held-out
answers were fitted, and §153 says so plainly - *distribution shift does not automatically mean
invalid evaluation*.

## Examples

`examples/corrupt_image` (36 images, full fingerprint) - the smallest interesting case, where
the same files that trip [DD016](DD016-corrupt-sample.md) also drag the property statistics:

```text
DD017-0001 LOW WARNING (POTENTIAL) STATISTICAL confidence=MEDIUM  train -> test
IMAGE_PROPERTY_SHIFT: train vs test
1 image property(ies) differ materially between train and test: brightness (|SMD| 0.69).
{ "properties": [ { "property": "brightness", "train_mean": 125.913, "test_mean": 132.618,
                    "std_mean_diff": 0.695, "ks_statistic": 0.393 } ],
  "min_std_mean_diff": 0.5 }
```

A 12-image fixture built while writing this document, where the second export is systematically
brighter (luma means 112.5 vs 142.5 against a within-group spread near 5.5), crosses the
escalation line and pushes the statistic to its absurd limit:

```text
DD017-0001 MEDIUM WARNING (POTENTIAL) STATISTICAL confidence=MEDIUM  train -> test
brightness |SMD| 16.036, ks_statistic 1.0   (contrast, width, height: no finding - spread
matched, so the pooled SD swamped the mean gap)
```

The same fixture with solid-colour images on both sides (luma 30 vs 200, zero spread) is the
`inf` case described above: `MEDIUM`, description reads `|SMD| inf`,
`"std_mean_diff": null, "test_mean": 200.0, "train_mean": 30.0`.

No test asserts DD017's behaviour directly, and no shipped `examples/` fixture crosses the 0.5
floor, so the two runs above are the record for this rule - it is listed under "verified by
hand-run data" in `docs/PROJECT_STATE.md`. The partial-coverage path it shares with
[DD016](DD016-corrupt-sample.md) *is* tested
(`tests/test_leakage.py::test_metadata_mode_calls_integrity_a_lower_bound_not_a_count`), and
the invariant that a rule which could not measure must not answer PASS is tested for the
verdict as a whole by `tests/test_structure.py::test_test30_a_train_only_dataset_can_never_be_called_safe`.

## Remediation

Decide which of the two explanations applies - a preprocessing artefact, or a genuine
population difference.

- Artefact: normalise identically across splits (same resize filter, same colour handling),
  then re-export and verify with `--baseline` / [DD018](DD018-version-drift.md).
- Genuine: keep the data, fix the *evaluation*. Report the metric per segment, or weight it,
  and say in the protocol that the test split is brighter. Resampling the splits into
  agreement destroys exactly the effect the model was meant to be measured on.

```yaml
policies:
  image_property_shift:
    enabled: true      # false => NOT_RUN, visible in the coverage block
    severity: low      # overrides both escalation tiers
    suppress: ""       # non-empty => SUPPRESSED, reason recorded in the report
```

---

*Registry entry: `rules.py` `DD017`. Policy block: `policies.image_property_shift`
(`enabled`, `severity`, `suppress`). Related: [DD012](DD012-feature-shift.md) (the tabular
analogue), [DD013](DD013-label-shift.md), [DD016](DD016-corrupt-sample.md) (which files are
excluded here), [DD001](DD001-dataset-identity.md).*
