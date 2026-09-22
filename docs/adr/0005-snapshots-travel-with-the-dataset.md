# 0005 - Snapshots live inside the dataset they describe

**Status:** accepted (2026-09-21)

## Context

Dataset versioning normally means an external store (DVC, a database, a registry). The audit
needs the opposite property: a comparison between *this* dataset and the one audited last month,
provable without a service, after the files moved between laptops. Drift that matters most is
drift a snapshot catches: samples added, labels flipped, and rows that crossed into the test
split.

## Decision

A snapshot is a JSON file under `<dataset>/.dataset-doctor/snapshots/<name>.json`, written by
`audit --save-snapshot NAME` or `snapshot --name NAME`. It stores the manifest (ids, splits,
labels, sizes, digests per fingerprint mode) plus, when the run was an audit, `findings_digest`.
`--baseline` accepts a snapshot name, a dataset id, or a path. A cross-fingerprint-mode or
cross-type diff is refused rather than attempted (ambiguity A14, `docs/rules/DD018`).

## Consequences

- The snapshot travels with the data: no daemon, no credentials, and a reviewer who has the folder
  has the history. It also means a snapshot is meaningless once detached from its dataset, which
  is why `snapshot --directory` output cannot be fed to another dataset's `--baseline` (A7) and why
  the error message says so.
- Snapshotting the *audit* (not just the manifest) is what allows finding-level
  `new/resolved/changed` diffing. During an audit `finding_changes` is empty by construction, and
  the finding carries a limitation saying so instead of reporting the baseline's findings as
  resolved (A13 - this was a real defect, fixed, with a test).
- Files inside the dataset is also the risk: `.dataset-doctor/` must never be treated as data. The
  directory is in the ignore list every walker consults, and `test_editor_and_archive_artefacts_are_never_read_as_data`
  guards the neighbouring case.
- Hash cache and snapshots share the folder, so deleting `.dataset-doctor/` loses speed and
  history but never data. That is stated in the README.
