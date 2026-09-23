# 0006 - Apache-2.0, and installed namespaces that are not the brand name

**Status:** accepted (2026-09-21), amended 2026-09-22 (the name decision widened)

## Context

The spec allowed Apache-2.0 or MIT, to be decided by Phase 0 research, and forbade adding a
licence *to a user's dataset* (section 103). Separately: `pip install dataset-doctor` turns out to
install an unrelated MIT-licensed auto-cleaning package (1.0.1, uploaded 2026-03-25,
`github.com/Mirdula18/dataset-doctor`) whose CLI has no `audit` subcommand - verified from PyPI
metadata on 2026-09-21, and re-verified against the built wheel on 2026-09-22, which is where we
confirmed it ships the top-level import package `dataset_doctor` *and* the console script
`dataset-doctor`.

## Decision

**Apache-2.0** for this project: it adds the patent grant MIT does not have, and it matches the
licences of the tools our users arrive from (Great Expectations, Evidently, Cleanlab, DVC, NeMo
Curator - see [COMPETITIVE_ANALYSIS](../COMPETITIVE_ANALYSIS.md)).

**All three namespaces carry the `-audit` suffix** (amended 2026-09-22): distribution
`dataset-doctor-audit`, import package `dataset_doctor_audit`, console script
`dataset-doctor-audit`. The original ruling suffixed only the distribution and kept the brand
command, which left the import package shared with the other project - two wheels writing
`dataset_doctor/cli.py` into the same `site-packages`, last install wins. `dataset-doctor-audit`,
`datasetdoctor` and `ds-doctor` were re-checked against the index on 2026-09-22 and are all still
available (HTTP 404).

What does **not** get suffixed: the brand-level artifacts that live in the user's directory, because
they collide with nothing - the config file is `dataset-doctor.yaml`, the per-dataset workdir is
`.dataset-doctor/`, the default report directory is `dataset-doctor-report/`, and the project is
called Dataset Doctor in prose.

## Consequences

- The spec's headline `pip install dataset-doctor && dataset-doctor audit ./data` cannot be printed
  as-is: the README's Quick Start says plainly that `pip install dataset-doctor` is not this tool,
  and points to `dataset-doctor-audit`.
- Nothing is shared with the other project any more, so installing both is now a cosmetic conflict
  rather than a corrupted environment. That was the point of the amendment.
- The command every user types got longer by six characters, and every quoted CLI invocation in
  the rule documents had to be re-measured. The alternative - keeping a colliding import name -
  was worse, because it fails silently and on the user's machine, not ours.
- Apache-2.0 means contributors grant a patent licence; `LICENSE` is the unmodified text and the
  spdx identifier is in `pyproject.toml`. No `[[project.license-files]]` oddity, no CLA.
- The tool still never writes a licence into a dataset. DD020 reports what the config declares and
  stops there; a missing licence is a `LOW`/`INFO` finding, never an automated edit.
- No `[project.urls]` was added at the time: a homepage pointing at a repository that does not exist
  is a broken link in every package index. The condition has since been met — `[project.urls]`
  (`Homepage`, `Repository`, `Issues`) were added on 2026-09-22 pointing at
  `github.com/xihaian251/dataset-doctor`, the repository created that day, and the `LICENSE`
  copyright line was given its named holder. The CI workflow ran for the first time after the
  initial push; the Trusted Publishing steps and 0.1.0 release were completed on 2026-09-23
  (PROJECT_STATE sections 1 and 10).
