"""Rule registry and the policy engine that turns detector facts into verdicts.

Detectors produce facts; only this module decides severity (spec section 107).
Every rule carries a ``formal_impact``: whether the fact, if true, can invalidate a
formal evaluation. That axis, not severity, is what ``EvalSafety`` is computed from,
so a noisy-but-harmless label never drags a dataset to INVALID and a silent
train/test overlap never stays at MEDIUM.
"""

from __future__ import annotations

from .models import (
    AuditFinding,
    AuditRule,
    AuditStatus,
    Category,
    Confidence,
    DatasetType,
    EvidenceType,
    FormalImpact,
    RuleOutcome,
    Severity,
)

V01_RULES = {"DD001", "DD002", "DD003", "DD005", "DD009", "DD011", "DD012", "DD014", "DD016", "DD018", "DD019"}

REGISTRY: dict[str, AuditRule] = {
    rule.rule_id: rule
    for rule in [
        AuditRule(
            rule_id="DD001",
            name="Dataset Identity",
            description="Establish what this dataset is: samples, splits, classes, schema, fingerprint.",
            category=Category.IDENTITY,
            default_severity=Severity.INFO,
            formal_impact=FormalImpact.NONE,
            evidence_type=EvidenceType.DETERMINISTIC,
            remediation="Nothing to fix: this is the factual baseline every other rule cites.",
            implemented=True,
            doc_path="docs/rules/DD001-dataset-identity.md",
        ),
        AuditRule(
            rule_id="DD002",
            name="Split Integrity",
            description="Are train/val/test present, non-empty, disjoint in identity, and labelled?",
            category=Category.SPLIT_INTEGRITY,
            default_severity=Severity.HIGH,
            formal_impact=FormalImpact.BLOCKING,
            requires=["splits"],
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="A deliberately missing test split (external benchmark) is fine, "
            "but the tool cannot certify evaluation safety from train alone.",
            remediation="Materialise the missing split, or declare the split layout in dataset-doctor.yaml.",
            implemented=True,
            doc_path="docs/rules/DD002-split-integrity.md",
        ),
        AuditRule(
            rule_id="DD003",
            name="Exact Duplicate",
            description="Byte-identical files (images) or identical rows (tables) within and across splits.",
            category=Category.DUPLICATE,
            default_severity=Severity.CRITICAL,
            formal_impact=FormalImpact.BLOCKING,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Within-split duplication is a sample-weight problem, not a leakage "
            "problem; it is reported separately at lower severity. Synthetic or tile-based imagery "
            "can legitimately repeat.",
            remediation="Remove one member of each cross-split group (keep the earliest, or drop from "
            "train), then re-audit. Never let the tool delete data for you.",
            implemented=True,
            doc_path="docs/rules/DD003-exact-duplicate.md",
        ),
        AuditRule(
            rule_id="DD004",
            name="Near Duplicate",
            description="Perceptually similar images (pHash + Hamming distance) inside and across splits.",
            category=Category.DUPLICATE,
            default_severity=Severity.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            requires=["images"],
            evidence_type=EvidenceType.HEURISTIC,
            false_positive_notes="Threshold is dataset-dependent and always a judgement call: uniform "
            "or logo-like images collide at any threshold, and pHash misses crops and rotations. "
            "Visual similarity within one split is redundancy, not leakage.",
            remediation="Inspect the cited pairs, then either accept them as natural variation or "
            "de-duplicate with an explicit rule and re-audit.",
            implemented=True,
            doc_path="docs/rules/DD004-near-duplicate.md",
        ),
        AuditRule(
            rule_id="DD005",
            name="Group / Entity Leakage",
            description="The same entity (patient, user, device, session) appearing in more than one split.",
            category=Category.LEAKAGE,
            default_severity=Severity.CRITICAL,
            formal_impact=FormalImpact.BLOCKING,
            requires=["group_columns"],
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Only meaningful when the group key is a real entity id. A column named "
            "patient_id that is actually a per-row primary key produces one group per sample and hides "
            "nothing; a column that repeats per hospital visit is a grouping factor by design.",
            remediation="Re-split with `dataset-doctor split --group-by <column>` so each entity lands in "
            "exactly one split, then re-audit.",
            implemented=True,
            doc_path="docs/rules/DD005-group-leakage.md",
        ),
        AuditRule(
            rule_id="DD006",
            name="Temporal Leakage",
            description="Training rows dated after evaluation rows.",
            category=Category.LEAKAGE,
            default_severity=Severity.HIGH,
            formal_impact=FormalImpact.BLOCKING,
            requires=["temporal_column"],
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Overlapping time ranges are legitimate for i.i.d. tasks (a random sample "
            "of historical events). Only policy-driven: DD006 fires when the config says the task forecasts "
            "the future.",
            remediation="Split by time (train earliest, test latest) with an embargo window if records cluster.",
            implemented=True,
            doc_path="docs/rules/DD006-temporal-leakage.md",
        ),
        AuditRule(
            rule_id="DD007",
            name="Target Leakage",
            description="A feature that is the target, a deterministic transform of it, or suspiciously predictive.",
            category=Category.LEAKAGE,
            default_severity=Severity.CRITICAL,
            formal_impact=FormalImpact.BLOCKING,
            requires=["tabular", "label"],
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Level 2 (high mutual information / single-feature AUC) is a CANDIDATE, "
            "never a verdict: a biomarker that genuinely predicts disease is high-signal, not leaked. "
            "Semantic leakage cannot be detected from data alone.",
            remediation="Confirm with domain knowledge what the column measures and when it becomes known; "
            "drop it (and any derived feature) from the model matrix.",
            implemented=True,
            doc_path="docs/rules/DD007-target-leakage.md",
        ),
        AuditRule(
            rule_id="DD008",
            name="Identifier / Feature Leakage",
            description="Near-unique id-like or path-like columns carried into the feature matrix.",
            category=Category.LEAKAGE,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            requires=["tabular"],
            evidence_type=EvidenceType.HEURISTIC,
            false_positive_notes="A high-cardinality free-text column is not an identifier. If the id is "
            "correlated with the target through the collection process it becomes memorisable leakage.",
            remediation="Drop identifier columns from features, or register them as `id_columns` so the "
            "tool treats them as identity rather than signal.",
            implemented=True,
            doc_path="docs/rules/DD008-identifier-leakage.md",
        ),
        AuditRule(
            rule_id="DD009",
            name="Label Conflict",
            description="Identical content carrying different labels.",
            category=Category.LABEL,
            default_severity=Severity.CRITICAL,
            formal_impact=FormalImpact.BLOCKING,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Duplicate images with different labels are ambiguous only if content is "
            "truly identical; near-identical frames with different labels are a labelling-policy question.",
            remediation="Decide a single label per content hash (majority, or expert review) and re-audit.",
            implemented=True,
            doc_path="docs/rules/DD009-label-conflict.md",
        ),
        AuditRule(
            rule_id="DD010",
            name="Missing Labels",
            description="Samples with no label, a null-labelled folder, or a label column that is not classes.",
            category=Category.LABEL,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Unlabelled data is normal in semi-supervised setups; it must not be "
            "silently counted as evaluation coverage.",
            remediation="Label, exclude explicitly, or move unlabelled material out of the eval split.",
            implemented=True,
            doc_path="docs/rules/DD010-missing-labels.md",
        ),
        AuditRule(
            rule_id="DD011",
            name="Class Imbalance",
            description="Class frequencies, minority share, entropy and effective class count.",
            category=Category.DISTRIBUTION,
            default_severity=Severity.LOW,
            formal_impact=FormalImpact.POTENTIAL,
            evidence_type=EvidenceType.STATISTICAL,
            false_positive_notes="Imbalance is a property of the world, not an error. Long-tail datasets "
            "are imbalance by design; suppress with a reason rather than accept noise.",
            remediation="Choose metrics and resampling that fit the minority class size; suppress the rule "
            "with a documented reason if the tail is intentional.",
            implemented=True,
            doc_path="docs/rules/DD011-class-imbalance.md",
        ),
        AuditRule(
            rule_id="DD012",
            name="Feature / Distribution Shift",
            description="Train vs test differences per feature, with effect size, not only significance.",
            category=Category.DISTRIBUTION,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            requires=["tabular"],
            evidence_type=EvidenceType.STATISTICAL,
            false_positive_notes="A measurable shift is not an invalid evaluation; covariate shift is the "
            "point of many benchmarks. Thresholds are reported, never converted into causality.",
            remediation="Confirm the shift is expected in deployment; if not, re-sample or re-label the "
            "affected split.",
            implemented=True,
            doc_path="docs/rules/DD012-feature-shift.md",
        ),
        AuditRule(
            rule_id="DD013",
            name="Label Distribution Shift",
            description="P_train(y) vs P_test(y) via total variation and Jensen-Shannon distance.",
            category=Category.DISTRIBUTION,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            evidence_type=EvidenceType.STATISTICAL,
            false_positive_notes="If the test set is enriched for rare cases on purpose, the difference is "
            "intended - report it, do not fail it.",
            remediation="Use metrics robust to prevalence shift, or document the intended difference.",
            implemented=True,
            doc_path="docs/rules/DD013-label-shift.md",
        ),
        AuditRule(
            rule_id="DD014",
            name="Schema Drift",
            description="Column presence, dtype and categorical level mismatches between splits.",
            category=Category.SCHEMA,
            default_severity=Severity.HIGH,
            formal_impact=FormalImpact.BLOCKING,
            requires=["tabular"],
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="A column dropped from test because it is only available at training time "
            "(e.g. an annotation artefact) is correct, not drift.",
            remediation="Rebuild the split from one schema version, or map dtypes explicitly at load time.",
            implemented=True,
            doc_path="docs/rules/DD014-schema-drift.md",
        ),
        AuditRule(
            rule_id="DD015",
            name="Missingness Shift",
            description="Per-column missing rate compared between splits.",
            category=Category.SCHEMA,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            requires=["tabular"],
            evidence_type=EvidenceType.STATISTICAL,
            false_positive_notes="Missingness that correlates with the target is informative (MNAR), which "
            "is a modelling question, not corruption.",
            remediation="Check the collection pipeline version; impute consistently across splits.",
            implemented=True,
            doc_path="docs/rules/DD015-missingness-shift.md",
        ),
        AuditRule(
            rule_id="DD016",
            name="Corrupt Sample",
            description="Unreadable, truncated or zero-byte files, and table files that fail to parse.",
            category=Category.INTEGRITY,
            default_severity=Severity.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="One corrupt file in 10k is a nuisance; corrupt files concentrated in the "
            "test split silently change what is being measured.",
            remediation="Re-download or re-export the affected files; if they sit in the eval split, "
            "re-materialise that split.",
            implemented=True,
            doc_path="docs/rules/DD016-corrupt-sample.md",
        ),
        AuditRule(
            rule_id="DD017",
            name="Image Property Shift",
            description="Resolution, aspect ratio, brightness, contrast and channel count compared between splits.",
            category=Category.DISTRIBUTION,
            default_severity=Severity.LOW,
            formal_impact=FormalImpact.POTENTIAL,
            requires=["images"],
            evidence_type=EvidenceType.STATISTICAL,
            false_positive_notes="A resolution difference is often a deliberate preprocessing consequence "
            "(one split was exported at a different DPI). This rule states IMAGE_PROPERTY_SHIFT, never "
            "'the model will fail'.",
            remediation="Normalise preprocessing identically across splits, or document the difference as "
            "part of the evaluation protocol.",
            implemented=True,
            doc_path="docs/rules/DD017-image-property-shift.md",
        ),
        AuditRule(
            rule_id="DD018",
            name="Version Drift",
            description="What changed between two fingerprints: added, removed, modified samples.",
            category=Category.VERSIONING,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.POTENTIAL,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Additions and removals are normal maintenance; the audit-relevant cases "
            "are label flips and split moves.",
            remediation="Record snapshots of every dataset a published number came from, then diff before "
            "comparing numbers across runs.",
            implemented=True,
            doc_path="docs/rules/DD018-version-drift.md",
        ),
        AuditRule(
            rule_id="DD019",
            name="Split Drift",
            description="Samples that moved between splits across versions.",
            category=Category.VERSIONING,
            default_severity=Severity.CRITICAL,
            formal_impact=FormalImpact.BLOCKING,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="A move train->test after results were reported is the textbook way for a "
            "number to improve without the model improving.",
            remediation="Explain every move in the changelog; never compare metrics computed on different "
            "split assignments.",
            implemented=True,
            doc_path="docs/rules/DD019-split-drift.md",
        ),
        AuditRule(
            rule_id="DD020",
            name="Dataset Provenance",
            description="Declared source, version, licence and acquisition date.",
            category=Category.PROVENANCE,
            default_severity=Severity.LOW,
            formal_impact=FormalImpact.NONE,
            evidence_type=EvidenceType.DETERMINISTIC,
            false_positive_notes="Missing provenance is a reproducibility gap, not a corruption.",
            remediation="Fill in the `provenance:` block of dataset-doctor.yaml.",
            implemented=True,
            doc_path="docs/rules/DD020-provenance.md",
        ),
        AuditRule(
            rule_id="DD021",
            name="PII Exposure",
            description="Columns whose values look like email, phone or national id; reported as counts only.",
            category=Category.PRIVACY,
            default_severity=Severity.MEDIUM,
            formal_impact=FormalImpact.NONE,
            requires=["tabular"],
            evidence_type=EvidenceType.HEURISTIC,
            false_positive_notes="Pattern matching over-reports: any 10-digit number can look like a phone "
            "number. Values are never copied into the report.",
            remediation="Decide what may leave the lab; tokenise or drop the column.",
            implemented=True,
            doc_path="docs/rules/DD021-pii-exposure.md",
        ),
    ]
}

RULE_TO_POLICY: dict[str, str] = {
    "DD001": "dataset_identity",
    "DD002": "split_integrity",
    "DD003": "exact_duplicate",
    "DD004": "near_duplicate",
    "DD005": "group_leakage",
    "DD006": "temporal_leakage",
    "DD007": "target_leakage",
    "DD008": "identifier_leakage",
    "DD009": "label_conflict",
    "DD010": "missing_labels",
    "DD011": "class_imbalance",
    "DD012": "feature_shift",
    "DD013": "label_shift",
    "DD014": "schema_drift",
    "DD015": "missingness_shift",
    "DD016": "corrupt_sample",
    "DD017": "image_property_shift",
    "DD018": "version_drift",
    "DD019": "split_drift",
    "DD020": "provenance",
    "DD021": "pii_scan",
}

POLICY_TO_RULE: dict[str, str] = {value: key for key, value in RULE_TO_POLICY.items()}


def rule_for(rule_id: str) -> AuditRule:
    try:
        return REGISTRY[rule_id]
    except KeyError:  # pragma: no cover - ids come from the registry
        raise KeyError(f"Unknown rule id '{rule_id}'") from None


def apply_policy(finding: AuditFinding, config_severity: Severity | None) -> AuditFinding:
    """The only place a severity can change. Policy overrides, heuristics never do."""
    if config_severity is not None and config_severity != finding.severity:
        metadata = dict(finding.metadata)
        metadata["severity_source"] = "policy"
        metadata["default_severity"] = finding.severity.value
        return finding.model_copy(update={"severity": config_severity, "metadata": metadata})
    return finding


def outcome_for(rule_id: str, findings: list[AuditFinding], status: AuditStatus, **kwargs: object) -> RuleOutcome:
    rule = rule_for(rule_id)
    highest = max((f.severity for f in findings), default=None)
    return RuleOutcome(
        rule_id=rule_id,
        name=rule.name,
        status=status,
        finding_count=len(findings),
        highest_severity=highest,
        **kwargs,  # type: ignore[arg-type]
    )


def eval_safety(
    findings: list[AuditFinding],
    outcomes: list[RuleOutcome],
    total_samples: int,
    dataset_type: DatasetType,
) -> tuple[str, list[str]]:
    """Aggregate verdict. Deliberately rule-based and explainable, never a weighted score."""
    from .models import EvalSafety as _ES

    reasons: list[str] = []
    # Only a finding that actually *asserts* something can move the verdict. A HIGH finding with
    # status INCONCLUSIVE is this tool saying "I could not rule this out", which belongs in the
    # INCONCLUSIVE branch - letting it force INVALID or RISKY would be a guess wearing evidence.
    assertive = (AuditStatus.FAIL, AuditStatus.WARNING)
    blocking = [f for f in findings if f.formal_impact == FormalImpact.BLOCKING and f.status in assertive]
    if blocking:
        for finding in blocking[:8]:
            reasons.append(
                f"{finding.rule_id} {finding.title}: {finding.affected_count} samples (status {finding.status.value})"
            )
        return _ES.FORMAL_EVAL_INVALID.value, reasons

    inconclusive = [o for o in outcomes if o.status == AuditStatus.INCONCLUSIVE]
    not_run = [o for o in outcomes if o.status in (AuditStatus.NOT_RUN, AuditStatus.UNSUPPORTED)]
    unsupported = [o for o in outcomes if o.status == AuditStatus.UNSUPPORTED]
    risky = [
        f
        for f in findings
        if f.status in assertive
        and f.severity.rank >= Severity.MEDIUM.rank
        and f.formal_impact in (FormalImpact.BLOCKING, FormalImpact.POTENTIAL)
    ]
    # "Leakage-first" is the promise, so a coverage gap on a *core* rule may not be printed
    # over with a SAFE. Scoped to the V0.1 priority rules of the categories that carry that
    # promise (leakage, duplicate, split integrity) and to the statuses that mean "this could
    # not be answered": NOT_RUN stays out, because in this codebase it encodes a deliberate
    # off-switch (policy disabled, optional column never declared) rather than a blocked
    # measurement - and gating on it would leave every image dataset permanently INCONCLUSIVE
    # just because nobody declared a patient id per file.
    _gating = (Category.LEAKAGE, Category.DUPLICATE, Category.SPLIT_INTEGRITY)
    core_gaps = [
        outcome
        for outcome in inconclusive + unsupported
        if outcome.rule_id in V01_RULES
        and REGISTRY[outcome.rule_id].category in _gating
        and dataset_type in REGISTRY[outcome.rule_id].applies_to
    ]
    unproven = [f for f in findings if f.formal_impact == FormalImpact.BLOCKING and f.status not in assertive]
    if total_samples == 0:
        return _ES.INCONCLUSIVE.value, ["No samples were discovered, so nothing could be measured."]
    if risky:
        for finding in risky[:8]:
            reasons.append(
                f"{finding.rule_id} {finding.title}: {finding.affected_count} samples, "
                f"severity {finding.severity.value}"
            )
        verdict = _ES.FORMAL_EVAL_RISKY.value
    elif core_gaps or unproven:
        for outcome in core_gaps:
            detail = outcome.skip_reason or next(
                (f.description for f in findings if f.rule_id == outcome.rule_id), "insufficient evidence"
            )
            reasons.append(f"{outcome.rule_id} could not be measured: {detail}.")
        for finding in unproven[:8]:
            reasons.append(f"{finding.rule_id} {finding.title}: flagged as potentially invalidating but not confirmed.")
        reasons.append(
            "The rules that did run found nothing blocking. That is not the same as safe: the core "
            "leakage question is unanswered for this dataset."
        )
        verdict = _ES.INCONCLUSIVE.value
    elif len(inconclusive) >= max(3, len(outcomes) // 3):
        # Too many rules could not answer to claim the dataset is clean.
        gaps = ", ".join(sorted(o.rule_id for o in inconclusive))
        reasons.append(
            f"{len(inconclusive)} of {len(outcomes)} rules returned INCONCLUSIVE ({gaps}); "
            "the rules that did run found nothing blocking, but that is not enough to call the "
            "evaluation safe."
        )
        verdict = _ES.INCONCLUSIVE.value
    else:
        verdict = _ES.FORMAL_EVAL_SAFE.value

    if (inconclusive or not_run) and verdict == _ES.FORMAL_EVAL_SAFE.value:
        gaps = ", ".join(sorted({o.rule_id for o in inconclusive} | {o.rule_id for o in not_run}))
        reasons.append(
            f"Coverage gap: {len(inconclusive)} rule(s) INCONCLUSIVE, {len(not_run)} not run/skipped ({gaps}). "
            "'SAFE' here means 'no blocking issue found by the rules that could run'."
        )
    return verdict, reasons


def severity_counts(findings: list[AuditFinding]) -> dict[str, int]:
    counts = {severity.value: 0 for severity in Severity}
    for finding in findings:
        counts[finding.severity.value] += 1
    return {key: value for key, value in counts.items() if value}


def dataset_types() -> list[DatasetType]:
    return [DatasetType.TABULAR, DatasetType.IMAGE]


def confidence_note(confidence: Confidence) -> str:
    return {
        Confidence.HIGH: "deterministic evidence, re-computable from the manifest",
        Confidence.MEDIUM: "measurement is exact but interpretation depends on dataset assumptions",
        Confidence.LOW: "heuristic signal, requires human confirmation",
    }[confidence]
