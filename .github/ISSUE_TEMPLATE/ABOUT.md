# What "reporting a problem" means here

Three shapes of issue, because they need different evidence:

- **A false positive or a wrong verdict.** The most useful report is a *minimal* dataset
  (even 8 rows) plus the command plus `report.json`. Say which rule id fired and what you
  believe the correct status was. If you suppressed it with `suppress:` and the reason is
  contestable, say so - several V0.1 rules were tuned exactly that way.
- **A crash, or a rule that reports `INCONCLUSIVE` where it could have measured.** The
  traceback and the `dataset-doctor.yaml` are the whole report. Redact data values, not
  column names - the names are usually what identifies the bug.
- **Something that should not be in a report.** A raw value from a PII-suspect column, an
  absolute path in a finding, an unescaped markup in `report.html`: see
  [SECURITY.md](../SECURITY.md) instead of opening a public issue.

Do not attach the dataset if it holds personal or clinical data. `report.json` is already a
data dictionary; strip `identity.root_path` if the path itself identifies someone.

Please include the version (the `tool_version` field in `report.json`, or
`pip show dataset-doctor-audit`), the OS, the Python version, and the `--fingerprint` mode
you used - `metadata` costs rule coverage, so a missing rule in your report may be a mode
effect rather than a bug.
