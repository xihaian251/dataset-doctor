# Dataset Doctor

**Your model may be learning your test set. Find out before training.**

Dataset Doctor audits an ML dataset and answers one question first: *could a formal
evaluation be trusted on these splits?* It looks for cross-split duplicates, shared
entities, post-outcome features, temporal inversions and label conflicts, and it reports
each one with the sample ids, hashes and counts a reviewer can check by hand.

It is a local CLI. It does not upload your data, does not call an LLM, does not need a
GPU, and never edits the dataset it inspects.

---

## Demo

```bash
dataset-doctor demo --output ./demo-datasets
```

This generates three small datasets with *known, deliberately planted* faults (each
directory ships a `PLANTED_FAULTS.md`), then audits them. Real output, verbatim:

```text
=== leaky_tabular ===
planted faults: .\demo-datasets\leaky_tabular\PLANTED_FAULTS.md
+---------------------- .\demo-datasets\leaky_tabular ----------------------+
| FORMAL_EVAL_INVALID  316 samples / 21 rules                               |
| 3 CRITICAL  0 HIGH  1 MEDIUM  4 LOW  1 INFO                               |
+---------------------------------------------------------------------------+
  - DD003 Cross-split exact duplicates: test / train: 12 samples (status FAIL)
  - DD005 Entity leakage on 'patient_id': test / train: 66 samples (status FAIL)
  - DD007 Target leakage: 'discharge_code' is a deterministic relabeling of the label: 316 samples (status FAIL)
CRITICAL DD003-0001 Cross-split exact duplicates: test / train (12 samples, test)
CRITICAL DD005-0001 Entity leakage on 'patient_id': test / train (66 samples, test)
CRITICAL DD007-0002 Target leakage: 'discharge_code' is a deterministic relabeling of the label (316 samples, discharge_code)
MEDIUM   DD007-0001 TARGET_LEAKAGE_CANDIDATE: 'visit_lactate' predicts the label unusually well (316 samples, visit_lactate)
LOW      DD012-0001 Feature distribution shift: train vs test (3 column(s)) (86 samples, train)
LOW      DD012-0002 Feature distribution shift: train vs val (2 column(s)) (30 samples, train)
LOW      DD013-0001 Label distribution shift: train vs test (86 samples, train)
LOW      DD020-0001 No provenance declared (0 samples, dataset)
```

The control fixture, generated in the same command, is the other half of the claim -
a clean dataset must not be flagged:

```text
=== clean_tabular ===
| FORMAL_EVAL_SAFE  300 samples / 21 rules                                  |
| 0 CRITICAL  0 HIGH  0 MEDIUM  2 LOW  1 INFO                               |
  - Coverage gap: 0 rule(s) INCONCLUSIVE, 5 not run/skipped (DD004, DD006, DD017, DD018, DD019).
    'SAFE' here means 'no blocking issue found by the rules that could run'.
```

`examples/RESULTS.md` checks in the measured verdict for 13 more fixtures, including a
100-image dataset with 10 exact duplicates, 6 near duplicates, a 3-way label conflict and
2 corrupt files, and a pure distribution-shift dataset that is deliberately **not**
reported as blocked.

---

## Why Dataset Doctor

Most dataset tooling answers "is this data clean?". A clean dataset can still produce a
meaningless test score, and a messy one can still support a valid comparison. The
difference is whether the *evaluation boundary* holds.

So every finding carries two independent labels:

| Axis | Values | Question it answers |
| --- | --- | --- |
| Severity | `INFO` `LOW` `MEDIUM` `HIGH` `CRITICAL` | how much this should change your behaviour |
| Formal impact | `NONE` `POTENTIAL` `BLOCKING` | whether a metric computed on these splits is interpretable |

A class-imbalance finding is `MEDIUM`/`POTENTIAL`. A patient appearing in both train and
test is `CRITICAL`/`BLOCKING`. A duplicate row *inside* train is `MEDIUM`/`POTENTIAL`
(it skews the loss); the same duplicate *straddling* the boundary is
`CRITICAL`/`BLOCKING` (it measures memorisation). Same fact, different consequence -
and the tool separates them because the experiment does.

Three things it does on purpose:

- **Detect Leakage.** Cross-split duplicates, shared entities, target leakage, temporal
  inversion, identifier leakage, conflicting labels.
- **Detect Drift.** Feature and label shift with effect sizes, schema mismatches between
  splits, missingness changes, image-property changes.
- **Track Dataset Changes.** A fingerprint per dataset version, and a diff that names the
  samples that moved between splits.

And one thing it will not do: hand you a single "data health score" and call it a day.
Scores hide reasoning. Every verdict here is traceable to a rule, a finding id, and an
evidence block.

---

## Quick Start

> **Release status:** V0.1 is not published to PyPI yet. Install from a checkout for now;
> the `dataset-doctor` console script is identical either way.
>
> **Name collision, read before installing anything.** An unrelated package already owns
> `dataset-doctor` on PyPI (MIT, 1.0.1, uploaded 2026-03-25 - a tabular *auto-cleaning* tool,
> which is the opposite of what this project does). Our distribution name is therefore
> `dataset-doctor-audit`, and `pip install dataset-doctor` is **not** this tool. Do not install
> both into one environment; they share the importable package name `dataset_doctor`.

```bash
git clone <your-fork>/dataset-doctor && cd dataset-doctor
pip install -e ".[image,excel]"
```

Point it at a directory of CSVs, or at an `train/<class>/*.jpg` image folder:

```bash
dataset-doctor init ./dataset          # writes a commented dataset-doctor.yaml next to the data
dataset-doctor scan  ./dataset         # what was found: splits, samples, schema - no verdict
dataset-doctor audit ./dataset -o ./report
```

`audit` writes `report.json`, `report.md` and `report.html` and prints the summary box.
The original data is opened read-only throughout; the only thing ever written outside
`-o` is the hash cache under `./dataset/.dataset-doctor/`.

A typical finding, from the Markdown report:

```markdown
### DD003-0001 - Cross-split exact duplicates: test / train
`CRITICAL` · FAIL · formal impact `BLOCKING` · evidence `DETERMINISTIC` · confidence `HIGH`

**Where:** `test` <-> `train` (cross-split)
6 identical content group(s) span test and train; 12 samples are involved.

*Why it matters:* Identical content sits on both sides of the test/train boundary, so
whatever is held out for scoring was also fitted. ...

**Affected:** 12 sample(s) (3.8%) · no automatic fix

**Do:** Remove one member of each cross-split group (keep the earliest, or drop from
train), then re-audit. Never let the tool delete data for you.
```

---

## Leakage Detection

| Rule | What it tests | Evidence type |
| --- | --- | --- |
| DD003 | byte-identical images / identical rows on both sides of a split | deterministic |
| DD005 | the same entity (`patient_id`, user, device, session) in more than one split | deterministic |
| DD006 | training rows dated at or after the evaluation window | deterministic |
| DD007 | a feature that *is* the label, or is a deterministic transform of it | deterministic |
| DD007 | a feature that predicts the label suspiciously well | **heuristic - candidate only** |
| DD008 | near-unique id/path columns sitting in the feature matrix | heuristic |
| DD009 | identical content carrying different labels | deterministic |
| DD004 | perceptually near-identical images across the boundary | heuristic |

**On the heuristic ones - read this before you trust a DD007 warning.** The
deterministic layer is arithmetic: identical to the label, one-to-one relabeling, a
coarse function that pins one class per value, or |r| ≥ 0.999999 with the binary target.
That fires `CRITICAL`/`BLOCKING` and it is not a judgement.

The second layer (`TARGET_LEAKAGE_CANDIDATE`) fires when single-feature AUC ≥ 0.95 or
normalised mutual information ≥ 0.6. A genuine biomarker looks *identical* in data to a
post-outcome column, so the finding is `MEDIUM`/`POTENTIAL` with `confidence LOW` and it
is phrased as a candidate, never a verdict. Only you know whether a value was knowable
before the outcome. See [docs/rules/DD007-target-leakage.md](docs/rules/DD007-target-leakage.md).

## Duplicate Detection

Exact duplication is measured on content hashes: `sha256` of the file bytes for images,
and a per-row hash for tables. Cross-split groups are `CRITICAL`/`BLOCKING`; groups that
repeat *within* one split are `MEDIUM`/`POTENTIAL`, because that is a sample-weight
problem, not a leak.

Near duplication uses 64-bit perceptual hashes (pHash) with Hamming distance ≤ 6, and
finds candidates by bit-band collision rather than an O(N²) sweep. Byte-identical pairs
are left to DD003 so one fault is never priced twice.

## Group Leakage

The failure that deduplication cannot see: two rows with completely different content,
same `patient_id`, one in train and one in test. Declare the entity column and DD005
reports every entity that appears in more than one split, with row counts per split:

```bash
dataset-doctor audit ./cohort --group-by patient_id
```

Or in `dataset-doctor.yaml`:

```yaml
groups:
  columns: [patient_id]
```

When the leakage is real, the fix is a group-safe split, and the tool can write one into
a **new** directory without touching the original:

```bash
dataset-doctor split ./cohort.csv --group-by patient_id --output ./cohort_resplit
```

A declared group column whose values are unique per row produces a `LOW` advisory, not a
leakage finding - a row id cannot hide an entity, and naming one should not turn a clean
dataset red.

## Distribution Shift

Feature shift (DD012) and label shift (DD013) are reported as **effect sizes with the
p-value attached**, never as significance alone: standardised mean difference, PSI,
Wasserstein, KS, total variation and Jensen-Shannon distance. With hundreds of columns,
the KS p-values go through Benjamini-Hochberg and the report says so.

Shift is not leakage. `examples/shifted_tabular` has covariate and label shift with no
boundary violation, and it measures as:

```text
| FORMAL_EVAL_RISKY  260 samples / 21 rules                                 |
| 0 CRITICAL  2 HIGH  0 MEDIUM  1 LOW  1 INFO                               |
  - DD012 Feature distribution shift: train vs test (4 column(s)): 60 samples, severity HIGH
  - DD013 Label distribution shift: train vs test: 60 samples, severity HIGH
```

`RISKY`, not `INVALID`, and `dataset-doctor audit` exits 0 on it. Whether a shift
invalidates *your* evaluation is a task question - a harder benchmark is a design choice.
The tool states the measurement and leaves the decision where it belongs.

## Dataset Fingerprint

```bash
dataset-doctor fingerprint ./dataset
```

A fingerprint is the ordered manifest hash: one record per sample with its relative path,
size, content hash, split, label and perceptual hash where applicable. Two datasets with
the same `manifest_hash` have the same samples, splits and labels - which is what lets a
published number be tied back to the bytes that produced it.

Three modes trade coverage for time: `full` (hash every byte, decode every image),
`metadata` (no pixel or content access - integrity and duplicate rules then report as
*not run*, not as PASS), and `sampled` (`--sample 0.1`, with the fraction recorded in the
report).

## Dataset Diff

```bash
dataset-doctor snapshot ./dataset --name v1
dataset-doctor diff ./dataset --baseline v1
```

The diff names the added, removed and modified samples, the labels that flipped, and -
the one that matters most - the samples that **moved between splits**. Moved-into-test is
`CRITICAL`/`BLOCKING` (DD019): it is the standard way a number improves without the model
improving. `audit --baseline v1` folds the same comparison into a single run.

Snapshots live in `<dataset>/.dataset-doctor/snapshots/`. Diffing two different datasets
is supported by passing two paths.

## Reports

Every audit writes all three, in the same content:

- `report.json` - machine-readable, stable schema (`schema 1.0`), for dashboards and tests
- `report.md` - reviewable in a pull request, evidence blocks collapsed
- `report.html` - self-contained single file, no external assets, safe to email

`dataset-doctor report ./report.json -f md -f html` re-renders from a stored JSON without
re-reading the data. Reports never contain raw field values from PII-suspect columns -
only counts (see [SECURITY.md](SECURITY.md)).

## CI

```bash
dataset-doctor audit ./dataset --ci
```

| Invocation | Fails (exit 1) when |
| --- | --- |
| `audit ./data` | a `BLOCKING`/`CRITICAL` assertive finding, or the verdict is `FORMAL_EVAL_INVALID` |
| `audit ./data --ci` | the above, **plus** any `MEDIUM`+ assertive finding, or a verdict that is not `FORMAL_EVAL_SAFE` |
| `audit ./data --strict` | the above, **plus** any rule that could not reach a verdict |
| `audit ./data --fail-on never\|low\|medium\|high\|critical` | a custom threshold instead of the ladder above |

Exit codes: `0` pass · `1` blocking findings · `2` configuration, usage or I/O error ·
`3` internal error · `130` interrupted.

`--strict` is deliberately a *superset* of `--ci`: a gate you tighten by asking for more
caution can never end up looser than the gate you started with.

```yaml
# .github/workflows/dataset.yml
- run: pip install -e ".[image,excel]"
- run: dataset-doctor audit data/cohort --ci --baseline data/cohort/.dataset-doctor/snapshots/accepted.json
```

## Methodology

- [docs/METHODOLOGY.md](docs/METHODOLOGY.md) - every detection method, formula and
  threshold, with the reason for each default
- [docs/rules/](docs/rules/) - one document per rule: definition, why it matters,
  detection, false positives, severity, examples, remediation
- [docs/adr/](docs/adr/) - the six decisions that shaped the design (hash strategy,
  near-duplicate search, severity model, read-only policy, statistical shift)
- [docs/COMPETITIVE_ANALYSIS.md](docs/COMPETITIVE_ANALYSIS.md) - how this differs from
  Great Expectations, Evidently, ydata-profiling, Cleanlab, DVC and FiftyOne
- [docs/DEEP_RESEARCH_PHASE0.md](docs/DEEP_RESEARCH_PHASE0.md) - the Phase-0 research report:
  how the landscape survey turned into the design decisions (the fact table above wins on any
  disagreement)
- [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) - what is implemented, what is measured,
  what is known to be wrong

## Limitations

Published, not buried:

```text
Semantic leakage cannot be fully automated.
Near duplicate thresholds are dataset-dependent.
Distribution shift does not automatically mean invalid evaluation.
```

More, including the false positives already observed:
[docs/PROJECT_STATE.md](docs/PROJECT_STATE.md#known-limitations).

## Roadmap

V0.1 scope, and what comes after it: [ROADMAP.md](ROADMAP.md). Headlines: more
modalities (text, audio, time-series), policy presets for medical/vision/time-series, and
a leakage-first benchmark built from public datasets with documented contamination.

---

## Requirements and guarantees

Python >= 3.11 · Windows / Linux / macOS · no GPU · no API key · no cloud account ·
no LLM · no database · no Docker.

**Guaranteed:** the audit opens your dataset read-only; `split` writes only into a new
directory; nothing leaves your machine.

**Not guaranteed:** that an empty report means a safe dataset. It means the rules that
*could* run found nothing blocking. Coverage - which rules ran, which were skipped and
why - is printed in every report and recorded in `report.json`.

## Licence

Apache-2.0. See [LICENSE](LICENSE). Dataset Doctor never assigns,
invents or modifies a licence for *your* dataset; the `provenance.license` field in
`dataset-doctor.yaml` is your declaration, and DD020 only reports whether you filled it
in.
