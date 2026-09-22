# Deep Research Report - Phase 0

**Dataset Doctor v0.1** · written 2026-09-22 from the research log of 2026-09-20/21.

This is the prose companion to `docs/COMPETITIVE_ANALYSIS.md`. That file is the fact table -
versions, licenses, commands, DOIs, all re-read from primary sources on 2026-09-21. This file is
the *reasoning*: what question we set out to answer, how the landscape answers it, and which
design decisions each finding produced. Where the two files disagree, the fact table wins and
this file is a bug.

Every external claim below is traceable to an entry in `COMPETITIVE_ANALYSIS.md` or to a
primary-source document in this repository. Nothing here was added after 2026-09-21 without
re-verification, and the "what we refuse to claim" section is binding for all downstream copy.

---

## 1. The research question

The master spec (sections 118, 160, 161) framed Phase 0 as a survey of eight tool families -
Great Expectations, Evidently, ydata-profiling, Cleanlab, DVC, FiftyOne, data-leakage tooling,
and image-duplicate tooling - with an explicit purpose: *not to copy*, but to establish whether
"ML evaluation safety" is a real gap or a relabelled existing product. The question this report
answers is therefore narrow on purpose:

> Does a tool exist whose job is to decide whether a dataset can support a trustworthy formal
> evaluation - with a verdict, evidence, and a CI exit code - or would Dataset Doctor be the
> first thing shaped like that?

A secondary question came from the spec's own hedges (sections 69, 88, 103, 153): which of our
headline features have prior art we must differentiate from honestly (pHash indexing, leakage
detection, licensing), and which numbers we are allowed to print at all.

## 2. Method

- **Tool inventory**: for each candidate, the PyPI project metadata on 2026-09-21 supplied the
  version and SPDX license; the tool's own documentation or paper supplied the capability
  description. Where metadata declares no license, the table says so rather than guessing
  (fiftyone-brain, text-dedup, cleanvision).
- **Live behaviour checks**: the name-collision investigation went one step further than
  metadata - the competing `dataset-doctor-audit` package's command surface (`diagnose/report/clean/
  display/show/init-config`) was enumerated, because "what is the *other* tool's contract" is
  exactly the kind of claim a README will be held to.
- **Literature**: four citation anchors ( Kapoor & Narayanan; Northcutt et al. ×2; Kaufman et
  al.; Elangovan et al.) were verified by DOI/arXiv. A medical-ML figure seen during the survey
  could not be confirmed to a primary source, so it is listed as *not cited* - see §6.
- **Feasibility probes**: near-duplicate indexing (§5) and the fingerprint/diff design (§4.4)
  were researched against our own constraints (no database, no daemon, 48 000-file budget)
  before the implementation choice was recorded in `docs/METHODOLOGY.md`.

## 3. What the landscape actually is

Five families emerged, and none of them is "an audit that can say *no*".

**Expectation validators** (Great Expectations, and the pandas-visualisation-adjacent suite
genre) answer *"did the data meet the contract I declared last month?"*. They are pass/fail by
construction - but the contract is human-authored, and nothing in the genre asks whether the
splits themselves are sound. This is where our **fact/verdict separation** (§4.1) departs: an
expectation suite encodes judgement *up front*; we emit measured facts and let one policy layer
judge them after the fact.

**Monitoring/report dashboards** (Evidently) compare a reference against a current window and
render charts. They normalized "drift" as a first-class object; we adopted the effect-size
discipline (SMD/PSI with supporting KS, METHODOLOGY) but rejected the output form: a dashboard
has no exit code.

**Profilers** (ydata-profiling) produce an exhaustive EDA document - including sample *rows*,
which we deliberately never put in a report (privacy: counts, ids, statistics only). The
research conclusion here was defensive: a profiler is *richer* on purpose, and our differentiator
is fewer, sharper, gate-able statements, not coverage.

**Label-noise detectors** (Cleanlab, built on confident learning - Northcutt et al.) find suspect
labels from out-of-sample predicted probabilities. That input does not exist at audit time
(there may be no trained model), so DD009/DD010 measure what *is* observable from bytes: label
conflict on identical content, and label absence. The literature review is what drew this line.

**Version managers** (DVC, and the snapshot genre) answer *"what changed?"* but never *"does the
change invalidate the metric?"*. That half-empty intersection is the direct motivation for
DD018/DD019: our diff stamps `CRITICAL`/`BLOCKING` on a row crossing into `test`, which a
`dvc diff` reports as a rename or an edit indistinguishable from a harmless one.

**The one genuine overlap** is FiftyOne Brain's `compute_leaky_splits()` for images - it exists,
it works, and pretending otherwise would have been the fastest way to lose credibility. The
differentiation the research settled on is *not* capability but packaging and coverage: it needs
MongoDB and embeddings (hence a model), it lives inside a viewer, and it has no gate semantics.
Our claim, checked against it, is: deterministic digest matching in one `pip install`, no
database/GPU/API key, tabular *and* images, plus entity/temporal/label-conflict checks the
vision tool does not have - and we say "the one real overlap" in our own docs, because that is
honest and it survives contact with their documentation.

## 4. Findings that changed the design

### 4.1 No tool adjudicates - so the verdict is the product

Every surveyed tool *reports*; none returns a four-valued statement about formal-evaluation
validity with per-finding `formal_impact ∈ {NONE, POTENTIAL, BLOCKING}`. This finding is the
reason ADR 0003 exists ("leakage-first, never a score"): once you accept that the output is a
*judgement*, the coverage-gap semantics follow immediately - an INCONCLUSIVE on a V0.1-core rule
must stop a `SAFE` from printing (TEST 30), and a health score would destroy exactly the
distinction we built the product to make.

### 4.2 Evidence is the unit reviewers ask for

The leakage literature (Kapoor & Narayanan's reproducibility argument; Kaufman et al.'s formal
treatment of prediction-time leakage) is written as *cases*: a named experiment, a named defect.
Audits that emit "37 issues found" cannot support that conversation. Hence ADR 0002: every
finding carries a re-openable evidence block (`DD003-0001` style ids, sample ids, digests,
counts), heuristic rules self-label (`EvidenceType.HEURISTIC` + low confidence - DD007/DD008/
DD021 never pretend to be certain), and the report groups by evaluation validity first.

### 4.3 The dependency floor *is* the feature

FiftyOne-on-MongoDB and Cleanlab-on-probabilities are not sloppier - they are different trades.
But the survey confirmed no tool in the leakage space runs on a locked-down laptop with no GPU,
no key and no daemon, and that *is* where most audits must happen (student projects, hospital
VPCs, CI runners). This inverted the usual reading of the spec's prohibitions: ADR 0004 records
"no network, no model" as a positive capability claim, with TEST 22/23 as its proof.

### 4.4 Fingerprints: DVC told us where not to put them

Snapshot storage in the surveyed tools lives in a sidecar directory (`dvc`-style) or a remote.
We chose the opposite (ADR 0005): snapshots travel *inside* the dataset under
`.dataset-doctor/snapshots/`, because the unit of comparison is a dataset, not a repo, and an
audit handed over as a folder must keep its baseline. The three fingerprint modes
(metadata/sampled/full) and the sampled-mode limitation text (now asserted by
`test_fingerprint_sampled_declares_its_coverage_and_is_deterministic`) exist so that a cheaper
hash is never silently presented as a complete integrity claim - spec section 17.

### 4.5 Naming and licensing came out of the survey, not the roadmap

Two findings were pure research output:

1. **`dataset-doctor` is taken on PyPI** (MIT, 1.0.1, an auto-*cleaning* tool whose `clean`
   command edits data - the exact opposite of our read-only non-negotiable). Distribution name
   became `dataset-doctor-audit`; the brand and the config-file names stayed short. On
   2026-09-22 the wheel was re-inspected and found to ship the import package `dataset_doctor`
   and the console script `dataset-doctor` as well, so all three of our namespaces now carry the
   `-audit` suffix (ADR 0006 amendment, register entry A16).
2. **Apache-2.0 over MIT** because the ecosystem our users arrive from (GX, Evidently, Cleanlab,
   DVC, FiftyOne) is Apache-2.0 and the patent grant matters for a tool that formalises a
   method (A3).

## 5. pHash indexing (spec section 88)

The spec demanded research, not a guess, on "bucket / BK-tree / other Hamming indexing". The
three options were weighed against the actual workload (≤48 000 images, threshold ≤ ~10 bits,
single machine, no C extensions):

| Option | Verdict |
| --- | --- |
| Linear O(N²) | fine to ~5 000 samples; 48 000 files would mean ~1.2 billion pair comparisons - rejected per the spec's own "don't over-engineer, but do the one expensive thing right" |
| BK-tree | correct and simple, but degenerate at small thresholds over dense hash populations, and the traversal cost is data-dependent |
| **Exact-match bit-band candidate generation** (chosen) | split the 64 bits into `threshold + 1` bands; two hashes within Hamming distance ≤ t must collide exactly in at least one band (pigeonhole), so the candidate set is a *provable superset* - no recall loss, only bucket-size cost, and truncation above `max_bucket_size` is itself reported as a limitation |

The superset property is the reason the shipped report can state, in its METHODOLOGY block, that
"coverage loss is only from bucket truncation, which is itself reported" - an approximation
guarantee we can give without measuring a recall number, which we are not entitled to state (§6).
Implemented in `_band_candidates` (`detectors/duplicates.py`); TEST 31 pins the threshold boundary.

## 6. What we refuse to claim, and why

- **No detection-rate numbers.** Nothing surveyed has a labelled leakage benchmark either, and
  our fixtures are hand-planted - they prove wiring, not accuracy. A future number must come
  with a protocol (COMPETITIVE_ANALYSIS, "Claims we do not make").
- **The "~90 of 100 medical-ML studies have leakage" figure** circulated during the survey could
  not be traced to a verifiable primary source, so it appears nowhere in this project - not in
  the README, not here. The adjacent PubMed records we *did* check are listed in
  COMPETITIVE_ANALYSIS.
- **Kapoor & Narayanan's paper counts differ between versions** (journal: 17 fields / 294
  papers; preprint: 329). We cite journal numbers only, and never enumerate their typology
  beyond the abstract.
- **Semantic leakage is undetectable from bytes** (spec section 153 Limitation 1). DD007/DD008/
  DD021 emit *candidates* with stated confidence; the report's language ("POTENTIAL_PII_COLUMN",
  "IDENTIFIER_FEATURE_CANDIDATE") is the research finding made visible.
- **Comparisons expire.** All tool facts above carry the date 2026-09-21; the release-note
  checklist requires re-checking before each version.

## 7. Verdict of the research

The gap is real but narrow, and its name is not "leakage detection" - FiftyOne Brain already
does that for images. The unoccupied position is the *adjudicating
audit*: evidence-bearing, verdict-bearing, gate-able, dependency-floor-zero, honest about being
heuristic where it is heuristic. Every core design decision in `docs/adr/0001-0006` traces to a
finding in this file or its fact table. Had the survey found a tool already in that position,
the correct Phase-0 output would have been "don't build it" - it didn't, so we built it, and
this report is the receipt.

---

*Sources of record*: `docs/COMPETITIVE_ANALYSIS.md` (fact table, 2026-09-21),
`docs/METHODOLOGY.md` (thresholds and formulae), `docs/adr/0001-0006` (decisions),
`docs/PROJECT_STATE.md` section 3 (ambiguity register A3/A16/A18) and section 8 (prohibitions).
