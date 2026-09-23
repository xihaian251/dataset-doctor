# Project State - Dataset Doctor v0.1

Last updated: 2026-09-22 (the measured figures below are from runs made on 2026-09-21 on the
authoring machine, Windows 11 / Python 3.13.1, unless a date is stated next to them).

This is the handoff document. It records what shipped, which decisions were taken and how
sensitive each was, what is *not* covered, and which numbers are real. Read it before changing a
threshold, a rule id, or a claim in the README.

---

## 1. Status

| Area | State |
| --- | --- |
| Package | `dataset-doctor-audit` 0.1.0, importable `dataset_doctor_audit`, CLI `dataset-doctor-audit` |
| Rules | DD001-DD021 implemented and registered (`rules.py`), 21/21 have `docs/rules/*.md` |
| Modalities | Tabular (CSV/TSV/Parquet/Excel incl. multi-sheet) + image folders |
| Reports | `report.json` (frozen field set), `report.md`, self-contained `report.html` |
| Commands | `audit`, `scan`, `init`, `split`, `snapshot`, `diff`, `fingerprint`, `report`, `rules`, `show`, `demo` |
| Exit codes | 0 ok · 1 findings gate · 2 usage/input error · 3 internal error · 130 on Ctrl+C |
| Fixtures | 13 in `examples/`, each with `PLANTED_FAULTS.md`; `examples/RESULTS.md` regenerates via `python examples/build.py` |
| Tests | 154 test functions / 243 collected items: 213 passed, 30 skipped, 1 warning in 74.66 s (2026-09-22 re-run after `29beb75`, Python 3.13.1, numpy 2.5.3, pandas 3.0.6, `pytest -o addopts="--tb=line -q"`; the run before it measured 86.99 s on the same command, so read ±15 s as machine load, not progress). Every skip is intentional: the opt-in scale test, plus parametrised documentation checks for rules that make no V0.1 or modality claim |
| Gates (2026-09-22) | `ruff format --check .` "103 files already formatted" · `ruff check .` "All checks passed!" · `mypy dataset_doctor_audit` "no issues found in 32 source files" · `pytest` green with the scale test skipped. mypy is green **only** with `numpy<2.5` installed: numpy 2.5.x vendors PEP 695 `type` statements that mypy 2.3.1 cannot parse while `python_version = "3.11"`, and the run aborts before it reaches our files. The CI static job installs that ceiling; a local `pip install -e ".[dev]"` still gets numpy 2.5.3, so run the type gate with the same ceiling until upstream resolves it |
| Release engineering | `.github/workflows/ci.yml`, issue/PR templates and `docs/RELEASE_CHECKLIST.md` are written but **unexecuted** - the remote now exists (created 2026-09-22) but holds no commits, so CI has never been green anywhere except locally |
| Not done | push to `origin`, PyPI upload, signed tag. `[project.urls]` are no longer on this list: they were added 2026-09-22 pointing at the new repository, which is public and still empty |

V0.1 rule set (`rules.py::V01_RULES`) is `V01_RULES = {DD001, DD002, DD003, DD005, DD009, DD011,
DD012, DD014, DD016, DD018, DD019}` - the leakage-critical surface named by spec section 69. It is
not a CLI switch: `rules.py::eval_safety` uses it so that an `INCONCLUSIVE` or `UNSUPPORTED`
outcome on one of those rules *in a gating category for this dataset type* keeps the verdict from
being printed `SAFE`. "Leakage-first" is therefore enforced in code, not just in the README. The
remaining ten rules are implemented and run by default; `NOT_RUN` deliberately stays out of that
gate (it encodes an off-switch, not a blocked measurement). DD004, DD006 and DD007 are absent from
the set although they are leakage rules - A20 records why. Source line numbers are not cited here
or in the rule documents for the same reason the docs-contract test rejects them: they move.

## 2. The two decisions everything else follows from

**Fact / verdict separation.** Detectors emit facts with a *proposed* severity;
`rules.apply_policy` and `_policy_severity` are the only places severity changes, and the verdict
is computed once:

> any `BLOCKING` finding ⇒ `INVALID`; a `MEDIUM`-or-worse `POTENTIAL` finding ⇒ `RISKY`; too many
> `INCONCLUSIVE` rules ⇒ `INCONCLUSIVE`; otherwise `SAFE`.

**`FormalImpact` is per finding, not per rule** (spec section 222). The same rule can emit
`BLOCKING` and `POTENTIAL` findings - DD019 does exactly that (split move vs relabel) - so
reading the registry alone never tells you what a finding does to the verdict.

### The `enabled` convention (repeat offender)

`policies.<rule>.enabled` is consulted by **nine** detectors only: DD004, DD006, DD011, DD012,
DD013, DD014, DD015, DD017, DD021. For DD001, DD002, DD003, DD005, DD007, DD008, DD009, DD010,
DD016, DD018, DD019, DD020 the *only* working knobs are `severity:` and `suppress:`. This is
asymmetric by design - integrity checks are not optional in a reliability audit - and it is
stated in each affected rule doc's Remediation section. If you add a rule, decide explicitly
which side of that line it is on and write it in the doc; do not "fix" the asymmetry silently.

## 3. Ambiguity register

Each entry: what was ambiguous, the reading chosen, why, and how much it matters.

| # | Ambiguity | Ruling | Sensitivity |
| --- | --- | --- | --- |
| A1 | Spec section 69 lists DD001-DD020; a PII rule was also required | Shipped as **DD021**, labelled an extension in its doc and in `rules.py` | Low - id only, no behaviour |
| A2 | Does `enabled: false` silence every rule? | No: nine detectors read it (section 2). Others use `severity`/`suppress` | **High** - a user who disables `exact_duplicate` still gets DD003 |
| A3 | License (spec: "Apache-2.0 or MIT, Phase 0 decides") | **Apache-2.0** - patent grant, and it matches GX / Evidently / Cleanlab / DVC, the ecosystem our users come from | Low-medium: MIT would be compatible with more derivatives, nothing else changes |
| A4 | Should the tool ever add a licence to a dataset? | Never (spec section 103). DD020 only reports what `dataset-doctor.yaml` declares | Low |
| A5 | A corrupt image in the test split: `BLOCKING` or not? | `HIGH` / `FAIL` but **`POTENTIAL`** - a broken file is a defect, not proof of leakage; the metric is re-run after the fix | Medium - it is the difference between a red and an unusable verdict |
| A6 | `--strict` vs `--ci` | `--strict` is a strict superset of `--ci`, never looser (`test_test34_strict_is_a_superset_of_ci...`) | Low |
| A7 | Should `--baseline` resolve snapshots written with `snapshot --directory`? | No. A snapshot lives inside the dataset it describes; the error message says so and points at `diff` | Low |
| A8 | DD014 with no reference split to compare against | Reports the asymmetry rather than inventing a baseline (`NOT_RUN` / limitation text) | Medium - silent comparison against "whatever looks like train" would be a fabricated reference |
| A9 | DD008 has a guard that can never fire given DD005's ordering | Kept, documented as redundant; removing it would couple two detectors | Low |
| A10 | DD017's 0.5 / 1.5 \|SMD\| floors | Literal in the detector, **not** policy-wired (unlike DD012) - and its doc says so | Medium: `policies.image_property_shift` currently only offers `enabled`/`severity` |
| A11 | DD019's `into_test` matches the literal split name `test`, not `SplitRole.TEST` | Kept, documented: a move into `val`/`eval` is `HIGH` instead of `CRITICAL` and still `BLOCKING` | Medium - severity only, verdict unchanged (measured, `_doccheck/vd_val`) |
| A12 | DD016 under `--fingerprint metadata`: 1 broken of 1 enumerated file | Fixed: unopened files are counted and the finding becomes a **lower bound** with `INCONCLUSIVE` + `limitations` | **High** for trust - this was an overclaim, not a wording issue |
| A13 | DD018's `finding_changes` during an audit | Diff runs before this run's findings exist ⇒ report it **empty** with a limitation, and refuse to compute new/resolved when a side has no `findings_digest` | **High** - the old behaviour claimed the baseline's problems were "resolved" |
| A14 | `Adapter.relative()` used unresolved roots | Fixed to resolve both sides (`base.py`), so `./data` and `/abs/data` produce identical sample ids | **High** for DD018/DD019: metadata-mode hashes used to depend on how the command was typed |
| A15 | Should reports carry absolute paths? | Only the diff's `right` label (a resolved path); every reported data path is relative | Medium - a report is shared, a machine path is not; hashes stay stable |
| A16 | `dataset-doctor` is already taken on PyPI (MIT 1.0.1, auto-cleaning tool); its wheel ships import package `dataset_doctor` and console script `dataset-doctor` | **All three namespaces suffixed** (2026-09-22 ADR 0006 amendment): distribution `dataset-doctor-audit`, import `dataset_doctor_audit`, CLI `dataset-doctor-audit`. Brand artefacts keep the short name (`dataset-doctor.yaml`, `.dataset-doctor/`, `dataset-doctor-report/`). Installing both projects is now cosmetic, not destructive | **High** for adoption - the spec's headline `pip install dataset-doctor` is not this tool, and our command is six characters longer |
| A17 | DD021 scanning several splits with the same column | `seen` set ⇒ one finding per `(column, pattern)`, attributed to the first split alphabetically; ratio is per split | Medium - `4 of 180` is not `4 of 240` |
| A18 | Near-duplicate Hamming threshold is dataset-dependent (spec section 153) | Kept configurable at 6, published as a Limitation verbatim | Low |
| A19 | Zero-variance columns in shift metrics \|SMD\| | Emitted as `inf` / `null` rather than clamped, and DD017's doc shows the measured pair | Medium - a clamped 0.0 would hide a degenerate column |
| A20 | `V01_RULES` omits DD004, DD006 and DD007 although all three sit in a gating category | The spec section 69 list is kept verbatim - it is the spec's ranking, not ours to re-make. Consequence, measured: an `INCONCLUSIVE` near-duplicate check (no `imagehash`) or an undeclared temporal column cannot block a `SAFE` verdict, while an `INCONCLUSIVE` DD003 can. `--strict` is the escape hatch: it fails on **any** inconclusive rule, V0.1 set or not | **High** - this is where "leakage-first" has a boundary, and a reader who assumes it does not will over-trust a `SAFE` |
| A21 | Does `NOT_RUN` belong in `core_gaps` alongside `INCONCLUSIVE` and `UNSUPPORTED`? | No. Here `NOT_RUN` encodes a deliberate off-switch (policy disabled, optional column never declared), not a blocked measurement; gating on it would leave most image datasets permanently `INCONCLUSIVE`. `--strict` does not add it either, by the same reasoning | Medium - it is the difference between a gate that complains about configuration and one that measures data |
| A22 | "Heuristic rules carry `LOW` confidence" | Not uniform, and now checked per rule instead of assumed: DD004 caps at `MEDIUM` (a pHash collision is arithmetic about pixels even though the threshold is a judgement), DD008 is `MEDIUM` for an identifier-named column and `LOW` for plain high cardinality, DD007's candidate layer and DD021 are `LOW`. Each rule document must state its own confidence, and `test_docs_contract.py` enforces that | Medium - the blanket version of the rule would misreport how much of each finding is arithmetic |
| A23 | Should distribution shift fail a CI gate? | It must not change the *verdict*: DD012/DD013 are `POTENTIAL`, so shift moves `SAFE`→`RISKY` and never to `INVALID` (measured on `examples/shifted_tabular`). It does move `--ci`, because that gate is defined as "verdict is not `FORMAL_EVAL_SAFE`" - a separate, opt-in decision about how strict a merge gate is. Whether a harder benchmark invalidates *your* evaluation stays a task question | **High** for adoption - the gap between "risky" and "invalid" is the whole pitch |

## 4. Defects found while writing the docs (all fixed, all with tests)

1. **Path leakage and unstable fingerprints** (A14/A15) - `tests/test_paths.py` covers relative
   resolution; the fix is exercised by every diff test.
2. **DD016 overclaim in metadata mode** (A12) - `tests/test_leakage.py::
   test_metadata_mode_calls_integrity_a_lower_bound_not_a_count`.
3. **`finding_changes` fabricating resolutions** (A13) - `tests/test_diff.py::
   test_an_unaudited_side_never_reports_findings_as_resolved`.
4. **Untraceable evidence ids in DD018/DD019** - diff rows now carry `current_sample_id` and
   findings resolve through `_locator`; `tests/test_diff.py::
   test_the_audit_baseline_finding_names_rows_a_reviewer_can_open`.

Pattern worth remembering: each of these was invisible in the code and obvious in a *rendered
report*. Documentation runs are a test surface - keep writing them per release. Since 2026-09-22
that is not a suggestion: `tests/test_docs_contract.py` re-measures the documents, and it found two
more stale claims the same way (section 6, last paragraph).

## 5. Spec TEST 1-37 coverage

Definitions taken verbatim from spec sections 183-219; the implementing test is named so a
reviewer can jump straight to it.

| TEST | Spec asks | Implemented by |
| --- | --- | --- |
| 1 | identical image in train/test ⇒ `CRITICAL` | `test_leakage.py::test_test01_identical_image_in_train_and_test_is_critical` |
| 2 | same bytes, different filename ⇒ still detected | `::test_test02_same_bytes_under_different_names_still_detected` |
| 3 | different bytes, same filename ⇒ no false positive | `::test_test03_same_filename_different_bytes_is_not_a_duplicate` |
| 4 | same image, different label ⇒ `CRITICAL` | `::test_test04_identical_content_with_conflicting_labels_is_critical`, `test_examples.py::test_a_conflicting_label_on_identical_content_is_a_blocking_finding` |
| 5 | same patient across splits ⇒ `CRITICAL` | `test_leakage.py::test_test05_shared_entity_across_splits_is_critical` |
| 6 | disjoint patients ⇒ no false report | `::test_test06_disjoint_entities_are_not_flagged` |
| 7 | 1% minority reported as imbalance | `test_structure.py::test_test07_a_one_percent_class_is_reported_as_imbalance_without_invalidating_anything` |
| 8 | long-tail preset, suppression allowed | `test_structure.py::test_test08_and_32_a_suppressed_rule_keeps_its_reason_in_the_report` |
| 9 | train/test feature shift measured | `::test_test09_a_shifted_feature_is_measured_with_effect_size` |
| 10 | identical distributions not over-flagged | `::test_test10_identical_distributions_are_not_flagged_in_volume` |
| 11 | missing column detected | `::test_test11_a_column_present_in_train_and_absent_in_test_is_found` |
| 12 | dtype drift detected | `::test_test12_a_column_that_changed_dtype_is_found` |
| 13 | corrupt JPG detected | `test_leakage.py::test_corrupt_and_empty_images_are_reported_not_silently_skipped` |
| 14 | zero-byte image detected | same test (docstring names both) |
| 15 | v2 adds samples, diff correct | `test_diff.py::test_test15_appended_rows_are_added_and_nothing_else` |
| 16 | train → test move ⇒ split drift | `::test_test16_a_row_crossing_the_boundary_is_a_move_not_an_add_and_a_remove` |
| 17 | label change detected | `::test_test17_a_changed_label_is_a_label_change_not_a_new_sample` |
| 18 | repeated fingerprinting stable | `test_diff.py::test_test18_repeated_fingerprinting_is_stable` |
| 19 | identical content, two paths: full-fingerprint behaviour designed | `test_leakage.py::test_test19_identical_bytes_on_two_paths_have_two_sample_ids` |
| 20 | 50 000 files without exhausting RAM | `test_scale.py::test_test20_every_file_is_accounted_for_and_ram_stays_bounded` |
| 21 | Ctrl+C exits safely | `test_reports.py::test_test21_an_interrupted_run_exits_130_and_writes_nothing`, `::test_test21_a_failure_while_writing_leaves_the_previous_report_intact` |
| 22 | no API key ⇒ full function | `test_standalone.py::test_test22_no_network_library_or_model_framework_is_imported_anywhere`, `::test_test22_the_full_audit_still_completes_with_the_network_switched_off` |
| 23 | no GPU ⇒ full function | `::test_test23_an_audit_with_no_gpu_and_a_stripped_environment_matches_the_local_one`, `::test_test23_the_child_process_imports_no_gpu_framework` |
| 24 | Windows paths work | `test_paths.py` - 4 `test_test24_*` tests |
| 25 | Unicode / 中文路径 works | `test_paths.py` - 3 `test_test25_*` tests + `::test_the_installed_command_line_entry_point_survives_a_subprocess_with_that_directory` |
| 26 | Excel read correctly | `test_formats.py` - 3 `test_test26_*` tests (multi-sheet included) |
| 27 | Parquet read correctly | `::test_test27_a_parquet_leaky_dataset_is_caught_the_same_way_as_a_csv_one`, `::test_test27_parquet_and_csv_agree_on_a_clean_dataset_too` |
| 28 | NaN category handled safely | `test_structure.py::test_test28_nan_values_in_a_category_are_counted_not_crashed` |
| 29 | empty dataset fails safely | `::test_test29_an_empty_dataset_fails_with_a_message_not_a_traceback`, `::test_test29b_a_header_only_table_is_audited_without_inventing_samples` |
| 30 | train-only ⇒ `INCONCLUSIVE`, never "safe" | `::test_test30_a_train_only_dataset_can_never_be_called_safe` |
| 31 | near-duplicate threshold boundary | `test_leakage.py::test_test31_near_duplicate_boundary_is_the_threshold_itself` |
| 32 | suppression reason kept in report | `test_structure.py::test_test08_and_32_...`, `::test_a_suppression_without_a_reason_is_refused` |
| 33 | `report.json` schema stable | `test_reports.py` - 3 `test_test33_*` tests |
| 34 | CLI exit codes correct | `test_reports.py` - 7 `test_test34_*` tests |
| 35 | ruff passes | gate command, not a pytest item (see CONTRIBUTING.md) |
| 36 | mypy passes | gate command |
| 37 | pytest passes | gate command |

Beyond the spec list: `test_discovery.py` (11 tests for the layout heuristics),
`test_splitting.py` (12 for group-aware splitting and its refusal to touch existing data),
`test_examples.py` (9 asserting each fixture trips exactly its planted fault, plus that
`examples/build.py` still reproduces the whole collection), 6 more diff tests (rename pairing,
mode refusal, the unaudited side), `test_privacy.py` (4 tests / 6 items), `test_packaging.py` (4) and
`test_docs_contract.py` - 12 checks that expand to 94 items because most of them run once per
rule. That last file is the one that keeps the prose honest: the front table of every
`docs/rules/*.md`, the detector wiring, the V0.1 claim, the README's demo block and quoted
finding, `examples/RESULTS.md` and the fingerprint-mode coverage claims are each compared with
the code or a live run. It adds no number to the TEST register above; it audits the documents.

## 6. Coverage gaps - closed 2026-09-22

The five zero-reference rules from the V0.1 write-up (DD001, DD008, DD013, DD017, DD020) and the
partially covered DD021 now have named assertions:

* DD001 - `test_structure.py::test_dd001_asserts_the_identity_baseline_every_other_finding_cites`
  (rule-id, exactly-one, INFO/PASS/NONE, evidence ties back to `identity`).
* DD008 - `test_leakage.py::test_dd008_a_near_unique_undeclared_column_is_an_identifier_candidate`
  (name-MEDIUM vs cardinality-LOW, 0.98 threshold, per-column dedup across splits) and
  `::test_dd008_declared_keys_are_resolved_not_re_judged` (declared ids leave the candidate set).
* DD013 - `test_structure.py::test_dd013_a_shifted_test_label_distribution_is_measured_with_effect_size`
  (TV 0.35 ⇒ HIGH, movers, threshold evidence) and `::test_dd013_a_small_shift_is_low_and_respects_a_raised_threshold`
  (`min_tv_distance` is policy-wired; note this contrasts with DD017's floors, see A10).
* DD017 - `::test_dd017_a_brighter_test_split_is_reported_as_property_shift`,
  `::test_dd017_without_decoded_pixels_answers_inconclusive_not_safe` (metadata mode ⇒ INCONCLUSIVE,
  message points at `--fingerprint full`), `::test_dd017_is_unsupported_on_tabular_data`.
* DD020 - `::test_dd020_undeclared_provenance_is_advisory_and_what_is_declared_is_reported`
  (all-missing / complete-silent / partial-INFO branches).
* DD021 - boundary (`2/40 == min_match_ratio` fires; `min_match_ratio: 0.1` silences; `1/40` quiet),
  cross-split `seen` dedup attributed to the alphabetically first split with a per-split ratio
  (A17 made executable), `enabled: false` ⇒ NOT_RUN with reason, and image dataset ⇒ UNSUPPORTED.
* `--fingerprint sampled` - `test_leakage.py::test_fingerprint_sampled_declares_its_coverage_and_is_deterministic`
  (limitation text with fraction+seed, real subset, identical manifest hash across runs).
* imagehash absence - `::test_dd004_without_imagehash_is_inconclusive_and_the_rest_still_runs`
  (DD004 INCONCLUSIVE "not a PASS", DD003 control still fires).
* `examples/build.py` - `test_examples.py::test_the_example_build_script_still_produces_the_whole_collection`
  (builder runs to a temp dir and reproduces exactly the committed fixture set). Freshness is no
  longer a manual step either: `test_docs_contract.py` re-derives `RESULTS.md` by auditing every
  fixture and byte-compares the text, so a drifted file fails `pytest`; `python examples/build.py
  --audit` is the command that rewrites it.

**And the documentation itself, on 2026-09-22:** `tests/test_docs_contract.py` (12 checks / 94
items). It found two stale claims in the README and both were rewritten from measured output, not
from an earlier document: the distribution-shift block quoted a finding format that no longer
renders (the live `examples/shifted_tabular` audit now replaces it), and the fingerprint paragraph
implied `metadata` costs only "integrity and duplicate rules" and that `sampled` trades coverage -
measured, `metadata` costs {DD003, DD004, DD009, DD016, DD017} on an image fixture and {DD003} on a
tabular one, while `sampled` at 0.1 costs no rule coverage on the shipped fixtures. It also removed
`(line NNN)` citations from two rule documents, which cannot be checked and rot silently.

Still open, deliberately: the detector-error fallback branch in `_execute` (last `except Exception`)
is only exercised indirectly; and DD017's 0.5/1.5 floors remain hard-coded (A10 unchanged).

Fixture lesson recorded: pandas parses the literal string `N/A` as NaN, so a DD021 filler value
written as `N/A` silently vanishes from the non-null denominator the ratio is computed over -
the column then reads as 2-of-2. Fillers in PII fixtures must be real strings (`masked`).

## 7. Measured numbers (real runs, do not restate without re-measuring)

| What | Number | Source |
| --- | --- | --- |
| `dataset-doctor-audit demo` leaky_tabular | 316 findings, `FORMAL_EVAL_INVALID` (DD003 12 · DD005 66 · DD007 316) | demo run log, 2026-09-21 |
| `dataset-doctor-audit demo` clean_tabular | 300 findings, `SAFE` - the false-positive control | demo run log, 2026-09-21 |
| `dataset-doctor-audit demo` leaky_images | 146 findings, `INVALID` | demo run log, 2026-09-21 |
| `examples/` fixtures (13, incl. 6 `unsafe_*`) | per-fixture verdicts and counts | `examples/RESULTS.md`, regenerate with `python examples/build.py --audit` |
| Single audit wall time (fixture-scale) | 1 883 ms | audit run log, 2026-09-21 |
| Scale: 60 000 image samples (50 000 train + 10 000 test), cold hash cache | 487.7 s and 467.8 s, peak RSS 396 MB | `tests/test_scale.py` TEST 20 passed x2, 2026-09-22, HEAD `7542f16` with the print statement moved above the ceilings (committed as `09021c8`), Windows 11 / Python 3.13.1 / pytest 9.1.1. `dataset_doctor_audit/` is byte-identical today: `git diff --stat 7542f16..HEAD -- dataset_doctor_audit` is empty |
| Scale, same fixture and conditions, code at `88eb253` (before `94ca1e1`) | 384.1 s and 408.9 s, peak RSS 396 MB | same test, 2026-09-22, A/B pair |
| Scale, same fixture, one run earlier the same evening | 4 825.8 s - breached the 1 800 s gate and FAILED | `scale_run.log`, 2026-09-22 17:51-19:11; the same fixture and the same commit then ran at 487.7 s, so this number did not reproduce |
| Raw floor over the same 60 000-file tree, no detector code | read + SHA-256 of every file 21.8 s (0.36 ms/file); PIL decode 0.42 ms/file | `p4_baseline.py`, 2026-09-22 |
| Filesystem call cost on that tree | `Path.resolve()` 0.498 ms, `os.stat()` 0.142 ms per path | micro-benchmark, 8 000 paths, 2026-09-22 |
| ~~Scale: 48 000 image files~~ superseded 2026-09-22 | cold 315.0 s / warm 320.6 s, peak RSS 344 MB | recorded 2026-09-21 from a fixture under `%TEMP%`; see the analysis below for why it is not comparable |

### Scale regression analysis (2026-09-22)

Two separate questions came out of the first gate breach, and they have different answers.

**The 4 825.8 s run is not a code regression.** Identical commit, identical fixture directory,
identical cold-cache condition re-ran at 487.7 s and 467.8 s minutes later, so the input and the
program were held constant and only the machine differed. The leading hypothesis is Windows Search
(`WSearch` is Running) indexing the 72 000 files that had been created two minutes before that run
started: this fixture lives under `Documents`, which is an indexed library location, while the
2026-09-21 run that produced the 315 s figure built its fixture under `%TEMP%`. It is labelled a
hypothesis because it was never reproduced on purpose - what is established is only that the stall
is environmental and does not reproduce. Consequence for the next person running this: on Windows,
build the fixture somewhere outside an indexed library, or let indexing settle first. The 1 800 s
gate did its job either way - a ten-fold stall was reported as a failure, not waved through.

**There is a real, modest, measured regression of about 20%, and it is attributed.** Paired runs on
the same directory, two per side: `88eb253` averaged 396.5 s, HEAD averages 477.8 s, so +81.3 s
(+20.5%) against within-side scatter of 4-6%. Peak RSS is unchanged at 396 MB, so this is CPU and
syscall time, not memory. The only package change between those commits is `94ca1e1` (keep absolute
paths out of findings), which routed reported paths through `adapters/base.relative()`; that helper
calls `self.root.resolve()` and `path.resolve()` for every record, and on this tree a resolve costs
0.498 ms - about 56 s of the measured 81 s at 60 000 files, which is the mechanism at the right
magnitude. `94ca1e1` is not being reverted: it closed a real report-sharing leak that SECURITY.md
had already promised, and the fix is correct. The cheap follow-up is to resolve the root once per
adapter instead of once per record, which is a performance change and therefore waits until the
freeze lifts - it is registered in section 10 with this analysis as its justification.

Comparing across days is invalid and is the reason the old figure is struck through rather than
corrected: the same pre-fix code that reads 396.5 s here in `Documents` measured 315.0 s in
`%TEMP%`, i.e. about 1 ms/sample of the apparent change is directory, not code.

| Demo leaky image set DD003 | "2 of 100" | `docs/rules/DD003-exact-duplicate.md` |
| `docs/rules/*.md` examples | every figure transcribed from an in-session run | each doc's Examples section |
| Rules whose document quotes a detector | 21/21 verified to be the function `audit.DETECTORS` wires | `test_docs_contract.py`, 2026-09-22 |
| `--fingerprint metadata` coverage cost | image fixture loses {DD003, DD004, DD009, DD016, DD017}; tabular fixture loses {DD003} | `test_docs_contract.py` (set equality), 2026-09-22 |
| `--fingerprint sampled --sample 0.1` coverage cost | no rule lost on either shipped fixture | same test, 2026-09-22 |
| CI workflow executions | 0 - `.github/workflows/ci.yml` is committed and the remote now exists, but the remote holds no commits, so no workflow can be triggered | `git remote -v` lists `origin`; GitHub reports 0 branches / 0 tags / 0 releases for it, 2026-09-22 |

Runtime is now dominated by the documentation-contract file: it re-audits every example fixture to
check `RESULTS.md`, and it is the reason the suite takes about a minute instead of seconds.
`tests/test_scale.py` no longer needs a `--deselect`: it skips itself unless
`DATASET_DOCTOR_SCALE=1`, so re-running it deliberately before a release is
`DATASET_DOCTOR_SCALE=1 PYTHONPATH=. pytest tests/test_scale.py`.

## 8. Where the spec's prohibitions are enforced

| Prohibition | Mechanism |
| --- | --- |
| No single "health score" | verdict is 4-valued + per-finding `formal_impact`; no numeric score exists anywhere in the model |
| No LLM decides safety | no network/model imports at all - asserted by `test_standalone.py` |
| No PASS without evidence | `build_finding` requires evidence; `InsufficientEvidence` ⇒ `INCONCLUSIVE`, not `PASS` |
| No correlation stated as cause | the three `HEURISTIC` rules (DD004, DD008, DD021) each state their own confidence in their document - `MEDIUM` capped for DD004, `MEDIUM` for an identifier-named column / `LOW` for plain cardinality in DD008, `LOW` for DD021 - and name a benign explanation in `why_it_matters`; DD007's registered evidence type is `DETERMINISTIC`, and only its candidate findings arrive as `HEURISTIC`/`LOW`. `test_docs_contract.py` enforces both halves (A22) |
| No deleting / overwriting user data | adapters open read-only; the only writes are `-o` and the hash cache; `split` refuses a non-empty target (`test_splitting.py`) |
| No auto-removal of near-duplicates | DD004 recommends quarantine, `auto_fix_available: false` |
| No cloud upload | no network code path; `test_test22` runs the whole audit with the network switched off |
| No quality/leakage conflation | `Category` + `FormalImpact`, and the report groups findings by evaluation validity first |
| No fabricated benchmark numbers | nothing here is a measured detection-rate claim; see COMPETITIVE_ANALYSIS "Claims we do not make" |
| No fake references | every citation in the docs is a DOI/arXiv/PMID checked on 2026-09-21; unconfirmed ones are listed as *not* cited |

## 9. Limitations (publish verbatim, spec section 153)

- Semantic leakage cannot be fully automated.
- Near duplicate thresholds are dataset-dependent.
- Distribution shift does not automatically mean invalid evaluation.

Add to that, in the same voice: DD016 cannot see inside a file it was not asked to open
(`--fingerprint metadata` ⇒ lower bound), DD021 cannot distinguish a phone number from an encoded
identifier, and DD018/DD019 measure nothing without a baseline - `NOT_RUN` is not a PASS.

## 10. Next steps, in order

1. ~~`docs/METHODOLOGY.md`, `docs/adr/0001-0006`, `AGENTS.md`, `ROADMAP.md`, `SECURITY.md`,
   `CONTRIBUTING.md`, `CHANGELOG.md`, `DEEP_RESEARCH_*.md`~~ Done: all shipped 2026-09-21 except
   the Phase-0 report, which landed 2026-09-22 as `docs/DEEP_RESEARCH_PHASE0.md` (prose companion
   to the COMPETITIVE_ANALYSIS fact table; the fact table wins on any disagreement).
2. ~~Close the section 6 gaps~~ Done 2026-09-22: all listed rules and modes now have named
   assertions (section 6 records which), and the documentation became a tested surface too. Suite
   118 → 134 → 242 collected items; gates green at each step.
3. ~~Real repository~~ Done 2026-09-22: `git init -b main` and one root commit carrying all 481
   tracked files, after a `.gitignore` for caches, `dist/`, and the per-dataset
   `.dataset-doctor/` workdir. The suite was re-run against the committed tree (133 passed,
   1 deselected; `ruff format --check`, `ruff check`, `mypy` clean). ~~Hosting setup~~ Also done
   2026-09-22: `github.com/xihaian251/dataset-doctor` created public and empty, set as `origin`,
   `[project.urls]` filled in, and `LICENSE`'s copyright line given its named holder (`冯硕`).
   **Still open and deliberately not done**: the push itself, a signed tag, and a PyPI publish
   under the distribution name `dataset-doctor-audit` - plus enabling private vulnerability
   reporting, which cannot be checked while the remote has no commits. Those are irreversible or
   shared-state, so they wait for the maintainer's explicit go-ahead, and the name-collision note
   in the README should have a human's eyes on it before anything is published.
4. ~~Release engineering artefacts~~ Written 2026-09-22, **never executed**: `.github/workflows/ci.yml`
   (three jobs: static gates; pytest on 3.11/3.12/3.13 × Ubuntu/Windows with the scale test held
   off; `python -m build` then an audit run through the installed wheel - no publish step, no
   upload to an index, no tag trigger), `.github/ISSUE_TEMPLATE/` (`crash`, `wrong-verdict`, plus
   `ABOUT.md`), `.github/PULL_REQUEST_TEMPLATE.md` and `docs/RELEASE_CHECKLIST.md`. The first push
   is what will show whether the YAML is right; nothing here can claim that.
5. `examples/RESULTS.md` no longer drifts silently - `test_docs_contract.py` re-audits every
   fixture and compares, so step 4 of the old list became a failing test rather than a reminder.
   Run `python examples/build.py --audit` to rewrite the file after an intended change.
6. Deferred by the feature freeze, with its measurement already taken: `adapters/base.relative()`
   resolves the dataset root for every record, which `tests/test_scale.py` costs about 20% of the
   60 000-file audit (section 7). Resolving it once per adapter is the fix. It is a performance
   change with no release necessity, so it waits; the A/B numbers above are its pre-registration.

## 11. Scratch state - disposition

`_doccheck/` (workspace root) held the documentation measurement fixtures - `vd*` (version
drift), `pii*`, `props*`, `dd016*`, `lc`, `imbal*`, `shift`, `schema`, `miss`, `out_*`, plus
`_clicheck`, `_demo_check*`, `_scale_check`, `_rules_dump.json`, `_readme_*`, `_rebuild_examples.log`,
`_diffcheck.out`. Every number they produced is already transcribed into `docs/`. On 2026-09-22
they were moved (not deleted) to `<workspace>/_scratch_archive_20260922/` - ~100 MB, dominated by
the 48 000-file `_scale_check` fixture - still outside the package, safe to purge once a human
has glanced at the archive once. They are not part of the repository.
