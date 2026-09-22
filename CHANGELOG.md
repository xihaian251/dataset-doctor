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
- Release engineering, **written but never executed** (written while there was no remote; the remote
  exists now and carries no commits, so nothing in this bullet has run either):
  `.github/workflows/ci.yml` - static gates on 3.12, `pytest` on 3.11/3.12/3.13 across Ubuntu and
  Windows with the scale test held off, and `python -m build` followed by an audit run through the
  installed wheel; no publish step, no package-index upload, no tag trigger. Plus
  `.github/ISSUE_TEMPLATE/` (`crash`, `wrong-verdict`, `ABOUT.md`), `.github/PULL_REQUEST_TEMPLATE.md`
  and `docs/RELEASE_CHECKLIST.md` - the last one separating what a local run can prove from the
  decisions (copyright holder, `[project.urls]`, private vulnerability reporting, version string)
  that need a person.

### Changed

- **Installed identity: `dataset-doctor` → `dataset-doctor-audit` everywhere a namespace is
  installed.** The distribution, the importable package (`dataset_doctor` → `dataset_doctor_audit`,
  including the source directory) and the console script all carry the `-audit` suffix now, because
  re-inspection of the unrelated PyPI `dataset-doctor` 1.0.1 wheel showed it ships *both* the
  top-level package `dataset_doctor` and the `dataset-doctor` script — two wheels writing into the
  same `site-packages` paths, last install wins. ADR 0006 records the widening; A16 is the register
  entry. What deliberately keeps the short brand name: `dataset-doctor.yaml`, `.dataset-doctor/`,
  `dataset-doctor-report/`, and "Dataset Doctor" in prose. No rule id, severity, `formal_impact`,
  report schema or persisted-cache format changed, and the on-disk state that survives between
  runs (manifests, snapshots) stores only `schema_version`, so no user cache is invalidated. Every
  quoted CLI invocation in the rule documents and the README was re-measured afterwards.
- **Publication metadata now states who owns the project and where it lives.** No behaviour change:
  no detector, rule, threshold, CLI surface or dependency moved. `LICENSE`'s appendix line reads
  `Copyright 2026 冯硕` in place of the `Dataset Doctor contributors` placeholder, with the Apache-2.0
  licence text itself untouched. `pyproject.toml` gains `[project.urls]` (`Homepage`, `Repository`,
  `Issues`) pointing at `github.com/xihaian251/dataset-doctor`, the public repository created
  2026-09-22 and configured as `origin`; `name`, `version`, `requires-python` and the dependency
  ranges are unchanged, so the three installed namespaces stay `dataset-doctor-audit` /
  `dataset_doctor_audit` / `dataset-doctor-audit` while the brand-level artifacts
  (`dataset-doctor.yaml`, `.dataset-doctor/`, `dataset-doctor-report/`) keep the short name.
  `SECURITY.md`'s reporting section now names that repository's security page, states that an unfixed
  vulnerability must not be disclosed through a public issue, and says plainly that private
  vulnerability reporting is **not** claimed to be enabled — it needs a repository administrator to
  turn it on, and the setting cannot be read while the remote holds no commits. No contact address was
  invented to paper over that gap; until the form is live there is no private intake channel, and the
  document now says so. One item was deliberately left alone: `pyproject.toml`'s `authors` still
  carries the collective label, which is a credit line rather than a copyright assertion, and
  `docs/RELEASE_CHECKLIST.md` section 3 registers it as a maintainer decision.

### Fixed

- **Two defects the identity migration itself introduced, both found by auditing every changed
  line against a pure token substitution rather than by the test suite.** `_find_config` and
  `splitting._carry_config` lost their `dataset-doctor.yml` candidate (both lists ended up with
  `dataset-doctor.yaml` twice), so a dataset whose config used the short extension stopped being
  discovered - silently, because no test had covered that spelling; the new
  `test_a_config_spelt_dot_yml_is_still_discovered_and_its_declarations_apply` fails when the
  candidate is deleted, which is how both directions were checked. And the Apache `LICENSE` text
  gained characters on its header URL line, which matters because section 4 requires the
  unmodified text to travel with a redistributed work; it is byte-identical to
  `www.apache.org/licenses/LICENSE-2.0.txt` again except for the copyright line.
- **A test fixture embedded the developer's own Windows username** (`C:\Users\<name>\...`) in cell
  data. The path is fabricated either way - the test is about backslashes surviving the CSV layer -
  so it now uses `C:\Users\example\`, and neither archive ships a real account name. Scanning the
  rebuilt sdist then caught the one remaining machine-named path, in `DD018`'s worked example, where
  the account name had been masked but the rest of the author's workspace was still visible; it is
  genericised too. What the scan still reports is the literal string `C:\Users` inside prose and
  fixtures that are *about* Windows path handling, which is not a leak and cannot be removed.
- `.github/workflows/ci.yml` ran `python -m build` but never validated the two artefacts it made.
  `twine check dist/*` is now a CI step, so a README that fails to render or a licence file missing
  from the sdist is caught on every push rather than at release time.

- **A fresh clone could not run.** An unanchored `reports/` pattern in `.gitignore` matched
  `dataset_doctor/reports/` (the package's name before the identity change above), so four
  report-writer modules were never committed and the first
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
no such claim). `ruff format --check .` (103 files), `ruff check .`, `mypy dataset_doctor_audit`
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
  `dataset-doctor-audit snapshot`, and `dataset-doctor-audit diff` with finding-level new/resolved/changed
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
  generated demo datasets via `dataset-doctor-audit demo`.
- 114 test functions / 118 items covering all 37 spec test cases plus discovery, splitting and
  example-fixture wiring; `ruff`, `mypy` clean.
- Documentation set: `docs/METHODOLOGY.md`, `docs/PROJECT_STATE.md`,
  `docs/COMPETITIVE_ANALYSIS.md`, six ADRs, `AGENTS.md`, `SECURITY.md`, `ROADMAP.md`,
  `CONTRIBUTING.md`.

### Changed

- Distribution name is `dataset-doctor-audit` while the CLI stays `dataset-doctor-audit`: `dataset-doctor-audit`
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
