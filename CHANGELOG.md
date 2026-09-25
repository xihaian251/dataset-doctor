# Changelog

All notable changes to Dataset Doctor are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project uses semantic versioning.

## Unreleased

### Known issues registered by the first real-world acceptance (UCI Adult), not fixed here

- **A dataset whose files carry no recognised extension is declared a table and then audited as
  images.** Reproduced on this commit with UCI Adult's own names - `adult.data` and `adult.test`
  mapped by `splits:` in `dataset-doctor.yaml`, nothing else changed: the audit ends
  `FORMAL_EVAL_RISKY`, 2 samples / 21 rules, with `HIGH` DD016 "Unreadable or corrupt images: 2 of
  2" (`identifiers`: `adult.data`, `adult.test`) and `HIGH` DD010 "Unlabelled samples: 2 of 2", and
  its repair plan tells the user to `mv adult.data adult.test` into a quarantine directory and
  "re-download or re-export the listed files". The two files are intact; 32 561 and 16 281 rows
  parse out of them one directory level up, where the same bytes carry `.csv`.
  Root cause is one function disagreeing with itself: `discovery._type_from_paths` counts only
  suffixes, so with neither a tabular nor an image extension present both hit counters are 0, the
  note it appends reads `Dataset type inferred from content (tables)` because `0 >= 0`, and the
  value it returns is `DatasetType.IMAGE` because the return guards on `table_hits` being nonzero.
  Everything downstream then takes the image branch, and DD016 - which is a real rule about pixels -
  reports a defect that does not exist.
  Not fixed in this run because the honest repair is a decision, not a patch: either the type model
  gains a third answer ("unresolved", which rules must then answer INCONCLUSIVE for) or discovery
  sniffs content instead of names, and that sniff is what would make `scan` of a raw UCI download
  work with zero configuration. Both change coverage semantics beyond a wording fix.
- **A headerless CSV has no way to say so, and nothing in the report says the parse guessed.**
  Same bytes, only the extension differs: `adult.data` / `adult.test` copied to `train.csv` /
  `test.csv` with no edit is read by `pandas.read_csv` with its default first-row-as-header.
  Measured directly: `train.csv` becomes 32 560 rows × 15 columns whose names are the first
  record's values, and `test.csv` becomes 16 281 rows × **1** column named `|1x3 Cross validator` -
  `adult.test` opens with that `|`-delimited marker line, and it is what pandas used as the header,
  leaving every 15-field record to collapse into one column. The audit then reports 48 841 samples, one short of the official 48 842, with
  `HIGH / FAIL` DD014
  "Schema mismatch between test and train" (15 columns extra in test, 3 missing), and DD003 finding
  333 duplicate groups / 15 970 samples inside `test` where the identical rows under a real header
  give 5 groups / 10 samples - the split had collapsed to two distinct values. DD014 alone is
  BLOCKING, so the verdict is `FORMAL_EVAL_INVALID` on a split that is the official one. Neither
  `adapter_notes` nor `config_warnings` recorded anything about it. There is no `header:` key in
  `dataset-doctor.yaml` or `docs/guides/CONFIGURATION.md`, so the only way out is to materialise a
  header row into the user's data - an edit the tool itself never makes.
  Registered, not fixed: the fix is a parsing contract (`parse.header` / explicit `columns:`, and
  the dtype inference that follows) plus a decision about whether a guessed parse may block, which
  is a release, not a patch inside an acceptance run.

### Fixed

- **DD013 reported `PASS` for every image dataset, including the official MVTec AD archives.**
  `_label_counts` asked for a table frame before it looked anywhere else, and returned `{}` when a
  split had none - which is every split of every `split/class/*.png` layout. Both halves of the
  comparison were therefore empty, `detect_label_shift` `continue`d over every target, and the rule
  published a PASS for a dataset whose labels it had enumerated fine for DD011. On the fourth
  real-world acceptance (MVTec AD `bottle` and `leather`, CC BY-NC-SA, audited with the published
  0.1.1 wheel) the independently measured total variation between train and test label
  proportions is 0.759 and 0.742 - the maximum this rule can express is 1.000 - and the report said
  nothing. Reproduced before fixing with a synthetic fixture in `tests/test_structure.py` (32x32
  tiles; train 8 images all `ok`, test 8 images split 2 `ok` + 6 `defect`, TV 0.75): the new test
  fails on the old code with `by_rule("DD013") == []`. After the fix MVTec `bottle` and `leather` each report one DD013-0001
  `HIGH` / `WARNING` / `POTENTIAL` with the measured TV and its `largest_movers`, both verdicts stay
  `FORMAL_EVAL_RISKY`, and the proportional-labels control fixture stays silent. `examples/safe_image`
  remains `FORMAL_EVAL_SAFE`, so the fallback does not manufacture shifts where the shares match; the
  image examples that do shift gained their DD013 rows in the regenerated `examples/RESULTS.md`.

## 0.1.1 - 2026-09-25

Real-world validation patch release, not a feature release. Every entry below was found by one of
the three real-world acceptance runs (UCI Adult, UCI HAR, UCI Online Retail II) driving the
installed 0.1.0 wheel, and reproduced on small synthetic fixtures inside this repository. No rule
id, default severity, `formal_impact`, threshold or verdict algorithm changed, and no rule was
added. Built and verified on Windows 11 / Python 3.13.1: `pytest` 231 passed, 30 skipped,
4 warnings in 59.91 s · `ruff format --check .` 107 files already formatted · `ruff check .`
All checks passed · `mypy --python-version=3.12 dataset_doctor_audit` no issues in 32 source
files.

### Documentation

- Post-release documentation now points to the published 0.1.0 package and the real repository.
  This does not change code, version metadata or the immutable 0.1.0 files on PyPI.

### Fixed

- **DD005 and DD006 could report a clean check on data they had not compared.** Found by the
  third real-world acceptance (UCI Online Retail II, 1 067 371 rows, through the installed
  0.1.0 wheel), and reproducible on 10-row synthetic fixtures, so this is a detector problem
  and not a quirk of one dataset. Two paths were silent in the same way: an entity column
  whose value is absent, and a declared time column that yields no comparable timestamps.
  - DD005 skipped null/empty entity values without counting them, so coverage was invisible
    in both directions. Measured on 0.1.0: a declared group column empty in every row
    reported `DD005 PASS`, 0 findings, `FORMAL_EVAL_SAFE`, exit 0 - the tool certified
    entity disjointness on zero evidence. A fixture where 20.4 % of rows were blanked and a
    known entity really did cross the boundary reported a bare `PASS` too, because "nothing I
    can see crosses" and "nothing crosses" printed the same.
  - DD006 coerced with `errors="coerce"` and then compared whatever survived. If nothing
    parsed, `violating = 0`, so the rule reported `PASS` with `skip_reason: null` and the
    verdict stayed `FORMAL_EVAL_SAFE` - on a config error, not on data.
  - Now rows carry `group_column_rows` / `rows_checked` / `rows_without_entity` /
    `entity_coverage_ratio` on every DD005 finding; zero usable entity values give one
    `HIGH` / `INCONCLUSIVE` / `BLOCKING` finding; partial coverage on an otherwise clean
    column gives a `LOW` / `NONE` advisory, which states the limit without asserting a risk
    it has not observed. DD006's four unmeasurable paths give the same
    `HIGH` / `INCONCLUSIVE` / `BLOCKING` finding, ending "This is not a PASS", and its
    comparison now checks that at least one train/test pair had timestamps on both sides.
    `INCONCLUSIVE` + `BLOCKING` is the combination `eval_safety` reads as "flagged as
    potentially invalidating, not confirmed", so both cases land at `INCONCLUSIVE`.
  - `tests/test_dd005_coverage.py` (6 checks) pins all of it, including the two directions
    that must not move: a disjoint fully-covered column still yields no DD005 finding, and a
    partially parseable time column still reaches a verdict rather than refusing.
    `tests/test_verdict_contract.py` pins the aggregation rule they depend on one level up: a
    `BLOCKING` check that returned no answer may never be summed into `FORMAL_EVAL_SAFE`,
    whichever rule failed to answer.
  - Nothing about a real detection changed. Re-auditing the million-row chronological split
    with `customer_id` declared gives byte-identical severity, status, `formal_impact`,
    `affected_count` (628 816 rows / 2 455 entities) and verdict; the finding additionally
    states `824364 of 1067371 rows (77.2%)`, matching an independent recomputation exactly.
    The two DD006 diagnostics on real data - the strict-chronological split (PASS) and the
    single known moved row (1 violating row, all five evidence fields) - are unchanged from
    0.1.0 field by field, and the no-group/no-label audit of the same data diffs to 0 fields.
    Cost at 1 067 371 rows: 143.5 s / 2 578 MB against 149.6 s / 2 583 MB (config A) and
    141.0 s / 2 746 MB against 148.3 s / 2 747 MB (config B).
- **DD005's row pointers named rows that do not hold the leaked entity.** The second
  real-world acceptance (UCI HAR, through the installed 0.1.0 wheel) found that a
  cross-split `affected_sample_ids` entry was `f"{split}:{i}"` for `i` in
  `range(row_count)` - a per-entity counter, not a position. On the official clean split
  everything else about DD005 checked out (entity count, per-split counts and the entity
  id all matched an independent recomputation), and on a subject whose rows happen to sit
  contiguously the counter can coincide with real row numbers; a four-row synthetic
  fixture with the entity placed at train rows 1 and 3 and test row 2 showed 0.1.0
  emitting `train:0, train:1, test:0` - every pointer a wrong row. A reviewer told to
  open `test:0` to see the leaked row is sent to an innocent one. Locators are now real
  0-based data-row positions collected while scanning the entity column, and the silent
  `[:200]` budget is declared: `affected_sample_ids_truncated` is present and true when
  rows were cut. Nothing about the finding's verdict inputs changed: severity, status,
  `formal_impact`, `affected_count`, description and evidence keys are byte-identical to
  0.1.0 on the same data (measured by re-auditing the HAR diagnostic fixture before and
  after). `tests/test_dd005_locators.py` pins both halves.
- **DD009 called a spelling difference a label conflict, and DD013 called it a distribution
  shift.** Found by the first acceptance run against an external dataset - UCI Adult, through the
  installed wheel rather than this tree. `adult.data` writes its classes `<=50K` / `>50K` and
  `adult.test` writes `<=50K.` / `>50K.`, so on 48 842 rows the tool reported 26 cross-split
  "conflicting labels" groups (CRITICAL, BLOCKING) of which 23 were that single trailing dot, and
  a `HIGH` label shift of `total variation 1.000` between two splits whose measured shift is
  0.0046. Every count and every number was arithmetically correct; the sentences attached to them
  were not, and the report blamed annotators for a separator convention while the real
  contradiction - 3 groups, 6 samples, exactly the `Duplicate or conflicting instances : 6` the
  dataset's own metadata states - was buried in the noise. Nothing about the consequence changed:
  a test set whose labels do not match the training vocabulary still blocks, because the mapping
  is a human decision. What changed is that the finding now says which of its own groups are
  punctuation.
  - DD009 adds `encoding_only_groups` and up to 5 `encoding_only_labels` pairs to its evidence, and
    its description names them, in all three scopes. Labels are still compared as exact strings and
    grouped exactly as before - normalising them would merge two classes a user's pipeline may keep
    apart, and that would be a silent edit of the user's data in the middle of a comparison.
  - DD013 adds `common_support_classes`, and when it is 0 the description states that the figure
    compares two vocabularies rather than two class proportions, and points at DD014, which names
    the one-sided categories. The number itself is untouched: genuinely disjoint classes deserve
    the same arithmetic.
  - `tests/test_label_encoding.py` (5 checks) pins both directions - a real `a`/`b` conflict must
    not gain the encoding sentence, a shared-vocabulary shift must not gain the vocabulary
    sentence - and holds severity, status, `formal_impact`, `affected_count` and the verdict to
    their released values on the same fixture, so a wording fix cannot smuggle in a weakening.
    Separately, re-auditing the Adult copy at this commit reproduces the 0.1.0 verdict, severities
    and counts exactly - measured: the two reports differ in nothing but the DD009 descriptions,
    evidence and limitations, the DD013 description and evidence, and wall-clock fields.
  - Registered but **not** fixed: because DD003 hashes the whole row including the label, this same
    punctuation difference hides the cross-split duplication it is standing on. Measured with only
    the trailing dot removed from `adult.test`, DD003 emits `CRITICAL / BLOCKING` for 23 content
    groups spanning train and test (48 samples) and DD013/DD014 go quiet. Changing what DD003
    treats as row identity is a rule-semantics decision for a release, not a patch inside an
    acceptance run - see PROJECT_STATE section 10 item 7.

## 0.1.0 - 2026-09-23

The final pre-release changes below were verification and packaging, not rule behaviour: no rule
id, default severity or `formal_impact` changed. Two release-blocking packaging defects were
fixed, listed under Fixed.

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
- Release engineering, written before the first push and subsequently exercised in CI:
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
  `SECURITY.md` names that repository's private vulnerability reporting form and forbids public
  disclosure of unfixed issues. The form was enabled after the first push, and no unverified
  contact address was invented. `pyproject.toml` names `冯硕` as the sole author, matching
  `LICENSE`; the earlier collective placeholder was removed before publication.

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
  `docs/PROJECT_STATE.md` section 6. (Closed 2026-09-22 - 0.1.0 Added above.)
