# 0004 - No LLM, no network, no GPU: the dependency floor is the feature

**Status:** accepted (2026-09-21)

## Context

V0.1's constraints (no GPU, no API key, no cloud, no external LLM, no database, no Docker; Windows
+ Linux + macOS; Python ≥ 3.11; 8 GB RAM) look like a limitation imposed from outside. They are
also the argument for the tool's existence: a leakage audit has to run on the machine holding the
data, on a cohort that may never legally leave it, and it has to give the same answer twice.

## Decision

Runtime dependencies are `pydantic`, `typer`, `rich`, `pandas`, `numpy`, `scipy`, `Pillow`,
`pyarrow`; optional extras add `imagehash` (near-duplicates) and `openpyxl` (Excel). Nothing else.
No HTTP client, no model framework, no vector store, no database driver - asserted in code by
`tests/test_standalone.py`, which also runs a full audit with the network switched off and in a
stripped child environment with no GPU.

## Consequences

- Detection is deterministic and inspectable: the price is that "semantic leakage" is out of scope
  and is published as a Limitation, not hidden behind a model call.
- An audit costs no tokens and cannot change its answer when a vendor updates a model.
- `pip install` works offline after the download, and `dataset-doctor-audit demo` can generate fixtures
  anywhere - which is how the README's first screen can show a real finding without asking for the
  reader's data.
- Some checks are weaker than a learned equivalent would be (image property shift instead of
  embedding similarity, pattern PII instead of a named-entity model). Each such rule states
  `HEURISTIC`/`LOW` confidence rather than borrowing unearned authority.
- If a model-backed rule is ever added it needs its own ADR, and it must stay opt-in with the
  default path unchanged.
