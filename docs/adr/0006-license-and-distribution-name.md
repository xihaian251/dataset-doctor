# 0006 - Apache-2.0, and a distribution name that is not the brand name

**Status:** accepted (2026-09-21)

## Context

The spec allowed Apache-2.0 or MIT, to be decided by Phase 0 research, and forbade adding a
licence *to a user's dataset* (section 103). Separately: `pip install dataset-doctor` turns out to
install an unrelated MIT-licensed auto-cleaning package (1.0.1, uploaded 2026-03-25,
`github.com/Mirdula18/dataset-doctor`) whose CLI has no `audit` subcommand - verified from PyPI
metadata on 2026-09-21.

## Decision

**Apache-2.0** for this project: it adds the patent grant MIT does not have, and it matches the
licences of the tools our users arrive from (Great Expectations, Evidently, Cleanlab, DVC, NeMo
Curator - see [COMPETITIVE_ANALYSIS](../COMPETITIVE_ANALYSIS.md)).

**Distribution name `dataset-doctor-audit`**, brand and console script unchanged
(`dataset-doctor`), import package stays `dataset_doctor`. `dataset-doctor-audit`,
`datasetdoctor` and `ds-doctor` were all confirmed available on PyPI the same day.

## Consequences

- The spec's headline `pip install dataset-doctor && dataset-doctor audit ./data` cannot be
  printed as-is: the README's Quick Start says plainly that `pip install dataset-doctor` is not
  this tool, and points to `dataset-doctor-audit`.
- The two projects share an importable package name, so they must not be installed together. That
  is a real cost of keeping the brand, recorded in PROJECT_STATE (A16) rather than glossed over.
- Apache-2.0 means contributors grant a patent licence; `LICENSE` is the unmodified text and the
  spdx identifier is in `pyproject.toml`. No `[[project.license-files]]` oddity, no CLA.
- The tool still never writes a licence into a dataset. DD020 reports what the config declares and
  stops there; a missing licence is a `LOW`/`INFO` finding, never an automated edit.
- No `[project.urls]` yet: a homepage pointing at a repository that does not exist is a broken
  link in every package index. Add it, the CI workflow and the PyPI publish job when the real
  repository exists (PROJECT_STATE section 10).
