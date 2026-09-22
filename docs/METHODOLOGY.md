# Methodology

Every threshold, formula and status rule this tool can emit, with the source line to check it
against. Values are the code's own defaults (`settings.get(...)` fallbacks), not documentation
aspirations. Where a number is literal in a detector instead of policy-wired, it says so.

Related: [PROJECT_STATE.md](PROJECT_STATE.md) (decisions and gaps) · the
[`rules/`](rules/) pages (per-rule measured output) · [COMPETITIVE_ANALYSIS.md](COMPETITIVE_ANALYSIS.md).

---

## 1. Identity, sampling, fingerprints

**Sample id.** Images: the relative path, so `sample_id == relative_path`. Tabular:
`stable_sample_id(split, declared_id)` when an id column is declared, else
`stable_sample_id(rel_path, row_index, row_digest[:64])` (`adapters/tabular.py:228`). Because the
split is part of the id, a row that changes split changes identity and is re-paired by content in
a diff - the mechanism behind [DD019](rules/DD019-split-drift.md).

**Paths are resolved on both sides** (`adapters/base.py::relative`) so `audit ./data` and
`audit /abs/data` yield identical ids and identical metadata-mode hashes.

**Fingerprint modes** (`manifest.py`):

| Mode | What is hashed | Use |
| --- | --- | --- |
| `metadata` | `relative_path\|size\|split\|label` (`metadata_key`), no file content | fast pass; integrity claims are lower bounds |
| `sampled` | content SHA256 of a seeded subset | large corpora; never presented as a complete hash |
| `full` | content SHA256 of every sample | the default for anything published |

`manifest_hash` sorts before digesting, so the digest is order-independent; sampled hashes are
labelled as partial in the report. Sampling is deterministic from `config.sampling.seed`, which is
what makes TEST 18 (repeated fingerprinting is stable) meaningful.

## 2. Statistics used, and what they are for

| Quantity | Definition in code | Used by |
| --- | --- | --- |
| SMD (standardised mean difference) | `mean(a) - mean(b)` over a pooled scale; for the degenerate case the scale is `quantile(pooled,0.95) - quantile(pooled,0.05)` (`metrics.py:116`) so a heavy-tailed column cannot inflate every comparison into "no shift" | DD012, DD017 |
| PSI | bucketed population stability index over the pooled quantile grid | DD012 |
| KS statistic | `scipy.stats.ks_2samp`, returns `(D, p)` (`metrics.py:123`) | DD012 (numeric columns only) |
| Benjamini-Hochberg | `benjamini_hochberg(p_values, alpha=0.05)` → `(rejected, adjusted)` (`metrics.py:182`) | DD012 FDR flags |
| Rank AUC | `_rank_auc` (`leakage.py:447`), Mann-Whitney style, computed only when ≥ 80% of the column parses as numeric and it has > 2 distinct values (`leakage.py:433`) | DD007 |
| Normalised mutual information | sklearn `mutual_info_classid`, normalised to [0,1] | DD007 (also the fallback for non-numeric columns, where AUC is undefined and the finding says so) |
| Total variation distance | on label frequency vectors | DD013 |
| Missingness delta | per-column `|rate_a - rate_b|` | DD015 |
| pHash Hamming distance | `imagehash` perceptual hash (optional extra), compared against a threshold | DD004 |

**Zero-variance columns** produce `|SMD| = inf` and are reported as `null`/`inf` rather than
clamped to 0: a column that is constant in one split is a fact worth seeing, and clamping hides
it. A categorical row carries an effect size and no p-value, and `fdr_significant` is `None`
rather than `False`.

## 3. Thresholds

### Leakage and duplicates

| Rule | Threshold | Configurable | Note |
| --- | --- | --- | --- |
| DD003 exact duplicate | content digest equality, no ratio | - | deterministic |
| DD004 near duplicate | `hamming_threshold: 6` (pHash) | `policies.near_duplicate.hamming_threshold`, `.method` | dataset-dependent by design (Limitation) |
| DD005 entity leakage | any shared group value across splits | - | 1 row is enough |
| DD006 temporal leakage | any test timestamp ≤ max train timestamp, plus inversion spread | `temporal.train_before_test` | needs a declared temporal column, else `NOT_RUN` |
| DD007 target leakage candidate | `min_single_feature_auc: 0.95` **or** normalised MI ≥ `candidate_mi`; exact functional dependence at `\|corr\| ≥ 0.999999` (`leakage.py:414`) | yes | `HEURISTIC` / `LOW` confidence always; FDR-corrected before escalation |
| DD008 identifier leakage | `unique_ratio > 0.98` (`leakage.py:122`); column-level uniqueness test with a name heuristic - `MEDIUM` when the name looks like an identifier, `LOW` otherwise (`leakage.py:534-546`) | `unique_ratio_threshold` | advisory: uniqueness alone is not leakage |
| DD009 label conflict | identical feature digest, differing label | - | `BLOCKING` inside evaluation, `POTENTIAL` in train alone |

### Structure and distribution

| Rule | Trigger | Severity mapping |
| --- | --- | --- |
| DD010 missing labels | any unlabelled row; `> 0.02` of the dataset escalates | `HIGH` inside evaluation · `MEDIUM` above 2% · `LOW` otherwise (`labels.py:174`); a label occupying `> 0.9` of rows is its own finding (`labels.py:224`) |
| DD011 class imbalance | minority ratio vs preset floor | `LOW`/`MEDIUM` by preset; never `BLOCKING` |
| DD012 feature shift | report a column when `\|SMD\| ≥ 0.2` (`min_std_mean_diff`) **or** `PSI ≥ 0.2` (`min_psi`, when the PSI grid is reliable) | `HIGH` at worst `\|SMD\| ≥ 0.8` · `MEDIUM ≥ 0.5` · `LOW` below (`distribution.py:247-275`); FDR at `fdr_alpha: 0.05` separates "big and significant" from "big and underpowered" |
| DD013 label shift | total variation ≥ `min_tv_distance: 0.05` | `HIGH ≥ 0.30` · `MEDIUM ≥ 0.15` · `LOW` below (`distribution.py:158-181`) |
| DD014 schema drift | declared-vs-observed column set and dtype mismatch | `HIGH` for a missing declared column, `MEDIUM` for dtype drift; needs a reference split (ambiguity A8) |
| DD015 missingness shift | any per-column rate delta | `MEDIUM` when `max|delta| ≥ 0.3`, else `LOW` (`distribution.py:466`) |
| DD016 corrupt sample | zero bytes, undecodable, truncation | `HIGH` when an evaluation split is hit, or when coverage is complete and `rate ≥ 0.01`; `MEDIUM` otherwise; `INCONCLUSIVE` when files were not opened (metadata mode) - reported as a lower bound (`integrity.py:61`) |
| DD017 image property shift | ≥ 5 samples per side and `\|SMD\| ≥ 0.5` (**literal**, not policy-wired - A10) | `MEDIUM` confidence: properties are proxies, and no p-value is published for them |
| DD018 version drift | `(added+removed+modified)/num_samples ≥ 0.05` → `MEDIUM`, else `LOW` (`versioning.py:97`) | relabels and moves are excluded from that numerator on purpose |
| DD019 split drift | any crossing; `into_test` matched on the **literal** name `test` | `CRITICAL` into test · `HIGH` other crossings, both `FAIL`/`BLOCKING`; relabels `HIGH`/`WARNING`/`POTENTIAL` |

### Reporting and privacy

| Rule | Trigger | Notes |
| --- | --- | --- |
| DD020 provenance | `is_empty`, then per-field `missing` list | `LOW` empty · `INFO` partial · none complete; `NONE` impact always |
| DD021 PII candidates | `matches > 0` and `matches/non_null ≥ min_match_ratio: 0.05`, per split | `MEDIUM`/`WARNING`/`NONE`/`LOW` confidence; `phone_like` vetoed by `_DATE_SHAPED`; values never copied |

## 4. From findings to a verdict

`rules.py::evaluate_formal_safety` (the single place the verdict is formed):

1. `BLOCKING` finding with an assertive status ⇒ `FORMAL_EVAL_INVALID`.
2. Otherwise any `MEDIUM`-or-worse `POTENTIAL` finding ⇒ `FORMAL_EVAL_RISKY`.
3. Otherwise, if a V0.1 priority rule in a gating category (leakage, duplicate, split integrity)
   came back `INCONCLUSIVE`/`UNSUPPORTED` **for this dataset type** ⇒ `INCONCLUSIVE`
   (`rules.py:448-455`). `NOT_RUN` is excluded: it encodes an off-switch (policy disabled, column
   never declared), and gating on it would leave every image dataset inconclusive.
4. Otherwise ⇒ `FORMAL_EVAL_SAFE`.

Extra guards on the same path: `total_samples == 0` ⇒ `INCONCLUSIVE` ("No samples were
discovered, so nothing could be measured"), and `unproven` catches a `BLOCKING` finding whose
status is not assertive - a blocking claim that failed to measure cannot silently pass either.

Exit codes: `0` ok · `1` gate tripped (`--ci` adds `INCONCLUSIVE`, `--strict` is a strict
superset of `--ci`, `--fail-on <severity>` never overrides a `BLOCKING` finding) · `2` bad
request · `3` internal error · `130` interrupted.

## 5. Reproducibility of a report

A report is a function of (dataset content, resolved config, tool version). `config_hash` and
`tool_version` are in every JSON report next to `identity.dataset_id` and
`identity.manifest_hash`, so a number can be traced to the exact fingerprint it was measured on.
The hash cache under `.dataset-doctor/` affects speed only; deleting it changes nothing.

## 6. What this methodology cannot do

- **Semantic leakage cannot be fully automated.** Two paraphrases of the same fact, or a feature
  computed from the label downstream of an obvious name, are out of reach of a deterministic
  audit. DD007/DD008 are candidates, labelled as such.
- **Near duplicate thresholds are dataset-dependent.** `hamming_threshold: 6` is a starting point,
  not a universal constant.
- **Distribution shift does not automatically mean invalid evaluation.** DD012/DD013/DD015 are
  `POTENTIAL` at worst; a shifted evaluation split can be exactly what a study set out to measure.
- **A heuristic that stays silent is not a PASS.** `INCONCLUSIVE`, `NOT_RUN` and `UNSUPPORTED` are
  distinct outcomes with distinct reasons, and the report prints all of them.
- **No detection-rate claim.** The fixtures in `examples/` are hand-planted, so they demonstrate
  wiring and non-regression; they are not evidence of precision or recall, and nothing in this
  repository should ever be read as one.
