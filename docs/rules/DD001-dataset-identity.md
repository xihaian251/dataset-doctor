# DD001 - Dataset Identity

| | |
| --- | --- |
| Category | `IDENTITY` |
| Default severity | `INFO` |
| Formal impact | `NONE` |
| Evidence type | `DETERMINISTIC` |
| Applies to | tabular, image |
| Requires | nothing (always runs) |
| Detector | `dataset_doctor/detectors/structural.py::detect_identity` |

## Definition

The record of what this dataset *is*, before anything is judged: sample count, split
names and sizes, class inventory, column schema, file-extension inventory, fingerprint
mode, and the two hashes that pin the rest of the report to bytes - `manifest_hash` and
`config_hash`. Every other rule cites sample ids that come out of this manifest.

DD001 always produces exactly one finding, at `INFO`, even for a perfect dataset. That
is deliberate: a report whose first line is a fact the reader can verify is a report the
reader can audit.

## Why It Matters

A published metric that is not tied to a named dataset revision is unverifiable. If a
reviewer cannot reproduce which rows, which split assignment and which column set
produced a number, the number is an anecdote. DD001 is the finding that makes "we used
the same data" a checkable claim instead of a memory.

It is also the anchor for coverage: rules that could not run are reported relative to
this inventory, so "5 rules skipped on 316 samples" means something.

## Detection

No detection - assembly. `dataset_doctor.manifest` builds one `SampleRecord` per sample
(relative path, size, content hash, split, label, perceptual hash, metadata) and the
identity summarises it.

- `manifest_hash` is `sha256` over the ordered, canonical record list. Same hash means
  the same samples, splits, labels and content, in the same order.
- `config_hash` is `sha256` over the resolved `dataset-doctor.yaml`, so a verdict can be
  reproduced with the policy that produced it.
- `dataset_id` is a short stable prefix so two reports can be told apart in a filename.
- `split_sizes` comes from the adapter, not from directory names - a discovered split
  that contributed zero rows shows up here as `0` and DD002 escalates it.
- `metadata.inference_notes` records every heuristic the loader used (type inference,
  label-column guessing, split-name canonicalisation). Inferred values are labelled as
  inferred, never presented as declared.

Fingerprint mode is part of the identity: `full`, `metadata` or `sampled`. The mode
changes which other rules can run, so it must be visible in the same place.

## False Positives

None by construction - DD001 asserts nothing about quality and has `FormalImpact.NONE`.
It can be *wrong* rather than noisy, though, in one way worth naming: if the config
declares the wrong layout, the identity is internally consistent and still describes the
wrong dataset. `dataset-doctor scan` exists for the five seconds of checking that the
inventory matches your expectation, before you read any verdict.

## Severity

`INFO`, always. It is not a problem, so it never contributes to the verdict, and it
never fails a CI gate. It does appear in the finding count, which is why a clean report
reads "1 INFO" rather than "0 findings".

## Examples

From `dataset-doctor demo` (measured, `leaky_tabular`):

```text
| FORMAL_EVAL_INVALID  316 samples / 21 rules |
```

and the identity block in `report.md`:

```text
| Samples | 316 |
| Splits | `test`: 86, `train`: 200, `val`: 30 |
| Classes | 2 - `0` (189), `1` (127) |
| Fingerprint | full |
| Manifest hash | `474b777afd1f6bd8` |
```

The control fixture `examples/safe_tabular` reports `FORMAL_EVAL_SAFE` with 240 samples
and 1 INFO finding - that INFO finding is DD001.

## Remediation

Nothing to fix. What to *do*: commit `dataset-doctor.yaml` and the report next to the
experiment that used it. A snapshot (`dataset-doctor snapshot ./data --name v3`) makes
the identity comparable across runs, which is what DD018 and DD019 need to exist.

---

*Registry entry: `rules.py` `DD001`. Related: [DD002](DD002-split-integrity.md),
[DD018](DD018-version-drift.md).*
