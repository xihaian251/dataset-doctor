# 0003 - Leakage-first: a four-valued evaluation-validity verdict, never a score

**Status:** accepted (2026-09-21)

## Context

The two claims that make this project worth building (spec sections 220-222) are: audit for
leakage *first*, and separate a data quality issue from an evaluation validity issue. Existing
tools report quality richly and validity implicitly. An implicit validity claim is the one that
shows up in a published number.

## Decision

Every finding carries `formal_impact ∈ {NONE, POTENTIAL, BLOCKING}`, independently of its severity,
and the run ends in exactly one of `FORMAL_EVAL_SAFE / RISKY / INVALID / INCONCLUSIVE`
(`rules.py::evaluate_formal_safety`, algorithm in [METHODOLOGY](../METHODOLOGY.md) section 4).
There is no health score, no 0-100 gauge, and no numeric aggregate anywhere in the data model.
`impact` is per finding, so DD019 emits `BLOCKING` moves and `POTENTIAL` relabels from one diff.

Coverage is gated too: if a V0.1 priority rule in a leakage/duplicate/split-integrity category
comes back `INCONCLUSIVE` or `UNSUPPORTED` for this dataset type, the verdict cannot be `SAFE`.

## Consequences

- A dataset with 200 informational findings and one `BLOCKING` is `INVALID`, which is the point -
  and the reason a `SAFE` verdict costs more to earn than a high score in a profile.
- `--ci` / `--strict` gate on the verdict, so CI failure and "this experiment is untrustworthy" are
  the same statement, not two conventions that can drift apart.
- `NOT_RUN` is deliberately excluded from the coverage gate (a policy off-switch is not a blocked
  measurement); the trade-off is that a user who disables DD005 can reach `SAFE` without entity
  checking - the report prints the disabled rule and the reason, and `docs/` says so.
- The four-valued verdict cannot express "80% safe", which reviewers sometimes want. It is a
  gate, not a ranking: ranking invites the comparison of numbers across datasets that this project
  exists to distrust.
