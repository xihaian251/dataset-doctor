# Contributing

Start with [AGENTS.md](AGENTS.md) - the seven non-negotiables and the conventions are enforced
review criteria, not style preferences. Then [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) for the
decisions already taken and the gaps still open.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"                              # imagehash + openpyxl + pytest + ruff + mypy
dataset-doctor demo ./demo-data                      # three generated datasets to point at
PYTHONPATH=. pytest -q --deselect tests/test_scale.py
```

Python ≥ 3.11 is supported and CI-relevant; development runs on 3.13. No GPU, no API key, no
Docker - if your change needs one of those, open an issue first, because that constraint is the
product (ADR 0004).

## Gates (spec TEST 35-37)

```bash
ruff format dataset_doctor tests examples && ruff check .
mypy dataset_doctor
pytest -q                       # includes the ~5-minute 48 000-file scale test
python examples/build.py        # regenerate examples/RESULTS.md
```

All four must be clean. `pytest -q` prints no summary line by configuration - read the dots, or
run with `-rA`. On Windows set `PYTHONIOENCODING=utf-8` first if a test prints Chinese paths.

## Adding or changing a rule

1. Registry entry in `dataset_doctor/rules.py` (`rule_id`, `name`, category, `default_severity`,
   `formal_impact`, `applies_to`, `evidence_type`, `doc_path`) and, if it is tunable, a
   `RULE_TO_POLICY` mapping to its `policies.<key>` block.
2. Detector in the matching `dataset_doctor/detectors/*.py`. Raise `NotApplicable` (⇒ `NOT_RUN` /
   `UNSUPPORTED`) or `InsufficientEvidence` (⇒ `INCONCLUSIVE`) when it cannot measure - never
   return an empty list to mean "fine".
3. Decide and state whether the rule reads `policies.<name>.enabled`; the current split is
   documented in `docs/METHODOLOGY.md` and is not uniform on purpose.
4. `docs/rules/DDNNN-<slug>.md` - the page `doc_path` points at, with **measured** examples: run
   the command, paste the finding, keep the numbers honest, note caps and truncation.
5. Fixture in `examples/` (with `PLANTED_FAULTS.md`) plus a test asserting the rule fires on it and
   stays quiet on the control fixtures. A new rule with no negative-control test is the most likely
   source of false positives for everyone else.
6. Update `docs/PROJECT_STATE.md` (matrix, coverage list, ambiguity register) and `CHANGELOG.md`.

A heuristic rule must carry `EvidenceType.HEURISTIC` and `Confidence.LOW`, name its benign
alternative explanation in `why_it_matters`, and cannot escalate a verdict without a correction
step (DD007's FDR is the model).

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
