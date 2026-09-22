# Release checklist

Sections 1 to 3 are checks a person can run on a laptop, and section 1 and 2 have been run
(2026-09-22, Windows 11 / Python 3.13.1) - `docs/PROJECT_STATE.md` section 7 carries the numbers
that run produced. Section 4 has not been executed and must not be: every step in it is
irreversible in public, and `docs/PROJECT_STATE.md` section 10 records the same boundary from the
project side.

## 1. Reproduce the release locally

Run from a clean checkout (`.venv` recreated, not reused):

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff format --check . && ruff check .
mypy dataset_doctor_audit
PYTHONPATH=. pytest -rA
python -m build                                        # wheel + sdist into dist/
python -m twine check dist/*                           # both artefacts, not just the wheel
```

Then install what was built, twice, in two environments that cannot see the source tree. A
repository checkout passing its own tests says nothing about whether a user can install the
release; `PYTHONPATH` and the current directory must be outside the checkout for the claim to mean
anything:

```bash
python -m venv .install-wheel && .install-wheel/bin/python -m pip install dist/*.whl
python -m venv .install-sdist  && .install-sdist/bin/python -m pip install dist/*.tar.gz
# in each, from a directory that is not the checkout, against a *copy* of the example data:
<venv>/bin/dataset-doctor-audit --help
<venv>/bin/dataset-doctor-audit audit ./safe_tabular                 # exit 0, three report files
<venv>/bin/dataset-doctor-audit audit ./unsafe_target_leakage --ci   # exit 1, INVALID
<venv>/bin/dataset-doctor-audit audit ./safe_tabular --save-snapshot v1
<venv>/bin/dataset-doctor-audit audit ./safe_tabular --baseline v1   # DD018/DD019 not NOT_RUN
```

The sdist install is the one that rebuilds from source, so it re-checks the build backend's file
selection; a module the sdist drops is a bug only this step can see.

Then record what was actually measured, in this order:

1. Version, OS, Python and the pytest summary line go into `CHANGELOG.md` under the release
   heading. Numbers come from the run, never from an earlier document.
2. `python examples/build.py --audit` regenerates `examples/RESULTS.md`; `tests/test_docs_contract.py`
   fails if the committed copy disagrees, so a stale quote cannot survive this step.
3. The scale test is opt-in: `DATASET_DOCTOR_SCALE=1 PYTHONPATH=. pytest tests/test_scale.py -v -s`.
   If it was not run, say so in the release notes rather than implying the memory claim was
   re-verified this release.

## 2. Package hygiene

- [ ] `dist/` contains exactly one wheel and one sdist for this version
- [ ] `unzip -l dist/*.whl` lists `dataset_doctor_audit/reports/` (a `.gitignore` that matched that
      source directory once left it out of the wheel - `tests/test_packaging.py` now catches it)
- [ ] `tar tzf dist/*.tar.gz` includes `LICENSE`, `README.md`, `docs/`, `examples/`, `tests/`, `.github/`.
      Check it rather than assuming: an sdist ships only what the build backend's selectors pick
      up, and `.github/` in particular is not a package directory.
- [ ] No scratch, cache, snapshot, `.dataset-doctor/` or report directory in either archive
- [ ] All three namespaces still carry the suffix - distribution `dataset-doctor-audit`, import
      package `dataset_doctor_audit`, console script `dataset-doctor-audit` - and no brand-level
      artefact does (`dataset-doctor.yaml`, `.dataset-doctor/`, `dataset-doctor-report/`). The
      README's name-collision notice describes the *other* project, so re-check the index before
      every release; that is a fact about someone else's upload, not about this repository

## 3. Decisions that must be made, not assumed

- [ ] **Copyright holder.** `LICENSE` currently reads `Copyright 2026 Dataset Doctor
      contributors`, which is a placeholder in the legal sense. Name the person or entity
      before publishing, or drop the line if the licence text without it is the intent.
- [ ] **`[project.urls]`.** Absent on purpose: a homepage pointing at a repository that does
      not exist is a broken link in the package index. Add `Homepage`, `Repository`, `Issues`
      and `Changelog` the moment the remote exists, in the same commit that records the URL.
- [ ] **Contact for security reports.** `SECURITY.md` points at GitHub's private vulnerability
      reporting, which only exists once the repository does; enable it in
      Settings → Security, and only then fill in a contact route if private reporting is not
      what you want.
- [ ] **Version number.** `0.1.0` for a first public release is a claim that the V0.1 rule set
      is complete, which PROJECT_STATE supports; `0.1.0b0` is the honest alternative if any
      V0.1 rule still feels provisional.

## 4. Publish (blocked on explicit authorisation)

- [ ] Create the remote repository; push the tagged commit; never force-push a tagged release
- [ ] `twine upload --repository testpypi dist/*` first, install from TestPyPI once, then upload to PyPI
- [ ] Create the GitHub release from the signed tag with the `CHANGELOG.md` section as notes
- [ ] Confirm the README install snippet and the CI workflow's `--ci` example both work from the published artefact

## 5. After publishing

- [ ] Update `README.md` release-status note, `ROADMAP.md` and `docs/PROJECT_STATE.md` with
      what is now true, including any measured numbers from step 1
- [ ] Open issues for the deferred work recorded in PROJECT_STATE rather than leaving it in
      prose, so the next reader sees the same gap list a maintainer sees
