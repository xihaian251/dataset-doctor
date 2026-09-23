# Security Policy

## What this tool is

A local, read-only auditor. It reads a dataset directory and writes a report directory. It has no
network code path, no model, no database and no daemon, and it does not require an API key -
enforced by `tests/test_standalone.py`, which runs a full audit with the network switched off and
in a stripped child environment.

If you are evaluating whether to run it on data that may not leave the machine: the relevant
question is not "does it phone home" (it cannot) but "what does it write, and what ends up in the
report".

## Data handling guarantees

- **Read-only.** Files are opened for reading. The only writes are the `-o` report directory, the
  hash cache and snapshots under `<dataset>/.dataset-doctor/`, `init`'s config template, and
  `split`'s new, empty target directory.
- **No deletion, no mutation.** Every rule reports and recommends; `auto_fix_available` is `false`
  on all 21.
- **No personal values in reports.** DD021 emits counts only, with `values_shown: false`, and there
  is no code path that copies a scanned cell into a report. Label values are reported where a
  finding needs them (a conflict or a relabel is meaningless without them); sample text and image
  pixels never are.
- **Relative paths for data.** No finding and no coverage entry carries an absolute path: `evidence`,
  `description`, `location.paths` and `coverage.unreadable_files` are relative to the dataset root, so
  a report does not carry your home directory or your account name through a finding. `tests/test_privacy.py`
  asserts that over the committed fixtures and the report renderers, walking the dumped values rather than
  grepping the serialised text. Three exceptions, all by design and all outside the findings: the report
  header and `identity.root_path` echo the path you typed (so the header does carry it), a diff's `right`
  label is the resolved absolute path of the audited directory (`docs/rules/DD018`), and the repair plan's
  commands embed the root because a command you cannot paste is no use. Reports intended for outside the
  lab should be reviewed with that in mind.
- **Report contents are not redacted for you.** `report.json` contains column names, label values,
  ids, sizes, digests and a config snapshot. Treat it with the same care as a data dictionary -
  which is usually less sensitive than the data, but not nothing.

## Trust boundary: the dataset is untrusted input

The tool parses attacker-controllable filenames and file contents, so treat a dataset from an
unknown source as untrusted input:

- **Not hardened against hostile volume.** There is no file-size cap, no decompression budget and
  no per-file timeout. A multi-gigabyte Parquet file or a deeply nested folder will be walked and
  read as far as your machine allows. Hashing is streamed and the manifest is the only thing held
  in memory, which is what keeps a 48 000-file image corpus inside ~350 MB RSS - but nothing stops
  you from pointing it at something pathological.
- **Symlinks are not special-cased.** A symlink inside the dataset is read as if it were data,
  including one that resolves outside the root. Audit directories you control, or bind-mount what
  you want scanned.
- **Excel/Parquet parsing is delegated** to `openpyxl` and `pyarrow`. Their parser hardening is
  this tool's floor; keep them updated (`pip list --outdated`).
- **Report renderers escape** user-derived strings into Markdown/HTML; if you find a way to get
  live markup out of a filename or column name into `report.html`, that is a bug worth reporting.
- **`dataset-doctor.yaml` is config, not data.** It can set thresholds, presets and suppressions;
  do not load a config from an untrusted source. Suppressions require a reason and are echoed in
  the report, so a config cannot quietly turn off an inconvenient rule.

## Versioning safety note

Snapshots are stored inside the dataset (ADR 0005), which means anyone with the folder has the
audit history too - including `findings_digest`, i.e. which rules fired before. That is usually
what you want from a reproducibility artefact and sometimes what you do not want in a public
release dataset. Exclude `.dataset-doctor/` when publishing the data itself.

## Reporting a vulnerability

Report privately at the repository's security page,
**<https://github.com/xihaian251/dataset-doctor/security>**, using GitHub's **Report a vulnerability**
form there. It reaches the maintainer directly and keeps the exploit out of a public issue.
Private vulnerability reporting was enabled and verified after the first push on 2026-09-23.

**Do not disclose an unfixed vulnerability through a public issue**, and do not describe it in a pull
request, a discussion or a commit message first. This is not the ordinary "please search for existing
issues first" advice: the realistic attack path for this tool is a hostile dataset handed to somebody
else's audit run, so even a precise rule id plus the words "this crashes" tells an attacker where to
look. If you are unsure whether what you found is a vulnerability, file it in the private form and say
you are unsure - judging that is the maintainer's job, not a reason to post publicly.

If the form is missing later, ask a repository administrator to re-check
Settings → Code security and compliance → **Private vulnerability reporting** before disclosing
anything publicly. There is deliberately no unverified contact address here.

There is no disclosure timeline, no CVE numbering authority relationship and no security team yet.
That is stated rather than invented.

## Non-goals

This is not a PII scanner in the compliance sense (DD021 is a column-level heuristic at `LOW`
confidence, see `docs/rules/DD021-pii-exposure.md`), not a malware scanner, and not a sandbox.
Nothing here satisfies GDPR/HIPAA on its own; a `SAFE` verdict means "this dataset can support a
trustworthy evaluation", never "this data may be published".
