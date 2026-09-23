# Roadmap

V0.1 shipped the closed loop: fingerprint → audit → evidence → verdict → diff. Everything below is
a proposal with a stated reason, not a promise; the ordering is the order that removes the most
doubt per unit of work.

## V0.1.x - make the existing claims impossible to weaken

1. ~~**Close the test gaps in `docs/PROJECT_STATE.md` section 6**~~ Done 2026-09-22: DD008,
   DD013, DD017, DD020, DD021's ratio boundary and cross-split dedup, and DD001 by rule id all
   have named assertions.
2. **Re-measure every doc example in CI.** A script that regenerates the `Examples` blocks from the
   quoted command and fails on a diff. Half of V0.1's real bugs surfaced as overstated rendered
   text; this turns that accident into a gate.
3. ~~**Release process**~~ Done 2026-09-23: the public repository, project URLs, green CI,
   TestPyPI rehearsal, production PyPI 0.1.0, annotated `v0.1.0` tag at the frozen source commit,
   and GitHub Release. The next version needs its own validation; this status update does not
   release 0.1.1.
4. ~~`--fingerprint sampled` reporting and the `imagehash`-absent fallback need explicit tests~~
   Done 2026-09-22 (`test_fingerprint_sampled_declares_its_coverage_and_is_deterministic`,
   `test_dd004_without_imagehash_is_inconclusive_and_the_rest_still_runs`).

## V0.2 - broaden coverage without diluting the verdict

- **Text and document modalities**: near-duplicate detection over normalised text, and cross-split
  overlap for sentence spans. This is where semantic leakage hides, and the honest version needs
  characterisation studies we have not run - so it ships as `HEURISTIC`/`LOW` findings or not at all.
- **Group-aware splitting in `split`**: temporal splits (before/after a cutoff) and stratified
  group splits; the row-wise-versus-grouped contrast is already demonstrated in
  `tests/test_splitting.py` and deserves a first-class command surface.
- **Configurable `into_test` for DD019**: wire the escalation to `SplitRole.TEST` instead of the
  literal name `test` (ambiguity A11), with a regression run on `val`/`eval`-named splits.
- **Policy-wired DD017 floors** (A10) so image shift matches the other distribution rules.
- **JUnit/SARIF export** so a verdict can gate a pipeline that does not read Markdown.

## V0.3 - the parts that need a design document first

- **Incremental audit**: re-audit only the samples a diff touched, using the snapshot as the cache
  key. Correctness first: an incremental verdict that disagrees with a full one is worse than slow.
- **Multi-run provenance**: attach the audit to a training run (config hash + dataset
  `manifest_hash` + code commit) so a published number can be re-derived, which is the reproducibility
  half of the original motivation.
- **Threshold calibration on public benchmarks**: the detection-rate measurements V0.1 deliberately
  does not make. Requires a real protocol, negative controls, and publication of the failures -
  see the discipline in `AGENTS.md`.
- **Rule plugins**: a documented detector interface (`capabilities`, `NotApplicable`,
  `InsufficientEvidence`, evidence keys) so groups can add domain rules without forking.
- **A curated public dataset registry of known split layouts**, so `init` can pre-fill group and
  temporal columns instead of asking users to find them.

## Explicitly out of scope

Anything that mutates a dataset (de-duplication, imputation, re-labelling, automatic re-splitting
in place); anything requiring a model, an API key, a database or a daemon; a numeric "data health
score"; and any claim that semantic leakage has been detected rather than suspected.
