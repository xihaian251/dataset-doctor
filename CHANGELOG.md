# Changelog

All notable changes to Dataset Doctor are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses semantic versioning.

## Unreleased

Everything between 0.1.0 and here is verification, not behaviour: no rule id, default severity or
`formal_impact` changed. Two release-blocking *packaging* defects were fixed, listed under Fixed.

### Added

- Test coverage for the gaps recorded in `docs/PROJECT_STATE.md` section 6: named assertions for
  DD001 (by rule id), DD008 (threshold, name-vs-cardinality severity, declared-key exemption,
  per-column dedup), DD013 (TV effect size, `min_tv_distance` policy wiring), DD017 (shift
  detection, metadata-mode INCONCLUSIVE, tabular UNSUPPORTED), DD020 (all three branches),
  DD021 (`min_match_ratio` boundary, cross-split dedup with per-split ratio, NOT_RUN,
  UNSUPPORTED), `--fingerprint sampled` (limitation text, subset integrity, run-to-run
  determinism), the `imagehash`-absent degradation of DD004, and an `examples/build.py`
  smoke test.
- `docs/DEEP_RESEARCH_PHASE0.md`: the Phase-0 research report in prose - the survey method, the
  findings behind each design decision, and the pHash indexing analysis (spec section 88). The
  COMPETITIVE_ANALYSIS fact table remains authoritative.
- **`tests/test_docs_contract.py`** (12 checks / 94 items): the documents are now a tested surface.
  Per rule it compares the front table (title, Category, Default severity, Formal impact, Evidence
  type, Applies to, `In V0.1 rule set`) with `rules.REGISTRY`, and the Detector row with the
  function `audit.DETECTORS` actually wires; it rejects a documented source line number, checks the
  README's leakage table wording and its link targets, re-derives `examples/RESULTS.md` from live
  audits and byte-compares it, reproduces the README's demo block and its quoted finding from real
  runs, and measures which rules `--fingerprint metadata` / `sampled` actually cost. It adds no
  number to the spec TEST register; it audits the prose.
- Assertions that state verdict *semantics* rather than spellings: DD003's cross-split duplicate is
  `AuditStatus.FAIL` + `FormalImpact.BLOCKING`, DD010 separates unlabelled rows by which side of
  the evaluation boundary they sit on, DD015/DD021 pin their own rule ids and their `UNSUPPORTED`
  branch ("we did not look" can no longer be read as "we looked and it is fine").
- Release engineering, **written but never executed** (there is no remote yet):
  `.github/workflows/ci.yml` - static gates on 3.12, `pytest` on 3.11/3.12/3.13 across Ubuntu and
  Windows with the scale test held off, and `python -m build` followed by an audit run through the
  installed wheel; no publish step, no package-index upload, no tag trigger. Plus
  `.github/ISSUE_TEMPLATE/` (`crash`, `wrong-verdict`, `ABOUT.md`), `.github/PULL_REQUEST_TEMPLATE.md`
  and `docs/RELEASE_CHECKLIST.md` - the last one separating what a local run can prove from the
  decisions (copyright holder, `[project.urls]`, private vulnerability reporting, version string)
  that need a person.

### Fixed

- **A fresh clone could not run.** An unanchored `reports/` pattern in `.gitignore` matched
  `dataset_doctor/reports/`, so four report-writer modules were never committed and the first
  command of a new checkout raised `ImportError`. The patterns are now anchored and
  `tests/test_packaging.py` asks *git* whether every source module is tracked and unignored.
- `pyproject.toml` declares the licence with the PEP 639 expression (`License-Expression:
  Apache-2.0`, verified in the built wheel) instead of the deprecated table form, the sdist now
  carries `LICENSE` (Apache-2.0 §4 asks that of a redistributed work), the unfilled Apache
  boilerplate in the licence header is replaced, and `.gitattributes` pins LF for text fixtures so
  a fingerprint does not depend on the line endings a clone happened to choose.
- **Reported data paths are relative again.** `SECURITY.md` claimed it; three places wrote the
  caller's absolute path anyway (the tabular adapter's unreadable-file entries and DD002's shared
  -path finding). The grouping key stays resolved, the printed evidence is relative, and
  `tests/test_privacy.py` asserts the invariant over the fixtures and all three renderers by
  walking the dumped values - a leaked `C:\` is JSON-escaped, so grepping the serialised text
  would have certified the leak as clean. `identity.root_path` and the repair plan's paste-ready
  commands are named exceptions.
- README claims that had drifted from behaviour, rewritten from measured runs rather than by hand:
  the distribution-shift block (it quoted a finding format the CLI no longer renders), the
  attribution of the sample finding, and the fingerprint-mode paragraph (measured cost: `metadata`
  loses {DD003, DD004, DD009, DD016, DD017} on an image fixture and {DD003} on a tabular one;
  `sampled` loses no rule coverage on the shipped fixtures).
- `dataset-doctor-report/`, the directory `audit` writes when no `-o` is given, added to
  `.gitignore`; `(line NNN)` citations removed from `docs/rules/DD020` and `DD021`.
- `CONTRIBUTING.md` corrected on three points: the gate list now matches what CI runs and says the
  workflow has never run; the `pytest -q` note explains that `addopts` already carries `-q`, so
  `pytest -q` means `-qq` and prints no summary line; heuristic confidences are stated per rule
  (DD004 `MEDIUM` capped, DD008 `MEDIUM`/`LOW` by branch, DD021 `LOW`) instead of a blanket
  `LOW`, and the rule-registration steps name `requires` as the modality discriminator that
  `applies_to` is not. `SECURITY.md`'s reporting route points at GitHub's private-vulnerability
  form once the repository exists, and says plainly that there is no disclosure timeline, no CNA
  relationship and no security team.

Suite: 153 test functions / 242 collected items → **212 passed, 30 skipped in 56 s** (2026-09-22,
Python 3.13.1; every skip is the opt-in scale test or a documentation check for a rule that makes
no such claim). `ruff format --check .` (103 files), `ruff check .`, `mypy dataset_doctor`
(32 files) clean; wheel build checked locally. The 48 000-file scale test was **not** run in this
round - it needs `DATASET_DOCTOR_SCALE=1` and about five minutes.

## 0.1.0 - 2026-09-21

First release. Local-first ML dataset audit CLI: `Detect Data Leakage Before It Corrupts Your ML
Experiment`. Read-only by default, no LLM, no network, no GPU, evidence attached to every verdict.

### Added

- **21 audit rules, DD001-DD021**, each with a per-rule document in `docs/rules/` containing
  measured output from a real run, false-positive conditions, severity table and remediation.
  Leakage first: exact duplicates (DD003), near duplicates by perceptual hash (DD004), entity/group
  leakage (DD005), temporal leakage (DD006), target-leakage candidates with FDR control (DD007),
  identifier leakage (DD008), label conflict (DD009). Integrity and drift: split integrity (DD002),
  missing labels (DD010), class imbalance (DD011), feature shift (DD012), label shift (DD013),
  schema drift (DD014), missingness shift (DD015), corrupt samples (DD016), image property shift
  (DD017), version drift (DD018), split drift (DD019), provenance (DD020), PII candidates (DD021).
- **Formal evaluation safety verdict** - `FORMAL_EVAL_SAFE / RISKY / INVALID / INCONCLUSIVE`, from
  per-finding `formal_impact ∈ {NONE, POTENTIAL, BLOCKING}`. No health score exists. A coverage gap
  on a V0.1 priority rule cannot be printed over with `SAFE`.
- **Dataset fingerprint and diff**: `metadata` / `sampled` / `full` fingerprint modes, snapshots
  stored inside the dataset under `.dataset-doctor/snapshots/`, `audit --baseline`,
  `dataset-doctor snapshot`, and `dataset-doctor diff` with finding-level new/resolved/changed
  comparison.
- **Adapters** for tabular (CSV/TSV/Parquet/Excel incl. multi-sheet workbooks, one split per file
  or per column) and image folders (train/val/test layouts, label-from-directory), plus layout
  discovery that reports what it inferred instead of pretending it was declared.
- **Reports** in `report.json` (frozen field set), Markdown, and self-contained HTML.
- **Commands**: `audit`, `scan`, `init`, `split` (group-aware, writes only into a new empty
  target), `snapshot`, `diff`, `fingerprint`, `report`, `rules`, `show`, `demo`.
- **CI gating** via exit codes: `0` ok, `1` findings gate tripped, `2` bad request, `3` internal
  error, `130` interrupted; `--ci`, `--strict`, `--fail-on <severity>`.
- **13 example fixtures** with `PLANTED_FAULTS.md` and a regenerated `examples/RESULTS.md`; three
  generated demo datasets via `dataset-doctor demo`.
- 114 test functions / 118 items covering all 37 spec test cases plus discovery, splitting and
  example-fixture wiring; `ruff`, `mypy` clean.
- Documentation set: `docs/METHODOLOGY.md`, `docs/PROJECT_STATE.md`,
  `docs/COMPETITIVE_ANALYSIS.md`, six ADRs, `AGENTS.md`, `SECURITY.md`, `ROADMAP.md`,
  `CONTRIBUTING.md`.

### Changed

- Distribution name is `dataset-doctor-audit` while the CLI stays `dataset-doctor`: `dataset-doctor`
  is already taken on PyPI by an unrelated auto-cleaning package. Documented in the README and
  ADR 0006.

### Fixed (found while writing the rule documentation, all regression-tested)

- Sample ids and reported paths are now computed from resolved roots, so `audit ./data` and
  `audit /abs/data` produce the same manifest hash and a report no longer carries the caller's
  absolute data path (DD018/DD019 depend on this).
- DD016 no longer overstates coverage: with `--fingerprint metadata` it reports a lower bound,
  counts files it never opened, and returns `INCONCLUSIVE` instead of a clean-looking number.
- `finding_changes` no longer reports baseline findings as resolved when one side of a diff was
  never audited; an audit run leaves the field empty and says why.
- DD018/DD019 evidence rows resolve to openable references (`file::id-value`) instead of bare
  content hashes.
- DD012's Benjamini-Hochberg flags can no longer land on the wrong column's evidence.

### Known limitations

- Semantic leakage cannot be fully automated. Near duplicate thresholds are dataset-dependent.
  Distribution shift does not automatically mean invalid evaluation.
- No test referenced DD001, DD008, DD013, DD017 or DD020, and DD021 had one test; see
  `docs/PROJECT_STATE.md` section 6. (Closed 2026-09-22 - Unreleased above.)
- Not yet published to PyPI, and no hosted repository: `[project.urls]` is intentionally absent
  until both exist.
