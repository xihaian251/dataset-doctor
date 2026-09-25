# Release checklist

Sections 1 to 3 retain the measured 2026-09-22 local release-candidate record; section 4 records
the completed 0.1.0 publication on 2026-09-23. `docs/PROJECT_STATE.md` section 7 carries the
older local measurements. Re-run the applicable gates for the next release rather than treating any
of 0.1.0, 0.1.1 and 0.1.2 as proof for a future artifact.

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

## 4b. Publish 0.1.1 (completed 2026-09-25)

Same sequence, one patch release. Every value below is from this run.

- [x] `main` received the Acceptance #3 fix [`81db92d`](https://github.com/xihaian251/dataset-doctor/commit/81db92d)
      and the release commit [`6ba9412`](https://github.com/xihaian251/dataset-doctor/commit/6ba9412)
      without a force push; [CI run 36129458287](https://github.com/xihaian251/dataset-doctor/actions/runs/36129458287)
      passed 8/8 on `6ba9412`, and [run 36130051554](https://github.com/xihaian251/dataset-doctor/actions/runs/36130051554)
      passed 8/8 on the later publisher-retarget commit `8006f41`.
- [x] Built from `git archive 6ba9412` (exact blobs, not a checkout - section 2's CRLF bullet), in a
      throwaway venv on another drive holding only `build` + `twine`, backend `hatchling 1.32.4`;
      `python -m twine check dist/*` both `PASSED`.
- [x] Artefact equals commit: 500 sdist entries and 32 wheel package modules byte-identical to
      `git show 6ba9412:<path>`; the only non-matching wheel entry is the generated
      `entry_points.txt`. Wheel holds 32 modules incl. the four `reports/` files, and the sdist holds
      `LICENSE`, `README.md`, `docs/`, `examples/`, `tests/`, `.github/`.
- [x] Local build reproducible: both SHA-256 values unchanged across two `python -m build` runs.
      Wheel `40cef49c06a7ed004a3b6ebe2f1915d0bdc1030ddfe70ede0f44fde08bd45a07` (146 773 B),
      sdist `d1d2b43388a782594f259e27927876838c4e5acabd7ae6754b505215492f710e` (435 015 B).
- [x] [TestPyPI run 36129723666](https://github.com/xihaian251/dataset-doctor/actions/runs/36129723666)
      built the same commit on `ubuntu-latest`: sdist hash **equal** to the local one, wheel hash
      **different** (`e99593b2af3d065945cef9479ee833ed38d1999d0816c30a074d21e828c35b10`) at the same
      146 773 bytes - zip metadata is platform-dependent, which is exactly why the production
      workflow pins the hashes of the frozen Linux build rather than any local artefact.
- [x] Annotated `v0.1.1` (tag object `ae03c28`) resolves to `6ba94129566ba86fd53a1a0e09dc03fd77144328`
      - the commit TestPyPI built and the commit the publisher pins, not the later retarget commit,
      mirroring 0.1.0. Local and remote tag objects agree.
- [x] [GitHub Release v0.1.1](https://github.com/xihaian251/dataset-doctor/releases/tag/v0.1.1)
      published (not draft, not prerelease) from that tag with the two verified files; GitHub reports
      both asset digests equal to the TestPyPI artifact.
- [x] [Production run 36130358950](https://github.com/xihaian251/dataset-doctor/actions/runs/36130358950)
      rebuilt frozen `6ba9412`, asserted name/version and both pinned hashes under
      `sha256sum --check --strict`, and uploaded through the existing Trusted Publishing
      (OIDC + `pypi` environment approval) - no `twine upload`, no API token, no second pipeline.
      Its artifact bytes equal the PyPI JSON digests, the release assets and the TestPyPI files.
- [x] Two fresh environments outside the checkout, neither with the repository on `sys.path`:
      the locally built wheel (`--help`, safe audit `FORMAL_EVAL_SAFE` exit 0 with three report
      formats, `unsafe_target_leakage --ci` `FORMAL_EVAL_INVALID` exit 1, `--save-snapshot` then
      `--baseline` with DD018/DD019 `PASS`, `fingerprint`, `diff`, `report` re-render, `pip check`
      clean), and the sdist rebuilt from source at the same two verdicts. A third environment then
      installed `dataset-doctor-audit==0.1.1` **from PyPI** and reproduced the same smoke set.
- [x] Both public P0s from Acceptance #3 verified gone on the published bytes, on 90-row synthetic
      fixtures rather than a million-row re-run: a declared group column with no usable entity is
      `DD005 INCONCLUSIVE` / `HIGH` / `BLOCKING` with `rows_checked: 0` and the audit verdict
      `INCONCLUSIVE`; a declared time column that parses nowhere is `DD006 INCONCLUSIVE` / `HIGH` /
      `BLOCKING` with `parseable_timestamps: 0` and verdict `INCONCLUSIVE`, with DD005 `PASS` so the
      attribution is single. The installed 0.1.0 wheel on the identical fixtures reports
      `DD005 PASS` / `FORMAL_EVAL_SAFE` and `DD006 PASS` / `FORMAL_EVAL_SAFE`.
- [ ] Not re-run for 0.1.1, deliberately: the opt-in scale gate (`DATASET_DOCTOR_SCALE=1
      pytest tests/test_scale.py`) and the million-row real-world audits. The detector change is
      coverage semantics, already measured at scale in Acceptance #3; the 0.1.0 scale numbers stand.
- [x] Registered while verifying, **not** fixed: a relative dataset path costs a single-table
      directory its leakage answers (PROJECT_STATE section 10 item 9). Present identically in 0.1.0.

## 4c. Publish 0.1.2 (completed 2026-09-26, 00:01 +08:00)

One patch release, the DD013 image-folder fix from the fourth real-world acceptance. Same sequence
as 4b; every value below is measured from this run.

- [x] `main` received the fix [`117d161`](https://github.com/xihaian251/dataset-doctor/commit/117d161),
      the release commit [`107504e`](https://github.com/xihaian251/dataset-doctor/commit/107504e) and the
      publisher-retarget commit `84c6e6a`, no force push. [CI run 36154213424](https://github.com/xihaian251/dataset-doctor/actions/runs/36154213424)
      passed 8/8 on `107504e`; [run 36156570701](https://github.com/xihaian251/dataset-doctor/actions/runs/36156570701)
      passed 8/8 on `84c6e6a`.
- [x] Built from `git archive 107504e` in a throwaway venv on another drive (backend
      `hatchling 1.32.4`, read back from the wheel's own `WHEEL` metadata); `twine check` both `PASSED`.
- [x] Artefact equals commit: wheel 37 entries / 32 tracked modules and sdist 501 entries / 500
      tracked files byte-compared against `git show 107504e:<path>`; the only reported non-match is the
      relocated `dist-info/licenses/LICENSE`, verified identical to its blob separately.
- [x] Local build reproducible: unchanged across two `python -m build` runs. Wheel
      `d9cc458a…` (146 928 B), sdist `d785c10a2f5f6f04d57d64a0d955e4c2afe386a81133517029900342a8f82ecb`
      (440 442 B).
- [x] [TestPyPI run 36156039925](https://github.com/xihaian251/dataset-doctor/actions/runs/36156039925)
      built `107504e` on `ubuntu-latest`: sdist hash **equal** to the local one, wheel hash
      **different** (`3d7c73572d09985715de8af51dbe9e45c266a1dcee3829f823fc89dc084a9f1d`) at the same
      146 928 bytes - the 0.1.1 pattern, and why the publisher pins the Linux build.
- [x] Annotated `v0.1.2` resolves to `107504ed7d2f0caffea9dbc28ec25225a532fdb0` (checked with
      `git rev-parse v0.1.2^{}`), the release commit, not the retarget commit.
- [x] [GitHub Release v0.1.2](https://github.com/xihaian251/dataset-doctor/releases/tag/v0.1.2)
      published, not draft, not prerelease, notes exactly the three approved lines.
      **Difference from 4b recorded deliberately: this Release carries no binary assets.** The release
      form's attachment input is not reachable by the automation available here, and the release
      baseline forbids manual file uploads on the publishing path; the verified bytes are instead in
      the workflow artifacts and on PyPI, and the asset digests that 4b could cite are absent here.
- [x] [Production run 36157278939](https://github.com/xihaian251/dataset-doctor/actions/runs/36157278939)
      rebuilt frozen `107504e`, asserted name/version, and matched both pinned hashes under
      `sha256sum --check --strict` (`…whl: OK`, `…tar.gz: OK`), then uploaded through the existing
      Trusted Publishing (OIDC + `pypi` environment approval). The publish step's own in-toto
      `https://docs.pypi.org/attestations/publish/v1` statements name exactly the two hashes above.
      No `twine upload`, no API token, no second pipeline.
- [x] PyPI JSON for 0.1.2 lists both files at those hashes and sizes, `Requires-Python: >=3.11`,
      `License-Expression: Apache-2.0`, not yanked, and 0.1.2 is the project's latest version.
- [x] A fresh venv outside the checkout on another drive installed
      `dataset-doctor-audit[image]==0.1.2` from production PyPI: import resolves inside
      `site-packages`, `__version__` is `0.1.2`, `pip check` clean, Python 3.13.1. `pip download
      --no-deps --no-cache-dir` of the same version returned a wheel whose hash equals the pinned one,
      which is what proves the index rather than a local path supplied it.
- [x] DD013 verified on the published bytes with synthetic fixtures: an image folder whose test split
      is label-enriched reports `HIGH` / `WARNING` / `POTENTIAL` at TV 0.75 (0.1.1 said `PASS`), a
      proportionally identical folder stays `PASS`, and the tabular path still reports its pre-fix
      TV 0.350 unchanged. No MVTec was re-downloaded.
- [ ] Not re-run for 0.1.2, deliberately: the four real-world datasets of acceptances #1-#4 and the
      opt-in scale gate. The change is confined to which label source DD013 reads; the acceptance
      measurements that found it stand in PROJECT_STATE.

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
