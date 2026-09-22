# 0002 - Every verdict carries its evidence; facts and severity are separated

**Status:** accepted (2026-09-21)

## Context

"Data health score" tools fail in two ways: a number with no location, and a severity assigned by
a model nobody can re-derive. The spec's requirement is stronger: each finding must answer what,
where, how many samples, why it matters, what the evidence is, how severe, auto-fixable, and
whether it disappears after the fix.

## Decision

`AuditFinding` (models.py) requires the evidence payload at construction time.
`build_finding()` in `detectors/context.py` sets defaults that fail loudly rather than optimistically:
`evidence_type=DETERMINISTIC`, `confidence=HIGH`, `formal_impact=POTENTIAL`. Detectors emit
*facts*; `rules.apply_policy` and `_policy_severity` are the only places a severity may change, and
suppression requires a reason string that the report keeps.

A rule that cannot measure raises `InsufficientEvidence` (⇒ `INCONCLUSIVE`) or `NotApplicable`
(⇒ `NOT_RUN` / `UNSUPPORTED`). Neither produces a `PASS`.

## Consequences

- Reports are auditable line by line: sample ids, digests, counts, split pairs. Three of this
  project's fixed defects were found *because* a rendered report was read as a reviewer would
  (PROJECT_STATE section 4).
- `evidence_type` must be `HEURISTIC` where the claim is heuristic - DD007, DD008, DD021 - and
  those findings state the competing explanation in `why_it_matters` instead of asserting a cause.
- Heuristics cannot escalate on their own authority: DD007 runs Benjamini-Hochberg across all
  tested columns before a column is allowed to affect the verdict.
- Cost: every finding needs evidence keys and caps designed, so detectors are longer than they
  would be in a score-emitting tool, and evidence lists are truncated (caps stated per rule doc).
