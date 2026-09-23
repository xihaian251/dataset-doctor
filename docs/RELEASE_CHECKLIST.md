# Release checklist

Sections 1 to 3 retain the measured 2026-09-22 local release-candidate record; section 4 records
the completed 0.1.0 publication on 2026-09-23. `docs/PROJECT_STATE.md` section 7 carries the
older local measurements. Re-run the applicable gates for 0.1.1 rather than treating either
release's results as proof for a future artifact.

## 1. Reproduce the release locally

Run from a fresh, clean checkout or detached worktree created from the exact release commit
(`.venv` recreated, not reused). Do not build a release artefact from a long-lived worktree: Git
can report it clean while its on-disk line endings no longer match the commit's blobs.

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
- [ ] Every version-controlled file included in either archive is byte-identical to its blob at
      the commit being built (`git show HEAD:path`), not just the `.py` modules. Enumerate the full
      sdist and compare every tracked entry, including CSV fixtures, documentation, configuration,
      tests and repository metadata; check the wheel's tracked package files the same way. Generated
      packaging metadata such as `PKG-INFO`, `METADATA` and `RECORD` is validated separately. A build
      reads the working tree, not the index, and `core.autocrlf=true` can leave CRLF there while
      `git status` still reports the tree clean - so "clean" does not prove the artefact matches the
      commit. Also require the wheel's hash to repeat across two builds. Measured 2026-09-22: 32
      package modules, 0 mismatches, wheel hash identical across three builds from two different
      commits.
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

- [x] **Author and copyright holder.** Resolved 2026-09-22. `LICENSE` reads `Copyright 2026 冯硕`,
      the named holder, replacing the former collective placeholder; the Apache-2.0 licence text
      around it is unmodified. `pyproject.toml` now also names `冯硕` as the current sole author, so
      the published author metadata and copyright attribution agree.
- [x] **`[project.urls]`.** Added 2026-09-22: `Homepage`, `Repository` and `Issues` point at
      `github.com/xihaian251/dataset-doctor`, now public with the 0.1.0 Release. No `Changelog`
      project URL was added for 0.1.0.
- [x] **Private vulnerability reporting.** Enabled and verified after the first push; the private
      **Report a vulnerability** form is the channel described in `SECURITY.md`. No contact address
      or public-issue workaround was added.
- [x] **Version number.** `0.1.0` was published to PyPI. Any 0.1.1 release requires a separate
      version decision, build and validation; this documentation update does not make one.

## 4. Publish 0.1.0 (completed 2026-09-23)

- [x] Public `origin` received `main` without force push; CI passed 8/8 jobs on the workflow
      commit. The annotated `v0.1.0` tag resolves to frozen source commit
      `31200147cc8c9d2cd51c4bd58a1c17004c6fcbb2`, not the later workflow commit.
- [x] TestPyPI verification preceded production PyPI. Both uploads used separate GitHub Actions
      Trusted Publishers, not a local `twine upload` or long-lived API token. The
      [production run](https://github.com/xihaian251/dataset-doctor/actions/runs/35858748946)
      succeeded; its wheel and sdist match the PyPI files byte-for-byte.
- [x] The [GitHub Release](https://github.com/xihaian251/dataset-doctor/releases/tag/v0.1.0)
      is published from that annotated tag with the same two files and SHA256 values.
- [x] A fresh virtual environment installed `dataset-doctor-audit==0.1.0` from production PyPI;
      `pip check`, the CLI, safe/unsafe `--ci`, snapshot, baseline, diff, fingerprint and all three
      report formats passed. The published 0.1.0 README retains its obsolete pre-release sentence;
      `main` corrects it for the next package release, without replacing 0.1.0.

## 5. Historical local release candidate - built 2026-09-22, not the published files

| Item | Measured value |
| --- | --- |
| Commit built | `6cdee51` (`git status --short` empty *and* `git ls-files --others --exclude-standard` empty at build time) |
| Build | `python -m build` in a throwaway venv holding only `build` + `twine`; backend `hatchling 1.32.4` |
| Wheel | `dataset_doctor_audit-0.1.0-py3-none-any.whl`, SHA-256 `74234229fb9e6cd83c656e7fd6ddc209084a74ed60c16fa642aff05aede8b54b` |
| Sdist | `dataset_doctor_audit-0.1.0.tar.gz`, SHA-256 `d22a279358f29fae269bd70917271051c5a64a987b2f7c690c315d8c12354833` |
| `twine check dist/*` | both `PASSED` |
| Wheel content | 37 entries: 32 package modules incl. the `reports/` subpackage, `dist-info/` with `METADATA`, `WHEEL`, `RECORD`, `entry_points.txt` (`dataset-doctor-audit = dataset_doctor_audit.cli:main`) and `licenses/LICENSE`. No tests, no `examples/`. No `py.typed` - none is claimed in the classifiers, so its absence is consistent rather than missing |
| Sdist content | 495 files: 401 `examples/`, 32 `dataset_doctor_audit/`, 32 `docs/`, 15 `tests/`, 5 `.github/`, 10 root (`README.md`, `LICENSE`, `pyproject.toml`, `CHANGELOG.md`, `SECURITY.md`, `CONTRIBUTING.md`, `AGENTS.md`, `ROADMAP.md`, `.gitignore`, `PKG-INFO`). Scanning every text entry: 0 strings identifying this machine or author, 0 scratch or report paths, 2 credential-shaped strings - both canaries in `tests/test_privacy.py` and `tests/test_standalone.py`, which assert that such values are *not* emitted |
| Artefact equals commit | all 32 wheel modules and all 32 sdist package modules are byte-identical to `git show 6cdee51:<path>` |
| Reproducible | the wheel SHA is unchanged across three builds from two commits (`27c25f6`, `6cdee51`); the sdist changed only when files it actually ships changed |
| Clean install, wheel only | throwaway venv, 7/7 checks, `repo on sys.path: False`, bare `dataset_doctor` absent |
| Clean install, sdist only | throwaway venv built from source, 7/7 checks, `repo on sys.path: False`, bare `dataset_doctor` absent |
| Static gates at this commit | `ruff format --check .` "103 files already formatted" · `ruff check .` "All checks passed!" · `mypy` "no issues found in 32 source files" (with `numpy 2.4.6`, see section 2) · `pytest` 213 passed, 30 skipped, 1 warning in 74.66 s (86.99 s on the run immediately before it) |
| Scale gate | 60 000 image samples, 487.7 s and 467.8 s cold, peak RSS 396 MB. Those ran with `dataset_doctor_audit/` byte-identical to today's (`git diff --stat 7542f16..HEAD -- dataset_doctor_audit` is empty); PROJECT_STATE section 7 carries the analysis |

Two earlier builds are void and neither was published. The historical pair recorded here on 2026-09-22 at
`6195dad` (wheel `b9ef247e…`, sdist `ddf603b2…`) carried CRLF copies of the package modules,
because the build reads the working tree and some files had drifted to CRLF there while
`git status` still reported them clean; section 2's byte-identity bullet exists because of that.
A build made minutes later, while a normalisation attempt was truncating files, shipped
zero-byte modules (`20697c8e…`, `5a17f873…`). Nothing in the checklist as it then stood would have
noticed it - `twine check` passes on an empty module and the entry count is unchanged - so it was
found only because the wheel's hash had moved without any source change, which is what the
byte-identity bullet now makes a routine check instead of a lucky catch. The two rows above are
historical measurements, **not** the artifacts to upload or reuse.

The commit that recorded those historical hashes was later than `6cdee51`; at the time it changed
only two files under `docs/`. Later release work changed more files. The published files were
built from frozen commit `31200147` in the production workflow, not from this old candidate.
Do not rebuild or attempt to replace immutable PyPI 0.1.0 files.

| Published 0.1.0 file | SHA256, verified against PyPI JSON, downloaded file, workflow artifact and GitHub Release asset |
| --- | --- |
| `dataset_doctor_audit-0.1.0-py3-none-any.whl` | `40afbefd26c9bafe6ca70c3e7dc60072f2a0318c9d6e1defd0634ba6c00425fe` |
| `dataset_doctor_audit-0.1.0.tar.gz` | `5111390aa583b1766bcd6e6c0745a143bf04352038a7b431a66a43bcc52edf11` |

### `0.1.0` or a pre-release: the judgement asked for

Decision taken for the first release: publish `0.1.0` without a pre-release version bump.

1. A pre-release buys rehearsal safety only if the rehearsal happens on the same index as the
   release. It does not: TestPyPI and PyPI are separate indexes, and uploading `0.1.0` to TestPyPI
   consumed nothing on PyPI. Section 4's sequence - push, real CI green, TestPyPI, install from
   TestPyPI, then PyPI - provided the rehearsal guard.
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

- [x] Update `README.md` release-status note, `ROADMAP.md` and `docs/PROJECT_STATE.md` with
      the verified publication state. This is a post-release documentation commit for 0.1.1
      preparation, not a rebuild of 0.1.0.
- [ ] Open issues for the deferred work recorded in PROJECT_STATE rather than leaving it in
      prose, so the next reader sees the same gap list a maintainer sees
