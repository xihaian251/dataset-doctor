# Contributing

Start with [AGENTS.md](AGENTS.md) - the seven non-negotiables and the conventions are enforced
review criteria, not style preferences. Then [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) for the
decisions already taken and the gaps still open.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                              # imagehash + openpyxl + pytest + ruff + mypy
dataset-doctor-audit demo ./demo-data                      # three generated datasets to point at
PYTHONPATH=. pytest -rA                                  # the scale test skips itself
```

Python ≥ 3.11 is supported and CI-relevant; development runs on 3.13. No GPU, no API key, no
Docker - if your change needs one of those, open an issue first, because that constraint is the
product (ADR 0004).

## Gates (spec TEST 35-37)

```bash
ruff format . && ruff check .           # CI runs `ruff format --check .`, so format before you push
mypy dataset_doctor_audit               # needs `pip install "numpy<2.5"`, see the note below
PYTHONPATH=. pytest -rA                 # ~1 minute; see the summary-line note below
python examples/build.py --audit        # regenerate examples/RESULTS.md from a live audit
```

numpy 2.5.x ships vendored stub files that use PEP 695 `type` statements. mypy cannot parse
those while `pyproject.toml` keeps `python_version = "3.11"` - the run stops on a syntax error
in `numpy/__init__.pyi` before it looks at a single file of ours, which reads like a broken
type gate but is a toolchain conflict. Measured 2026-09-22 with mypy 2.3.1: numpy 2.5.3 aborts,
numpy 2.4.6 reports "no issues found in 32 source files". The CI static job installs the
ceiling; nothing about the shipped dependency range narrows, and the test matrix still runs the
newest numpy.

All four must be clean. `.github/workflows/ci.yml` runs them as: format/lint/types on 3.12,
`pytest` on 3.11, 3.12 and 3.13 on both Ubuntu and Windows, and `python -m build` plus one
audit executed through the installed wheel on 3.12. The workflow file is prepared but has
never run - there is no remote yet, so CI green is something the first push will have to
prove, not a claim you can make here. The 48 000-file scale test is skipped by every one of
those runs (`tests/test_scale.py` enables it only when `DATASET_DOCTOR_SCALE=1`) because its
value is a memory measurement, not a regression gate.

Skips are expected and are part of the contract, not noise: the scale test, plus the
parametrised documentation checks for rules that make no V0.1 or modality claim. Note that
`pyproject.toml` already puts `-q` in `addopts`, so typing `pytest -q` means `-qq` and prints
**no** summary line - read the dots, or run `pytest -rA`. On Windows set
`PYTHONIOENCODING=utf-8` first if a test prints Chinese paths.

## Adding or changing a rule

1. Registry entry in `dataset_doctor_audit/rules.py` (`rule_id`, `name`, category, `default_severity`,
   `formal_impact`, `applies_to`, `requires`, `evidence_type`, `doc_path`), the detector tuple in
   `audit.DETECTORS`, and, if the rule is tunable, a `RULE_TO_POLICY` mapping to its
   `policies.<key>` block. `applies_to` is `[tabular, image]` for all 21 rules and decides
   nothing - `requires` is what makes a rule skip a modality or a missing input (`images`,
   `tabular`, `splits`, `label`, `group_columns`, `temporal_column`), so the two must not be
   confused when you read or write either.
2. Detector in the matching `dataset_doctor_audit/detectors/*.py`. Raise `NotApplicable` (⇒ `NOT_RUN` /
   `UNSUPPORTED`) or `InsufficientEvidence` (⇒ `INCONCLUSIVE`) when it cannot measure - never
   return an empty list to mean "fine".
3. Decide and state whether the rule reads `policies.<name>.enabled`; the current split is
   documented in `docs/METHODOLOGY.md` and is not uniform on purpose.
4. `docs/rules/DDNNN-<slug>.md` - the page `doc_path` points at, with **measured** examples: run
   the command, paste the finding, keep the numbers honest, note caps and truncation. The front
   table is not free prose: `tests/test_docs_contract.py` compares Category, Default severity,
   Formal impact, Evidence type, Detector and (when present) In V0.1 rule set against the registry
   and `audit.DETECTORS`, and rejects a Detector cell that pins a source line number. A new rule
   that skips one of those rows fails; `Applies to` is checked only when `requires` binds the rule
   to one modality, and `In V0.1 rule set` is optional prose.
5. Fixture in `examples/` (with `PLANTED_FAULTS.md`) plus a test asserting the rule fires on it and
   stays quiet on the control fixtures. A new rule with no negative-control test is the most likely
   source of false positives for everyone else.
6. Update `docs/PROJECT_STATE.md` (matrix, coverage list, ambiguity register) and `CHANGELOG.md`.

A heuristic rule must carry `EvidenceType.HEURISTIC`, name its benign alternative explanation in
`false_positive_notes` and in `why_it_matters`, and cannot escalate a verdict without a
correction step (DD007's FDR is the model). Its `Confidence` is per rule and is stated in the
rule document - `LOW` for DD007's candidate layer and for DD021; `MEDIUM` for DD004 (capped
there) and for DD008's identifier-named branch, `LOW` for a plain high-cardinality column. A
blanket `LOW` would misreport how much of the judgement is arithmetic, so
`tests/test_docs_contract.py` requires each heuristic rule's document to state its own.

## Report changes

`report.json`'s field set is frozen by `tests/test_reports.py::test_test33_*`: adding a field is
fine, removing or renaming one is a breaking change and needs a `schema_version` bump plus a note
in the changelog. `docs/rules/*.md` quote rendered findings, so a wording change is a documentation
change too - re-measure the affected Examples sections in the same PR.

## Pull requests

Explain the *why*, show the measured output, and link the issue or the ambiguity-register entry.
If you changed a threshold, state what it was and what it now is, and which finding's severity
moves as a result - thresholds are the substance of this tool (see `docs/METHODOLOGY.md`).

## Reporting problems

- Auditing, correctness, crash: regular issue. Include the command, the tool version, and - if the
  dataset is private - only the rule ids and counts, not the data.
- Security: see [SECURITY.md](SECURITY.md); do not open a public issue with a working exploit.
- A false positive you cannot suppress with a recorded reason: worth an issue and probably a doc
  fix; several V0.1 rules were tuned this way.
