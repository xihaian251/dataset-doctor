# Changelog

All notable changes to Dataset Doctor are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses semantic versioning.

## Unreleased

### Added

- Test coverage for the gaps recorded in `docs/PROJECT_STATE.md` section 6: named assertions for
  DD001 (by rule id), DD008 (threshold, name-vs-cardinality severity, declared-key exemption,
  per-column dedup), DD013 (TV effect size, `min_tv_distance` policy wiring), DD017 (shift
  detection, metadata-mode INCONCLUSIVE, tabular UNSUPPORTED), DD020 (all three branches),
  DD021 (`min_match_ratio` boundary, cross-split dedup with per-split ratio, NOT_RUN,
  UNSUPPORTED), `--fingerprint sampled` (limitation text, subset integrity, run-to-run
  determinism), the `imagehash`-absent degradation of DD004, and an `examples/build.py`
  smoke test. 126 test functions / 134 collected items, gates green.
- `docs/DEEP_RESEARCH_PHASE0.md`: the Phase-0 research report in prose - the survey method, the
  findings behind each design decision, and the pHash indexing analysis (spec section 88). The
  COMPETITIVE_ANALYSIS fact table remains authoritative.

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
- No test references DD001, DD008, DD013, DD017 or DD020, and DD021 has one test; see
  `docs/PROJECT_STATE.md` section 6.
- Not yet published to PyPI, and no hosted repository: `[project.urls]` is intentionally absent
  until both exist.
