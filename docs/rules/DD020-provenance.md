# DD020 - Dataset Provenance

| | |
| --- | --- |
| Category | `PROVENANCE` |
| Default severity | `LOW` (nothing declared) · `INFO` (declared but incomplete) |
| Formal impact | `NONE` in every branch |
| Evidence type | `DETERMINISTIC` |
| Applies to | the config, not the samples - modality-independent |
| Requires | nothing; always runs |
| Detector | `dataset_doctor/detectors/structural.py::detect_provenance` |
| Registry name | `Dataset Provenance` |
| Policy block | `policies.provenance` |
| In V0.1 rule set | no (`V01_RULES` covers the leakage-critical surface) |

## Definition

Does `dataset-doctor.yaml` say where this dataset came from? Four fields are checked:
`source`, `version`, `license`, `download_date`. If none is set the rule warns; if some are set it
reports the remainder as `INFO`; if all four are set it produces no finding at all.

## Why It Matters

Every other rule in this tool compares the dataset against itself: a fingerprint, a split, a
label. Nothing in the dataset says whether it is the same *benchmark* you published last year
or a later revision of it with 4 000 extra images and a re-licensed download. Without provenance,
"the same dataset" is only a fingerprint match, and a fingerprint match tells you nothing about
licence terms - which is the part that cannot be fixed after release.

This is deliberately the *lowest*-stakes rule in the set. The registry's own
`false_positive_notes` say why: "Missing provenance is a reproducibility gap, not a
corruption." It has `FormalImpact.NONE` in all three branches, so it can never make a verdict
`RISKY` or `INVALID`.

## Detection

`Provenance` is a small pydantic model (`config.py:144`) with four optional string fields and
`extra="allow"`. The branches, in order:

1. `provenance.is_empty` - no field has a truthy value → `LOW` / `WARNING`, title
   `No provenance declared`, evidence `{"missing": ["source", "version", "license", "download_date"]}`.
2. Some fields set, all four non-empty → no finding (`status PASS`, `finding_count 0`).
3. Some fields set, at least one still empty → `INFO` / `PASS`, title `Partial provenance`,
   evidence `{"declared": {...}, "missing": [...]}`, where `declared` is
   `model_dump(exclude_none=True)`.

Two consequences of that shape worth knowing before you trust the output:

- **An empty string counts as absent.** `source: ""` puts `source` in `missing`, both for
  `is_empty` and for the `missing` list.
- **Extra keys are kept but do not satisfy anything.** `upstream_url: https://...` shows up in
  `evidence.declared` and makes the block non-empty, yet `source`/`version`/`license` stay in
  `missing`. The rule reads declarations, not meaning.

**DD020 checks that you declared something, never that it is true.** It does not fetch a URL,
open a licence file, or compare `version` against an upstream registry - it has no network
access and no idea what "MVTec AD" is. A confident, wrong provenance block passes. That is the
whole limits section, and it is why the impact is `NONE`: the audit's job here is to make the gap
visible to a human reviewer, not to adjudicate it.

## False Positives

- **A dataset you generated yourself** has no source, version or licence to declare. Fill in
  `source: "<pipeline + commit>"` and a `version` so future diffs mean something; do not suppress.
- **Licence declared in a README instead of the config** still counts as missing. DD020 looks at
  one place because that is the place the report and the snapshot read.
- **`download_date` is a free-text field.** Anything truthy satisfies it, including `"unknown"`,
  which is a legitimate answer and reads honestly in the report.
- The rule never writes anything. It does not add a `license` to your dataset or your config -
  that is a decision about your data, not a detectable fact.

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| No provenance fields at all | `LOW` | `WARNING` | `NONE` |
| Partial block | `INFO` | `PASS` | `NONE` |
| All four fields present | - | `PASS` (no finding) | `NONE` |

## Examples

`examples/safe_tabular` copied, config untouched, `audit`:

```text
DD020-0001 LOW WARNING (NONE) DETERMINISTIC confidence=HIGH
No provenance declared
dataset-doctor.yaml carries no provenance block: source, version, licence and acquisition date
are unknown.
affected_count 0   auto_fix_available false   metadata.scope "config"
evidence: {"missing": ["source", "version", "license", "download_date"]}
recommended_action: Fill in the provenance block, even for a well-known public benchmark.
```

The same fixture with two of the four fields appended:

```yaml
provenance:
  source: "MVTec AD"
  license: "CC-BY-NC-4.0"
```

```text
DD020-0001 INFO PASS (NONE)
Partial provenance
Provenance declared but incomplete; missing: version, download_date.
evidence: { "declared": { "license": "CC-BY-NC-4.0", "source": "MVTec AD" },
            "missing": ["version", "download_date"] }
recommended_action: Fill in the `provenance:` block of dataset-doctor.yaml.
why_it_matters: Version and licence gaps are the ones that bite when a result is re-checked.
```

`status PASS` with an `INFO` finding is intentional - it is advice, and the rule outcome line
records it as `{"rule_id": "DD020", "status": "PASS", "highest_severity": "INFO",
"finding_count": 1}`. With all four fields filled in (`version: "1.0"`,
`download_date: "2026-05-11"`) the same run reports `finding_count 0` and `status PASS`. All
three runs leave `eval_safety` at `FORMAL_EVAL_SAFE`, and the surrounding fixture (the control
one) stays clean apart from this rule.

The `recommended_action` text differs between the two branches - the empty case carries the
detector's own sentence, the partial case falls through to the registry remediation. Both point
at the same file.

## Remediation

```yaml
provenance:
  source: "MVTec AD"                    # what it is, as you would cite it
  version: "1.0"                        # upstream revision, not your copy's date
  license: "CC-BY-NC-4.0"               # the terms you actually agreed to
  download_date: "2026-05-11"           # when this copy was acquired
```

Then re-audit; the finding disappears because it was measured, not because it was suppressed. If
you genuinely cannot state one of the four, write that (`version: "unknown"`) - the report will
carry it, and a later reader learns the gap existed at audit time rather than invented now.

`policies.provenance: {severity: "info"}` retunes the displayed severity and
`{suppress: "<reason>"}` removes the rule; `enabled: false` is **not** read by this detector, so
it does not silence DD020.

---

*Registry entry: `rules.py` `DD020` ("Dataset Provenance"). Policy block: `policies.provenance`
(`severity`, `suppress`). No test in `tests/` references `DD020` or `provenance`; the three runs
above are this page's evidence. Related: [DD001](DD001-dataset-identity.md) (the fingerprint that
provenance is supposed to complement), [DD018](DD018-version-drift.md),
[DD021](DD021-pii-exposure.md).*
