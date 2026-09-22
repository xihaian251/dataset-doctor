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
mypy dataset_doctor_audit                              # needs `pip install "numpy<2.5"`, see section 2
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
- [ ] `git ls-files --others --exclude-standard` prints nothing before the build. The sdist target
      lists directories, but the backend adds untracked files too, so anything sitting in the
      working tree that `.gitignore` does not cover is published: on 2026-09-22 a throwaway venv
      left in the checkout put 2 485 third-party files into the archive (495 files became 2 980).
- [ ] Every `.py` in both archives is byte-identical to its blob at the commit being built
      (`git show HEAD:path`), and the wheel's hash repeats across two builds. A build reads the
      working tree, not the index, and `core.autocrlf=true` can leave CRLF there while
      `git status` still reports the tree clean - so "clean" does not prove the artefact matches
      the commit. Measured 2026-09-22: 32 package modules, 0 mismatches, wheel hash identical
      across three builds from two different commits.
- [ ] `mypy` needs `numpy<2.5` in the environment while `[tool.mypy]` holds `python_version =
      "3.11"`: numpy 2.5 vendors PEP 695 `type` statements mypy cannot parse at that target, and
      the run aborts before reaching our files. CI's static job installs the ceiling; the shipped
      dependency range is untouched and the test matrix still runs the newest numpy
- [ ] All three namespaces still carry the suffix - distribution `dataset-doctor-audit`, import
      package `dataset_doctor_audit`, console script `dataset-doctor-audit` - and no brand-level
      artefact does (`dataset-doctor.yaml`, `.dataset-doctor/`, `dataset-doctor-report/`). The
      README's name-collision notice describes the *other* project, so re-check the index before
      every release; that is a fact about someone else's upload, not about this repository

## 3. Decisions that must be made, not assumed

- [x] **Copyright holder.** Resolved 2026-09-22. `LICENSE` now reads `Copyright 2026 冯硕`, the named
      holder, replacing the `Dataset Doctor contributors` placeholder; the Apache-2.0 licence text
      around it is unmodified. One thing was *not* changed and needs a person: `pyproject.toml`'s
      `authors` still carries the collective label `Dataset Doctor contributors`. That is a credit
      line rather than a copyright assertion, so it does not contradict the licence, but whether the
      published metadata should name the holder too is the maintainer's call, not a docs edit's.
- [x] **`[project.urls]`.** Added 2026-09-22: `Homepage`, `Repository` and `Issues` point at
      `github.com/xihaian251/dataset-doctor`, the public repository created that day. Deliberately no
      `Changelog` key — a changelog URL wants a release tag or a published page, and neither exists
      before the first push. These links resolve to an *empty* repository until section 4 runs.
- [ ] **Private vulnerability reporting.** Still open, and not assumed done. `SECURITY.md` names the
      security page and states plainly that the **Report a vulnerability** form only appears once a
      repository administrator turns on Settings → Code security and compliance → **Private
      vulnerability reporting**. Nobody has checked whether it is on, because nothing has been pushed
      and an empty repository has no Security tab to read. Verify it after the first push. There is no
      contact address to substitute and none was invented; until the form is live this project has no
      private intake channel, which `SECURITY.md` now says out loud.
- [ ] **Version number.** `0.1.0` for a first public release is a claim that the V0.1 rule set
      is complete, which PROJECT_STATE supports; `0.1.0b0` is the honest alternative if any
      V0.1 rule still feels provisional. Answered in section 5, not here: publish `0.1.0`, and
      if a pre-release marker is ever wanted on the same index, PEP 440 spells it `rc`, not `b`.

## 4. Publish (blocked on explicit authorisation)

- [ ] ~~Create the remote repository~~ **Done 2026-09-22**: `github.com/xihaian251/dataset-doctor`,
      public, created empty (no README/.gitignore/LICENSE/initial commit, because the history is
      local), and configured as `origin`. Nothing has been pushed. Remaining: push the tagged commit;
      never force-push a tagged release
- [ ] `twine upload --repository testpypi dist/*` first, install from TestPyPI once, then upload to PyPI
- [ ] Create the GitHub release from the signed tag with the `CHANGELOG.md` section as notes
- [ ] Confirm the README install snippet and the CI workflow's `--ci` example both work from the published artefact

## 5. Release candidate record - built 2026-09-22, deliberately not published

| Item | Measured value |
| --- | --- |
| Commit built | `2590265` (`git status --short` empty *and* `git ls-files --others --exclude-standard` empty at build time) |
| Build | `python -m build` in a throwaway venv holding only `build` + `twine`; backend `hatchling 1.32.4` |
| Wheel | `dataset_doctor_audit-0.1.0-py3-none-any.whl`, SHA-256 `74234229fb9e6cd83c656e7fd6ddc209084a74ed60c16fa642aff05aede8b54b` |
| Sdist | `dataset_doctor_audit-0.1.0.tar.gz`, SHA-256 `d22a279358f29fae269bd70917271051c5a64a987b2f7c690c315d8c12354833` |
| `twine check dist/*` | both `PASSED` |
| Wheel content | 37 entries: 32 package modules incl. the `reports/` subpackage, `dist-info/` with `METADATA`, `WHEEL`, `RECORD`, `entry_points.txt` (`dataset-doctor-audit = dataset_doctor_audit.cli:main`) and `licenses/LICENSE`. No tests, no `examples/`. No `py.typed` - none is claimed in the classifiers, so its absence is consistent rather than missing |
| Sdist content | 495 files: 401 `examples/`, 32 `dataset_doctor_audit/`, 32 `docs/`, 15 `tests/`, 5 `.github/`, 10 root (`README.md`, `LICENSE`, `pyproject.toml`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`, `ROADMAP.md`, `.gitignore`, `PKG-INFO`). Scanning every text entry: 0 strings identifying this machine or author, 0 scratch or report paths, 2 credential-shaped strings - both canaries in `tests/test_privacy.py` and `tests/test_standalone.py`, which assert that such values are *not* emitted |
| Artefact equals commit | all 32 wheel modules and all 32 sdist package modules are byte-identical to `git show 2590265:<path>` |
| Reproducible | the wheel SHA is unchanged across three builds from two commits (`177b431`, `2590265`); the sdist changed only when files it actually ships changed |
| Clean install, wheel only | throwaway venv, 7/7 checks, `repo on sys.path: False`, bare `dataset_doctor` absent |
| Clean install, sdist only | throwaway venv built from source, 7/7 checks, `repo on sys.path: False`, bare `dataset_doctor` absent |
| Static gates at this commit | `ruff format --check .` "103 files already formatted" · `ruff check .` "All checks passed!" · `mypy` "no issues found in 32 source files" (with `numpy 2.4.6`, see section 2) · `pytest` 213 passed, 30 skipped, 1 warning in 74.66 s (86.99 s on the run immediately before it) |
| Scale gate | 60 000 image samples, 487.7 s and 467.8 s cold, peak RSS 396 MB. Those ran with `dataset_doctor_audit/` byte-identical to today's (`git diff --stat 1a671be..HEAD -- dataset_doctor_audit` is empty); PROJECT_STATE section 7 carries the analysis |

Two earlier builds are void and neither was published. The pair recorded here on 2026-09-22 at
`919a9e4` (wheel `b9ef247e…`, sdist `ddf603b2…`) carried CRLF copies of the package modules,
because the build reads the working tree and some files had drifted to CRLF there while
`git status` still reported them clean; section 2's byte-identity bullet exists because of that.
A build made minutes later, while a normalisation attempt was truncating files, shipped
zero-byte modules (`20697c8e…`, `5a17f873…`). Nothing in the checklist as it then stood would have
noticed it - `twine check` passes on an empty module and the entry count is unchanged - so it was
found only because the wheel's hash had moved without any source change, which is what the
byte-identity bullet now makes a routine check instead of a lucky catch. The two rows above are the
artefacts to upload.

The commit that *records* these hashes is later than `2590265`. It changes documentation only - the
two files under `docs/` that the sdist ships and the wheel never did - so a rebuild from that head
differs from the sdist above by exactly those files and nothing else, which `git diff --stat
2590265..HEAD` shows in one line each; the wheel is unaffected either way. That is not a
contradiction: the artefacts a human should upload are the ones above. Rebuilding from the head you
are standing on is equally acceptable and is the recommended last step before `twine upload` - it
just produces a different sdist SHA-256, which should then replace the row above rather than sit
beside it.

### `0.1.0` or a pre-release: the judgement asked for

Recommendation: publish `0.1.0`. No version change was made, and none is needed.

1. A pre-release buys rehearsal safety only if the rehearsal happens on the same index as the
   release. It does not: TestPyPI and PyPI are separate indexes, and uploading `0.1.0` to TestPyPI
   consumes nothing on PyPI. Section 4's order - push, real CI green, TestPyPI, install from
   TestPyPI, then PyPI - already provides the guard a beta version would provide.
2. The risk a pre-release genuinely protects against is that PyPI accepts a version once and never
   lets it be re-uploaded or edited, so a flawed `0.1.0` is permanent. That risk is real, which is
   why the two-clean-venv step above is a release gate rather than a nice-to-have; but a
   `0.1.0b0` uploaded to the same index is equally permanent, so the protection is illusory.
3. If a marker is wanted anyway, PEP 440's spelling for "candidate" is `0.1.0rc1`, not `0.1.0b0`.
   `b` means beta. The only mechanical difference either makes is that `pip install` skips
   pre-releases without `--pre`, which is a downside for a project whose whole point is that
   installation should be unremarkable.
4. Cost specific to this tool: `tool_version` is written into every report JSON and into every
   snapshot, and DD018 exists to compare those across runs. Shipping `0.1.0b0` and then `0.1.0`
   makes the same release look like two different detectors to the user's own baseline history.
5. `Development Status :: 4 - Beta` is already the classifier, so `0.1.0` does not overclaim
   stability. The honesty is in the classifier and in the documented limitations, not in a `b0`.

## 6. After publishing

- [ ] Update `README.md` release-status note, `ROADMAP.md` and `docs/PROJECT_STATE.md` with
      what is now true, including any measured numbers from step 1
- [ ] Open issues for the deferred work recorded in PROJECT_STATE rather than leaving it in
      prose, so the next reader sees the same gap list a maintainer sees
