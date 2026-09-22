# 0001 - Read-only by default, no mutation API at all

**Status:** accepted (2026-09-21)

## Context

The spec's prohibitions list auto-deletion, auto-overwrite of splits and auto-modification of raw
data as failure modes, not as features to gate behind a flag. A tool whose job is to tell you that
your evaluation is broken must never be the thing that changes the evaluation.

## Decision

`dataset_doctor` has no code path that writes to a dataset. Adapters open files read-only; the
only writes in the whole package are (a) the `-o` report directory, (b) the hash cache under
`<dataset>/.dataset-doctor/`, (c) `init`'s config template, and (d) `split`, which writes into a
**new** directory and refuses a non-empty target. Recommended actions are text, and every
remediation in `docs/rules/` is phrased as something the user does in their pipeline.

## Consequences

- `auto_fix_available` is `false` on all 21 rules, so the report can be trusted as "nothing here
  was silently applied".
- Near-duplicate remediation suggests quarantine lists rather than deletion, even though deletion
  would be more convenient.
- Users who want an automated cleaner must use another tool (the PyPI `dataset-doctor` that owns
  our name is exactly that, `COMPETITIVE_ANALYSIS.md` A16). That confusion is a marketing cost we
  accept deliberately.
- `split` is the one write-like command, guarded by: refuse non-empty target, fail before writing
  if a split would come out empty, never touch the source directory (three tests in
  `tests/test_splitting.py`).
