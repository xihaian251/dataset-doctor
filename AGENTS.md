# AGENTS.md - working rules for humans and agents on this repository

Non-negotiables, in the form the spec requires them (section 157):

- **Read-only by default.** No code path writes into a dataset. The only writes are the `-o`
  report directory, the hash cache and snapshots under `<dataset>/.dataset-doctor/`, `init`'s
  config template, and `split` into a new, empty target.
- **No data deletion.** Not of samples, not of duplicates, not of columns. Remediation is text the
  user acts on; `auto_fix_available` is `false` on every rule.
- **No fabricated benchmark.** Every number in this repository - README, `docs/rules/*`,
  `examples/RESULTS.md`, `PROJECT_STATE.md` - came from a run on this machine. If you cannot point
  at the run, do not write the sentence, and never invent a dataset, a paper, a DOI or a GitHub
  repository.
- **No LLM required.** No network client, no model, no API key, no GPU. `tests/test_standalone.py`
  fails the build if that stops being true.
- **No silent PASS.** An unmeasurable check returns `INCONCLUSIVE`, `NOT_RUN` or `UNSUPPORTED` with
  a reason, and a coverage gap on a V0.1 priority rule blocks the `SAFE` verdict.
- **No hidden upload.** Nothing leaves the machine; reports are written locally and contain
  relative paths, ids and digests - no absolute paths of *data files*, and never raw values from a
  column DD021 flagged.
- **Evidence before verdict.** A finding without sample ids, counts and a location is a bug, even
  when its severity happens to be right.

## Before you change anything

1. Read [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) - ambiguity register (A1-A23), coverage
   gaps, and the defects that documentation runs already caught.
2. Read [docs/METHODOLOGY.md](docs/METHODOLOGY.md) - which thresholds are policy-wired and which
   are literal in a detector. Do not "harmonise" them silently.
3. Read the page for the rule you are touching under [docs/rules/](docs/rules/). Its Examples
   section is measured output; if your change breaks the quoted text, either the change is wrong
   or the doc must be re-measured - never leave a stale example.

## Repo conventions

- Python ≥ 3.11, `from __future__ import annotations`, type hints on public functions,
  `mypy dataset_doctor_audit` clean, `ruff format` + `ruff check` clean (line length 120, nested
  ternaries rejected by `SIM108`).
- Detectors live in `dataset_doctor_audit/detectors/`, one module per family, and raise
  `NotApplicable` / `InsufficientEvidence` instead of returning an empty list when they cannot
  measure. `rules.py` owns the registry, the policy application and the verdict; severity changes
  happen nowhere else.
- Every rule needs a `docs/rules/DDNNN-*.md` page matching `doc_path` in the registry, with
  measured examples, false positives, a severity table and a remediation section that states
  whether that rule reads `enabled`.
- New heuristic ⇒ `EvidenceType.HEURISTIC` + a `Confidence` its document states explicitly
  (`LOW` unless the arithmetic justifies more; existing deviations are registered in
  `docs/PROJECT_STATE.md` A22) + a `why_it_matters` that names the benign explanation. Do not let
  a heuristic escalate a verdict un-corrected (see DD007's FDR step).
- Truncate evidence lists, never the claim: caps go in the doc, `limitations` says what was capped.

## Commands

```bash
pip install -e ".[image,excel]"        # extras: imagehash for DD004, openpyxl for Excel
PYTHONPATH=. pytest -rA                         # TEST 37 (the scale test skips itself)
DATASET_DOCTOR_SCALE=1 PYTHONPATH=. pytest tests/test_scale.py   # the 48 000-file run, ~5 min
ruff format dataset_doctor_audit tests examples && ruff check .   # TEST 35
mypy dataset_doctor_audit                                         # TEST 36
python examples/build.py --audit     # regenerate examples/RESULTS.md after any detector change
PYTHONPATH=. python -c "from dataset_doctor_audit.cli import main; main()" demo ./out
```

`pyproject.toml` puts `-q` in pytest's `addopts`, so a typed `-q` becomes `-qq` and prints no
summary line - use `-rA` if you want the counts and the skip reasons.

Windows note: set `PYTHONIOENCODING=utf-8` before any command that prints Chinese paths or report
text, and remember that long background jobs here get killed silently - drive long runs
resumably/cache-first, not in the background.

## What not to do

- Do not add a score, a percentage "health index", or a colour that stands in for the verdict.
- Do not make `dataset-doctor-audit audit` exit 0 on a `BLOCKING` finding to appease a CI complaint.
- Do not weaken a fixture to make a test pass; the control fixtures in `examples/` exist precisely
  so false positives are visible.
- Do not add a licence to a user's dataset, or auto-fill provenance.
- Do not publish a comparison against another tool's detection rate. We have not measured one.
