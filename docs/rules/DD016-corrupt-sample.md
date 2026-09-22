# DD016 - Corrupt Sample

| | |
| --- | --- |
| Category | `INTEGRITY` |
| Default severity | `HIGH` · `MEDIUM` when the rate is under 1% and no evaluation split is involved |
| Formal impact | `POTENTIAL` |
| Evidence type | `DETERMINISTIC` |
| Applies to | image + tabular |
| Requires | a fingerprint mode that opens the files (`full`, `sampled`) for a complete answer |
| Detector | `dataset_doctor/detectors/integrity.py::detect_corrupt_samples` |
| In V0.1 rule set | yes |

## Definition

A file the dataset layout declares as a sample that cannot be read. For images this is a
failed decode; for tables it is a file the parser refused. The rule counts them, says which
split they sit in, and - the part that matters for this tool - separates "your data has a few
bad bytes" from "the set your metric was computed over is not the set you published".

## Why It Matters

Loaders disagree about what to do with an unreadable file. Some skip it, some raise, some
raise only after the epoch has started, and a framework that swallows the exception silently
shrinks your evaluation set without telling you. When the corrupt files sit in train, that is
a nuisance. When they sit in test, the denominator of the published accuracy is a different
set than the one declared in the split - the same class of problem as a duplicate crossing
the split boundary, just arrived at by decay rather than by mistake.

## Detection

**Images.** The adapter opens every enumerated file (`imagefolder.py::_inspect`). A zero-byte
file is caught by size; anything else is caught by a failed `Pillow` verification, which
records `corrupt: True` plus a short reason (`zero-byte file`, `unreadable or truncated image
data`). DD016 groups the broken records by split and emits one finding per run
(`DD016-0001`), with up to 20 examples carrying `sample_id`, `path`, `size` and `reason`.

**Tables.** The tabular adapter records parse failures in `adapter.unreadable`; the detector
maps each path back to the declared split that contains it and reports them alongside any
split whose frame came out empty (`empty_splits`). Nothing here needs a threshold - a file
either parsed or it did not.

**Coverage, honestly.** The denominator in the title is the number of *enumerated* samples,
not the number of files that were actually opened. Under `--fingerprint metadata` pixels are
deliberately never decoded, so only zero-byte files are visible. In that mode the rule still
reports what it found, but as `INCONCLUSIVE` with an explicit lower bound in the description
and a `limitations` line, because "1 corrupt file" out of an unexamined remainder is not an
integrity statement. If *no* file at all was decoded, the rule raises
`InsufficientEvidence` instead of answering:

```text
No image was decoded, so integrity cannot be asserted. Re-run with `--fingerprint full`
(metadata mode deliberately skips pixel access).
```

The same applies to `--sample 0.1`: the rate is over the sample, and the coverage block says
the sample fraction was 0.1.

## False Positives

- **Files that are not images.** Anything outside `IMAGE_SUFFIXES` is enumerated as *skipped*,
  not corrupt, and lands in the coverage block's `skipped_files` - a `.md` README in a class
  folder is not damage.
- **Formats Pillow can open but not decode fully** (some 16-bit TIFFs, CMYK JPEGs) can show up
  as corrupt on a machine without the codec. The reason string is deliberately coarse - this
  build reports `zero-byte file` or `unreadable or truncated image data` and nothing more - so
  an "unsupported format" diagnosis means opening the file once by hand before re-exporting a
  whole split.
- **A corrupt file is not leakage.** This rule is `POTENTIAL`, never `BLOCKING`: it says the
  measurement is over a different set, not that held-out answers were fitted.

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| Any broken file in a test/val split | `HIGH` | `FAIL` | `POTENTIAL` |
| Full coverage and rate ≥ 1% of enumerated samples | `HIGH` | `WARNING` | `POTENTIAL` |
| Full coverage and rate < 1% | `MEDIUM` | `WARNING` | `POTENTIAL` |
| Coverage partial (metadata mode) and no eval split hit | `MEDIUM` | `INCONCLUSIVE` | `POTENTIAL` |
| Table file failed to parse | `HIGH` if that split is eval, else `MEDIUM` | `WARNING` | `POTENTIAL` |

Concentration in the evaluation split outranks raw count, which is why the escalation column
is keyed on the split rather than the rate. `FAIL` here does not produce
`FORMAL_EVAL_INVALID`: the verdict is driven by `BLOCKING` findings, and corruption is
recoverable by re-exporting a file, whereas a duplicate in test is recoverable only by
rebuilding the split and re-running the model.

## Examples

`examples/corrupt_image` - 36 images, two of them broken in `train/scratch`:

```text
DD016-0001 HIGH WARNING (POTENTIAL) DETERMINISTIC confidence=HIGH
Unreadable or corrupt images: 2 of 36
2 file(s) failed Pillow verification (truncated, zero-byte or unsupported). Per split: train=2.
{ "enumerated": 36, "decoded": 36, "not_decoded": 0, "broken": 2,
  "by_split": { "train": 2 },
  "examples": [ { "path": "train/scratch/empty.png", "reason": "zero-byte file", "size": 0 },
                { "path": "train/scratch/truncated.jpg",
                  "reason": "unreadable or truncated image data", "size": 252 } ] }
```

Moving those same two files into `test/scratch` changes the verdict vocabulary, not the
count - and `why_it_matters` switches to the denominator wording:

```text
DD016-0001 HIGH FAIL (POTENTIAL)
Unreadable or corrupt images: 2 of 36
2 file(s) failed Pillow verification (truncated, zero-byte or unsupported). Per split: test=2.
Affected evaluation split(s): test.
```

The same dataset audited with `--fingerprint metadata` sees one of the two (the zero-byte
file, caught without a decode) and says so rather than reporting a clean bill of health:

```text
DD016-0001 MEDIUM INCONCLUSIVE (POTENTIAL)
Unreadable or corrupt images: 1 of 36
1 file(s) failed Pillow verification (truncated, zero-byte or unsupported), and 35 more were
never opened, so this is a lower bound. Per split: train=1.
limitations: 35 of 36 file(s) were not opened (`--fingerprint metadata` reads sizes only),
  so a truncated or unsupported image among them would not appear here.
```

Its `eval_safety` is `INCONCLUSIVE` - the mode that inspects nothing can certify nothing.
Downstream, the corrupt files also remove themselves from other rules' scope, which is
recorded as a coverage note rather than a silence:

```text
adapter_notes: 2 sample(s) had no pHash (corrupt or skipped) and are outside DD004 coverage
```

Covered by `tests/test_leakage.py::test_corrupt_and_empty_images_are_reported_not_silently_skipped`
(TEST 13, TEST 14) and
`tests/test_leakage.py::test_metadata_mode_calls_integrity_a_lower_bound_not_a_count`,
plus `examples/RESULTS.md` (`leaky_image_dataset`: `2 of 100`).

## Remediation

The repair plan emits a **quarantine** step, never a delete:

```text
mkdir -p <dataset>-quarantine && mv <broken files> <dataset>-quarantine/
```

with `residual_risk: "Manual step by design: the tool will not delete your data."` Moving the
files out changes the split's population, so re-audit afterwards and, if the affected split
was the evaluation split, re-run the metric - a number computed before the removal and a
number computed after it are answers about different sets.

`policies.corrupt_sample: {severity: "medium"}` lowers the escalation and
`{suppress: "<reason>"}` removes the rule from the verdict; `enabled: false` is **not** read
by this detector (see the registry note in `docs/PROJECT_STATE.md`).

---

*Registry entry: `rules.py` `DD016`. Policy block: `policies.corrupt_sample`
(`severity`, `suppress`). Related: [DD001](DD001-dataset-identity.md) (what was enumerated),
[DD004](DD004-near-duplicate.md) (loses coverage here),
[DD017](DD017-image-property-shift.md) (skips undecoded records),
[DD018](DD018-version-drift.md) (re-export then verify).*
