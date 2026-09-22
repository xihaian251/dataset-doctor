# DD021 - PII Exposure

| | |
| --- | --- |
| Category | `PRIVACY` |
| Default severity | `MEDIUM` |
| Formal impact | `NONE` - it can never make a verdict `RISKY` or `INVALID` |
| Evidence type | `HEURISTIC` (this rule is *not* deterministic, and says so in every field) |
| Confidence | `LOW` |
| Applies to | tabular only (`requires: ["tabular"]`) |
| Policy | `policies.pii_scan` - `enabled`, `min_match_ratio` (default `0.05`) |
| Detector | `dataset_doctor/detectors/structural.py::detect_pii` |
| Registry name | `PII Exposure` |
| In V0.1 rule set | no |

## Definition

Scan every column of every split for values whose *shape* resembles personal data: e-mail
addresses, phone-number-shaped digit strings, national-ID-shaped digit strings. Report the
column, the pattern, and how many rows matched - never the values.

## Why It Matters

A dataset that leaves the lab is a disclosure. The other 20 rules ask whether the data supports
a trustworthy metric; this one asks whether the audit itself is safe to share and whether the
folder you are about to attach to a supplementary material has phone numbers in it. It is the
only rule whose subject is the *report*.

It is also the rule that most easily becomes a false accusation, so the implementation refuses
to claim: the title is prefixed `POTENTIAL_PII_COLUMN:`, `evidence_type` is `HEURISTIC`,
`confidence` is `LOW`, `metadata.candidate` is `true`, and `why_it_matters` states the
alternative explanation ("a phone number" vs "an encoded identifier") instead of asserting the
causal one.

## Detection

Three anchored regexes, applied to `str(value).strip()` of every non-null cell:

| Pattern | Regex |
| --- | --- |
| `email` | `^[^@\s]{1,64}@[^@\s]{2,}\.` |
| `phone_like` | `^\+?[0-9][0-9\s().-]{7,14}$` |
| `national_id_like` | `^\d{6}[-+]?\d{4}$` \| `^\d{9,11}$` |

A `(column, pattern)` pair becomes a finding when `matches > 0` **and**
`matches / non_null_rows >= min_match_ratio` (default 0.05). Denominators are per split, and the
ratio is reported to one decimal in the description and to four in `evidence.match_ratio`.

**The date veto.** `phone_like` accepts dashes and spaces, which is exactly what an ISO date
looks like: `2026-05-11` matches it (first char `2`, then nine characters from `[0-9\s().-]`).
Without a veto, every timestamp column in a clinical cohort - the most common column in the
datasets this tool exists for - gets reported as personal data. `_DATE_SHAPED`
(`structural.py:480`) therefore cancels `phone_like` only; the other two patterns are unaffected.

**Splits are scanned alphabetically, and each `(column, pattern)` pair is reported once.** A
column present in both `test.csv` and `train.csv` yields one finding attributed to `test`. The
`seen` set makes the rule quiet about repeats; it does not make the count a whole-dataset count.

**No values are copied into the report.** Not in `evidence`, not in `location`, not in the
Markdown or HTML renderers - `evidence.values_shown` is `false` in every finding, and there is no
code path that could set it otherwise. Verify in place, in the file, where the access controls
already are.

## False Positives

- **Any 9-11 digit number is `national_id_like`.** An 11-digit phone column above is flagged as
  *both* `phone_like` and `national_id_like` - two findings, one column. The patterns overlap by
  construction; treat the pair as one candidate.
- **Anonymised identifiers collide with everything.** Hashes truncated to digits, sequence
  numbers, timestamps-as-integers and station codes all match. `min_match_ratio` is the knob for
  this: raise it, or accept the noise.
- **Mixed-format columns dilute below the threshold.** One real phone number in 200 rows is
  0.5% and reports nothing. A rule tuned to avoid accusing every `id` column cannot find sparse
  PII either - this is a *column-level* signal, not a row-level scanner.
- **Non-tabular data is `UNSUPPORTED`, not `PASS`.** An image audit records
  `PII scanning covers table columns` and produces no finding; OCR-of-document text is out of
  scope, and the rule does not pretend otherwise.

## Severity

| Condition | Severity | Status | Formal impact |
| --- | --- | --- | --- |
| Column matches a pattern at ≥ `min_match_ratio` | `MEDIUM` | `WARNING` | `NONE` |
| Below the ratio, or no match | - | `PASS` (no finding) | - |
| `policies.pii_scan.enabled: false` | - | `NOT_RUN` (`policy pii_scan.enabled = false`) | - |
| Non-tabular dataset | - | `UNSUPPORTED` (`PII scanning covers table columns`) | - |

## Examples

`examples/safe_tabular` (180 train / 60 test) with five synthetic columns added: `phone`
(`1380000` + 4 digits, every row), `appt_date` (`2026-05-01`…-`28`), `email`
(`p###@example.org`), `nid` (the constant `123456-7890`), and `rare_phone` (phone-shaped in 4 of
180 training rows, plain 4-digit integers elsewhere). Default policy:

```text
DD021-0001 MEDIUM WARNING (NONE) HEURISTIC confidence=LOW
POTENTIAL_PII_COLUMN: 'phone' looks like phone_like
60 of 60 non-null values in 'phone' (100.0%) match a phone_like pattern.
source_split test   affected_count 60   metadata {"scope": "column", "candidate": true}
evidence: {"column": "phone", "match_ratio": 1.0, "matching_rows": 60, "non_null_rows": 60,
           "pattern": "phone_like", "values_shown": false}
limitations:
  - No raw values are included in this report by design. Verify in place.
  - False positives are common: any digit string of the right length matches 'phone_like'.
recommended_action: Confirm with the data owner whether 'phone' is personal data; tokenise or
  drop it before the dataset or this report leaves the lab.
```

Five findings total, all at `100.0%` on the 60-row `test` split: `phone` (× `phone_like`,
`national_id_like`), `email`, `nid` (× `phone_like`, `national_id_like`). **`appt_date` and
`rare_phone` produce nothing** - the first because of the date veto, the second because
`4 / 180 = 2.2%` is under the threshold. Outcome line:
`{"rule_id": "DD021", "status": "WARNING", "finding_count": 5, "highest_severity": "MEDIUM", "duration_ms": 4}`.

The same fixture with `policies.pii_scan.min_match_ratio: 0.02` adds exactly the sparse column,
and it is attributed to `train` because that is where it clears the bar:

```text
DD021-0006 MEDIUM WARNING | POTENTIAL_PII_COLUMN: 'rare_phone' looks like phone_like
4 of 180 non-null values in 'rare_phone' (2.2%) match a phone_like pattern.
DD021-0007 MEDIUM WARNING | POTENTIAL_PII_COLUMN: 'rare_phone' looks like national_id_like
4 of 180 non-null values in 'rare_phone' (2.2%) match a national_id_like pattern.
```

With `enabled: false` the rule reports nothing and the outcome records why
(`"status": "NOT_RUN", "skip_reason": "policy pii_scan.enabled = false"`). On
`examples/leaky_image_dataset`:

```text
{"rule_id": "DD021", "status": "UNSUPPORTED", "finding_count": 0,
 "skip_reason": "PII scanning covers table columns"}
```

Across all four tabular runs `eval_safety` stayed `FORMAL_EVAL_RISKY`, and DD021 is *not* one of
the reasons: `["DD007 TARGET_LEAKAGE_CANDIDATE: 'email' predicts the label unusually well: 240
samples, severity MEDIUM", "DD012 Feature distribution shift: train vs test (5 column(s)): 60
samples, severity HIGH"]`. The synthetic `email` column I added to exercise this rule happens to
correlate with the label, so it tripped the leakage rule too - a useful reminder that "privacy
risk" and "evaluation validity" are different axes measured on the same column, and that a
`NONE` impact finding cannot rescue or ruin a verdict.

Covered by `tests/test_structure.py::test_dd021_an_iso_date_column_is_not_called_a_phone_number`,
which keeps an 11-digit `contact` column as the positive control so the veto cannot pass by
simply switching the rule off. The ratio threshold, the cross-split dedup and the
`UNSUPPORTED`/`NOT_RUN` branches above were produced by manual runs (scratch fixtures under
`_doccheck/`) and are not in the suite.

## Remediation

The finding is a question, not a deletion order. Nothing here is automatic and nothing is
removed - `auto_fix_available` is false because dropping a column from someone's dataset is not
this tool's call.

1. Open the file and look at the column. `matching_rows` and `non_null_rows` tell you where to
   start.
2. If it is personal data, tokenise or drop it **in your pipeline**, then re-audit so the
   disappearance is measured rather than assumed.
3. If it is an identifier that merely *looks* personal, keep it and record the judgement:
   `policies.pii_scan: {suppress: "<why this column is not personal data>"}` keeps the reason in
   the report. `enabled: false` also works - DD021 is one of the rules that reads it - but it
   turns the rule off for the whole dataset, including columns you have not looked at.

---

*Registry entry: `rules.py` `DD021` ("PII Exposure"). Policy block: `policies.pii_scan`
(`enabled`, `min_match_ratio`, `severity`, `suppress`). Related:
[DD007](DD007-target-leakage.md) (a column that predicts the label - the other thing to worry
about), [DD006](DD006-temporal-leakage.md), [DD020](DD020-provenance.md) (licence terms, also a
"what may leave the lab" question).*
