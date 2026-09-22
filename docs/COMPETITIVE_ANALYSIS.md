# Competitive Analysis - Dataset Doctor v0.1

**Facts checked 2026-09-21.** Version numbers and SPDX license identifiers below were read from
PyPI project metadata for the named distribution on that date; capability descriptions come from
each project's own documentation or paper. Where a claim could not be verified it is marked as
such, and the "Claims we do not make" section at the end is binding for the README and the paper
draft: **we have no head-to-head benchmark, so nothing here asserts that Dataset Doctor detects
more than anyone else.**

## Why this file exists

The spec (sections 118, 227) requires an honest map of the field before writing the README's
first screen. Two reasons it matters more than usual here: the tool's core claim is a *category*
claim ("evaluation-validity audit", not "data quality report"), and a category claim is only
interesting relative to what already exists.

## Landscape

| Tool | Version (2026-09-21) | License | What it is actually for | Leakage-first? |
| --- | --- | --- | --- | --- |
| Great Expectations | 1.23.1 | Apache-2.0 | Assertion suites: declare expectations about schema/ranges/nulls, validate, get a pass-fail data contract plus a Data Docs site | no |
| Evidently | 0.7.23 | Apache-2.0 | Model and data monitoring reports: drift, quality, performance dashboards over reference vs current | no |
| ydata-profiling | 4.18.4 | MIT | Automated EDA HTML profile: types, distributions, correlations, missingness, sample rows | no |
| Cleanlab | 2.9.0 | Apache-2.0 | Finds suspect *labels* from out-of-sample predicted probabilities (confident learning, Northcutt et al. below) | adjacent - label noise, not split integrity |
| DVC | 3.67.1 | Apache-2.0 | Git-for-data: versioning, pipelines, remote cache, `dvc diff` between git refs | no (versioning, not auditing) |
| FiftyOne + fiftyone-brain | 1.22.0 / 0.25.0 | Apache-2.0 (per PyPI metadata) / Brain ships separately, license not stated in its metadata | Interactive vision explorer; Brain ships `compute_leaky_splits()` | **yes - the one real overlap** |
| imagehash | 4.3.2 | BSD-2-Clause | pHash/dHash/wHash primitives (what our DD004 uses) | no |
| text-dedup | 0.4.1 | not stated in PyPI metadata | Exact / minhash / suffix-array dedup for text | no |
| datatrove | 0.10.0 | Apache-2.0 | Large-scale corpus processing pipeline ops, incl. dedup and filtering | no |
| NeMo Curator | 1.3.0 | Apache-2.0 | GPU/Ray corpus curation: dedup, quality classification, PII redaction | no |
| cleanvision | 0.3.7 | not stated in PyPI metadata (check the repo) | Image dataset checks: near-duplicates, blurry/low-information/dark/bright, odd aspect ratio | no |
| **Dataset Doctor** | 0.1.0, distribution `dataset-doctor-audit` | Apache-2.0 | Audit whether a dataset can support a trustworthy *formal evaluation*, with reviewable evidence and a blocking verdict | yes |

DVC note: the repository moved from `iterative/dvc` to `treeverse/dvc`; cite the current location.

### The short name `dataset-doctor` is already taken

Verified from PyPI metadata on 2026-09-21 and re-verified from the downloaded 1.0.1 wheel on
2026-09-22:

| | |
| --- | --- |
| Distribution | `dataset-doctor` - releases 1.0.0 and 1.0.1, both uploaded 2026-03-25 |
| License / Python | MIT / `>=3.11` |
| Home page | github.com/Mirdula18/dataset-doctor (author: "Dataset Doctor Contributors") |
| Import package it installs | `dataset_doctor` |
| Console script it installs | `dataset-doctor` |
| Dependencies | pandas, numpy, scikit-learn, PyYAML, rich, typer |
| Self-described | "Automatically diagnose **and clean** messy datasets"; tabular only |
| Commands | `diagnose` / `report` / `clean` [--output, --normalize] / `display` / `show` / `init-config`; Python API `dd.diagnose`, `dd.auto_fix` |
| Overlap with us | none of DD002-DD009: no split integrity, no group/entity, no temporal, no label conflict, no snapshot/diff, no evidence ids, no formal-evaluation verdict |

Three consequences:

1. **`pip install dataset-doctor` is not this tool**, and its CLI has no `audit` subcommand, so a
   reader following the spec's headline command literally would get an error from someone else's
   package. Our distribution is `dataset-doctor-audit` (name checked free on PyPI 2026-09-21, along
   with `datasetdoctor` and `ds-doctor`).
2. **All three of our namespaces carry the suffix** - `dataset-doctor-audit` on the index,
   `dataset_doctor_audit` for `import`, `dataset-doctor-audit` as the command. Sharing the import
   package or the console script with someone else's wheel means two installations overwrite each
   other's files in one `site-packages`, so suffixing only the distribution name was not enough;
   ADR 0006 records the widening. `datasetdoctor` remains the fallback if the index ever changes.
3. **Brand-level artefacts keep the short name**, because they are file paths inside a user's data
   rather than installed namespaces: the config file is `dataset-doctor.yaml`, the per-dataset
   workdir `.dataset-doctor/`, and report directories `dataset-doctor-report/`. Neither project
   writes to those, so there is nothing to collide.

Its `clean`/`auto_fix` behaviour is also the cleanest contrast we have: that project imputes
missing values, drops duplicate rows and removes constant columns, i.e. it edits the dataset.
V0.1's non-negotiables are the opposite - read-only, no deletion, recommendations only - so we
must never be described as "the other dataset doctor" without saying which one does the editing.

### The nearest neighbour, in detail

`fiftyone.brain.compute_leaky_splits()` is the one function found that does what DD003/DD005
do for images: it looks for samples that appear on both sides of a split. It is also the reason
our constraints matter rather than being arbitrary:

- it requires a running **MongoDB**, and Dataset Doctor V0.1 has no database and no daemon;
- it requires **embeddings**, i.e. a model (fiftyone-brain's PyPI metadata states no license of
  its own, so its terms must be checked at the source before anything depends on it), and V0.1
  requires no GPU, no API key and no model download;
- it is a function inside a viewer, not an audit with an exit code: nothing gates a CI job on it.

So the differentiation is *not* "we detect leakage and they don't". It is: deterministic
content-digest matching with recorded evidence, in one `pip install`, on Windows/Linux/macOS,
runnable in CI, for tabular **and** image data, with entity, temporal and label-conflict checks
the vision tool does not have.

### What the literature names the problem

- Kapoor & Narayanan, *Leakage and the reproducibility crisis in machine-learning-based science*,
  Patterns 2023, DOI `10.1016/j.patter.2023.100804`. The survey's own fields/paper counts differ
  between the journal version (17 fields, 294 papers) and its arXiv preprint (329 papers) - cite
  the journal numbers, never the preprint's, and do not enumerate its leakage typology beyond what
  the abstract states.
- Northcutt, Jiang & Fleischer, *Impact of label errors on ML performance*, arXiv `2103.14749`;
  Northcutt, Su & Liu, *Confident learning*, JAIR, DOI `10.1613/jair.1.12125` - the basis of
  Cleanlab's approach, and the reason DD009/DD010 deliberately measure label *conflict* and
  *absence* rather than re-deriving suspect labels from probabilities.
- Kaufman et al., *Leakage in data mining: formulation, detection, and avoidance*, ACM TKDD,
  DOI `10.1145/2382577.2382579` - the formal statement of what DD007/DD008 are heuristically
  approximating.
- Elangovan, Rastogi, Singh & Mehndiratta, EACL 2021, DOI `10.18653/v1/2021.eacl-main.113` -
  leakage in NLP pipelines, i.e. the split-integrity half.
- The reproducibility-crisis medical-ML literature is real but I could not confirm the specific
  "~90 of 100 studies" figure, so it is not cited anywhere in this project. Related PubMed
  records checked during Phase 0: `42518934`, `41833897`, `41508117`, `42201923`, `42623034`.

## Gap this project fills

1. **A verdict, not a dashboard.** Every finding carries `formal_impact ∈ {NONE, POTENTIAL,
   BLOCKING}` and the report ends in `SAFE / RISKY / INVALID / INCONCLUSIVE`. Data-quality
   tooling reports; this adjudicates, which is what a CI gate and a paper appendix need.
2. **The quality/validity split is explicit in the data model**, not implied by colour.
   A high-null-rate column and a test-set member that used to be in train are different kinds of
   problem here (spec section 220).
3. **Evidence is the unit of output.** `DD003-0001` names the sample ids, the digests and the
   counts, so a reviewer can re-open the file. `evidence_type` + `confidence` label which
   findings are measured and which are heuristics (DD007/DD008/DD021 never pretend to be certain).
4. **Dataset fingerprint + diff as a first-class object.** Snapshots live in the dataset,
   `--baseline` yields DD018/DD019, and a row crossing into `test` is `CRITICAL`/`BLOCKING`.
   Versioning tools do not ask whether the change matters to the metric; audit tools do not
   version.
5. **Runs where the audit is actually needed**: no GPU, no API key, no cloud, no model, no
   database, no Docker; read-only by default; exit codes `0/1/2/3` for CI.

## Claims we do not make

- **No detection-rate claim.** We have not measured precision/recall against a labelled
  leakage benchmark, and the fixtures in `examples/` are hand-planted, so their pass/fail
  behaviour demonstrates wiring, not accuracy. Any future number must come from a real run and be
  published with its protocol.
- **"Nobody else detects leakage" is false** (see FiftyOne Brain above, and Cleanlab's label
  noise). The claim is about the packaging: deterministic, dependency-light, verdict-bearing.
- **Semantic leakage is out of reach.** The Limitations section states this verbatim, as required
  by spec section 153.
- **Profiling is not a substitute, and we are not a better profiler.** `ydata-profiling` produces
  richer EDA than we do on purpose; we produce fewer, sharper, gate-able statements.
- Neighbouring tools may have added leakage checks after 2026-09-21. Re-check before each release
  note, and record the date of any comparison.

## How the positioning shows up in the deliverables

- `README.md` first screen: the leakage hook plus one measured example, no invented comparisons.
- `docs/METHODOLOGY.md`: the thresholds and formulae behind every finding.
- `docs/PROJECT_STATE.md`: which rules are heuristic, which are untested, and the open ambiguities.
- `docs/rules/*.md`: per rule, the *measured* output of a real run, false-positive conditions, and
  what the evidence keys mean.
