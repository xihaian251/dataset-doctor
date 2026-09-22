"""DD011 class imbalance, DD012 feature shift, DD013 label shift,
DD015 missingness shift, DD017 image property shift.

Two disciplines hold throughout:

1. Effect size travels with the statistic. A KS p-value on 200k rows is significant
   for a difference nobody can observe, so severity is keyed to standardised mean
   difference / PSI / total variation, and the p-value is evidence, not the trigger
   (spec sections 44-46).
2. Multiple comparisons are corrected. With hundreds of features the KS p-values go
   through Benjamini-Hochberg and the report says so.

Shift findings say "measurable distribution shift", never "the model will fail":
whether a shift invalidates an evaluation is a task question, not a data question
(spec section 110).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .. import metrics
from ..models import (
    AuditStatus,
    Category,
    Confidence,
    DatasetType,
    EvidenceType,
    FormalImpact,
    Severity,
    SplitRole,
)
from .context import AuditContext, InsufficientEvidence, NotApplicable, build_finding


def _reference_and_targets(ctx: AuditContext) -> tuple[str, list[str]]:
    """Reference = the train split when one is recognised, else the first non-empty split."""
    sizes = {name: len(bucket) for name, bucket in ctx.by_split().items()}
    usable = sorted(name for name, size in sizes.items() if size > 0)
    if len(usable) < 2:
        raise NotApplicable("distribution comparison needs at least two non-empty splits", "NOT_RUN")
    trains = [name for name in usable if ctx.role_of(name) is SplitRole.TRAIN]
    reference = trains[0] if trains else usable[0]
    targets = [name for name in usable if name != reference]
    return reference, targets


# --------------------------------------------------------------- DD011 imbalance
def detect_class_imbalance(ctx: AuditContext) -> list[Any]:
    counts = {key: value for key, value in ctx.identity.class_counts.items() if key != "<unlabeled>" and value > 0}
    item = ctx.config.policies.item("class_imbalance")
    if not item.enabled:
        raise NotApplicable("policy class_imbalance.enabled = false", "NOT_RUN")
    if not counts:
        raise InsufficientEvidence(
            "no labels were discovered, so class balance cannot be measured. This is not a PASS."
        )
    settings = item.extra_settings()
    max_ratio = float(settings.get("max_imbalance_ratio", 20.0))
    min_share = float(settings.get("min_minority_ratio", 0.02))
    values = [float(counts[key]) for key in sorted(counts)]
    ratio = metrics.imbalance_ratio(values)
    share = metrics.minority_share(values)
    total = int(sum(values))

    if len(counts) < 2:
        return [
            build_finding(
                ctx,
                rule_id="DD011",
                sequence=1,
                title="Single-class label distribution",
                category=Category.DISTRIBUTION,
                severity=Severity.HIGH,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.STATISTICAL,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL,
                affected_count=total,
                description=f"All {total} labelled samples carry the class '{next(iter(counts))}'.",
                why_it_matters=(
                    "A one-class 'classification' evaluation has no discriminative content: accuracy equals "
                    "the majority rate by construction."
                ),
                evidence={"class_counts": counts},
                metadata={"scope": "dataset"},
            )
        ]

    if ratio <= max_ratio and share >= min_share:
        return []

    minority = sorted(counts.items(), key=lambda kv: kv[1])[:5]
    return [
        build_finding(
            ctx,
            rule_id="DD011",
            sequence=1,
            title=f"Class imbalance: {ratio:,.1f}:1 (majority to minority)",
            category=Category.DISTRIBUTION,
            severity=Severity.MEDIUM if share < min_share / 10 else Severity.LOW,
            status=AuditStatus.WARNING,
            evidence_type=EvidenceType.STATISTICAL,
            confidence=Confidence.HIGH,
            formal_impact=FormalImpact.POTENTIAL,
            affected_count=total,
            description=(
                f"{len(counts)} classes over {total} labelled samples; largest/minority = {ratio:.1f}, "
                f"minority share {share:.4f}, effective class count "
                f"{metrics.effective_class_count(values):.2f} of {len(counts)}."
            ),
            why_it_matters=(
                "Imbalance is a property of the world, not corruption. It matters here because accuracy on "
                "this mix is dominated by the majority class, so the headline metric is nearly constant "
                "however the minority class performs."
            ),
            evidence={
                "class_counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "imbalance_ratio": round(ratio, 3),
                "minority_share": round(share, 6),
                "entropy_bits": round(metrics.entropy(values), 4),
                "effective_class_count": round(metrics.effective_class_count(values), 3),
                "smallest_classes": [{"class": key, "count": value} for key, value in minority],
                "thresholds": {"max_imbalance_ratio": max_ratio, "min_minority_ratio": min_share},
            },
            recommended_action=(
                "Report per-class and balanced metrics; suppress this rule with a reason if the long tail is "
                "the point of the dataset."
            ),
            limitations=["Counts pool every split together; per-split class coverage is reported by DD013."],
            metadata={"scope": "dataset"},
        )
    ]


# ------------------------------------------------------------------ DD013 shift(y)
def detect_label_shift(ctx: AuditContext) -> list[Any]:
    item = ctx.config.policies.item("label_shift")
    if not item.enabled:
        raise NotApplicable("policy label_shift.enabled = false", "NOT_RUN")
    reference, targets = _reference_and_targets(ctx)
    label_column = ctx.label_column()
    findings: list[Any] = []
    sequence = 1
    for target in targets:
        train_counts = _label_counts(ctx, reference, label_column)
        test_counts = _label_counts(ctx, target, label_column)
        if not train_counts or not test_counts:
            continue
        keys = metrics.support_union(list(train_counts), list(test_counts))
        p = [train_counts.get(key, 0) for key in keys]
        q = [test_counts.get(key, 0) for key in keys]
        tv = metrics.tv_distance(p, q)
        jsd = metrics.jensen_shannon(p, q)
        threshold = float(item.extra_settings().get("min_tv_distance", 0.05))
        if tv < threshold:
            continue
        train_total = max(sum(train_counts.values()), 1)
        test_total = max(sum(test_counts.values()), 1)
        ranked = sorted(
            (
                (
                    abs(test_counts.get(key, 0) / test_total - train_counts.get(key, 0) / train_total),
                    key,
                )
                for key in keys
            ),
            reverse=True,
        )[:20]
        movers = [
            {
                "class": key,
                "train_share": round(train_counts.get(key, 0) / train_total, 4),
                "test_share": round(test_counts.get(key, 0) / test_total, 4),
            }
            for _, key in ranked
        ]
        severity = Severity.HIGH if tv >= 0.30 else Severity.MEDIUM if tv >= 0.15 else Severity.LOW
        findings.append(
            build_finding(
                ctx,
                rule_id="DD013",
                sequence=sequence,
                title=f"Label distribution shift: {reference} vs {target}",
                category=Category.DISTRIBUTION,
                severity=severity,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.STATISTICAL,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL,
                source_split=reference,
                target_split=target,
                affected_count=sum(test_counts.values()),
                description=(
                    f"P({label_column or 'y'}) differs between {reference} and {target}: "
                    f"total variation {tv:.3f}, Jensen-Shannon distance {jsd:.3f}."
                ),
                why_it_matters=(
                    "A weighted average over classes changes when prevalence changes, even with a fixed "
                    "confusion matrix. Comparing this test set's accuracy with a differently balanced one is "
                    "comparing different questions."
                ),
                evidence={
                    "tv_distance": round(tv, 4),
                    "js_distance": round(jsd, 4),
                    "train_total": sum(train_counts.values()),
                    "test_total": sum(test_counts.values()),
                    "largest_movers": movers,
                    "threshold": threshold,
                },
                limitations=[
                    "A test set deliberately enriched for rare cases is a design choice, not an error. "
                    "Report it as the evaluation protocol instead of 'fixing' it."
                ],
                metadata={"scope": "cross_split"},
            )
        )
        sequence += 1
    return findings


def _label_counts(ctx: AuditContext, split: str, label_column: str | None) -> dict[str, int]:
    frame = ctx.table(split)
    if frame is None or frame.empty:
        return {}
    if label_column and label_column in frame.columns:
        series = frame[label_column].dropna().astype(str)
    else:
        records = [record for record in ctx.records if record.split == split and record.label is not None]
        series = pd.Series([str(record.label) for record in records])
    if series.empty:
        return {}
    return {str(key): int(value) for key, value in series.value_counts().items()}


# --------------------------------------------------------------- DD012 shift(x)
def detect_feature_shift(ctx: AuditContext) -> list[Any]:
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("feature shift compares table columns; for images see DD017", "UNSUPPORTED")
    item = ctx.config.policies.item("feature_shift")
    if not item.enabled:
        raise NotApplicable("policy feature_shift.enabled = false", "NOT_RUN")
    settings = item.extra_settings()
    min_smd = float(settings.get("min_std_mean_diff", 0.2))
    min_psi = float(settings.get("min_psi", 0.2))
    alpha = float(settings.get("fdr_alpha", 0.05))
    reference, targets = _reference_and_targets(ctx)
    columns = ctx.feature_columns()
    if not columns:
        raise InsufficientEvidence("no feature columns remain after removing label/id/split columns")

    findings: list[Any] = []
    sequence = 1
    for target in targets:
        rows = _shift_rows(ctx, reference, target, columns, min_smd, min_psi)
        if not rows:
            continue
        corrected = [row for row in rows if "ks_pvalue" in row]
        if len(corrected) > 1:
            # Correct over every numeric column tested for this pair, then use the flags to
            # separate 'big and significant' from 'big but underpowered'. The p-values are read
            # back out of the sorted rows so a flag can never land on the wrong column;
            # categorical rows carry an effect size only, and say so.
            observed = [float(row["ks_pvalue"]) for row in corrected]
            rejected, adjusted = metrics.benjamini_hochberg(observed, alpha=alpha)
            for index, row in enumerate(corrected):
                row["fdr_significant"] = index in set(rejected)
                row["adjusted_pvalue"] = None if np.isnan(adjusted[index]) else round(float(adjusted[index]), 6)
        for row in rows:
            row.setdefault("fdr_significant", None)
        worst = max(row["abs_smd"] for row in rows)
        severity = Severity.HIGH if worst >= 0.8 else Severity.MEDIUM if worst >= 0.5 else Severity.LOW
        findings.append(
            build_finding(
                ctx,
                rule_id="DD012",
                sequence=sequence,
                title=f"Feature distribution shift: {reference} vs {target} ({len(rows)} column(s))",
                category=Category.DISTRIBUTION,
                severity=severity,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.STATISTICAL,
                confidence=Confidence.MEDIUM,
                formal_impact=FormalImpact.POTENTIAL,
                source_split=reference,
                target_split=target,
                columns=[str(row["column"]) for row in rows[:50]],
                affected_count=len(ctx.tables[target]),
                description=(
                    f"{len(rows)} of {len(columns)} feature column(s) exceed the shift thresholds "
                    f"(|std mean diff| >= {min_smd}, or PSI >= {min_psi} on splits large enough for "
                    f"PSI to clear its own noise floor); largest effect |SMD| = {worst:.2f}."
                ),
                why_it_matters=(
                    "Covariate shift means the evaluation is measured on a different input distribution than "
                    "training. That can be intentional (a harder benchmark) or a collection artefact - the "
                    "data cannot tell which, so the verdict is not 'invalid'."
                ),
                evidence={
                    "reference": reference,
                    "target": target,
                    "thresholds": {
                        "min_std_mean_diff": min_smd,
                        "min_psi": min_psi,
                        "fdr_alpha": alpha,
                        "psi_bins": PSI_BINS,
                        "psi_null_floor": f"(bins-1)/n_target = {(PSI_BINS - 1) / max(len(ctx.tables[target]), 1):.3f}",
                    },
                    "columns_tested": len(columns),
                    "columns_flagged": len(rows),
                    "top_shifts": rows[:20],
                    "multiple_testing": (
                        f"Benjamini-Hochberg across the {len(corrected)} numeric column(s) that crossed a "
                        f"threshold at FDR {alpha}; categorical rows report an effect size only."
                    ),
                },
                limitations=[
                    "Significance is never the trigger: with large splits almost any column is significant. "
                    "Severity comes from effect size.",
                    "PSI is always reported but only triggers where its null floor (bins-1)/n_target sits "
                    "below the cutoff; the row says psi_trigger_usable=false where it did not.",
                    "Rows are compared as pooled distributions; a shift that only appears jointly across "
                    "columns (covariance change) is invisible to per-column tests.",
                ],
                metadata={"scope": "cross_split"},
            )
        )
        sequence += 1
    return findings


PSI_BINS = 10


def _psi_above_noise_floor(n_target: int, min_psi: float) -> bool:
    """False when PSI on this split size cannot be told apart from its own sampling noise.

    With B quantile bins and no real shift, the observed probabilities still scatter
    around the expected ones, and every clipped near-empty bin contributes
    ``(1/n) * ln((1/n)/EPS)``. That leaves an expected floor near ``(B - 1) / n``, which
    on a 30-row split is ~0.3 - above the conventional 0.2 "moderate shift" cutoff.
    """
    if n_target <= 0:
        return False
    return ((PSI_BINS - 1) / n_target) < min_psi


def _shift_rows(
    ctx: AuditContext,
    reference: str,
    target: str,
    columns: list[str],
    min_smd: float,
    min_psi: float,
) -> list[dict[str, Any]]:
    left, right = ctx.tables[reference], ctx.tables[target]
    numeric = set(ctx.numeric_columns())
    rows: list[dict[str, Any]] = []
    for column in columns:
        if column not in left.columns or column not in right.columns:
            continue
        a, b = left[column], right[column]
        if column in numeric:
            a_values = pd.to_numeric(a, errors="coerce").dropna().to_numpy(dtype=float)
            b_values = pd.to_numeric(b, errors="coerce").dropna().to_numpy(dtype=float)
            if a_values.size < 5 or b_values.size < 5:
                continue
            smd = metrics.std_mean_diff(a_values, b_values)
            psi = metrics.population_stability_index(a_values, b_values, bins=PSI_BINS)
            ks_stat, ks_p = metrics.ks_statistic(a_values, b_values)
            # PSI is only a trigger where it can actually distinguish shift from binning
            # noise; on a 30-row split its null floor sits above the threshold.
            psi_reliable = _psi_above_noise_floor(int(b_values.size), min_psi)
            if abs(smd) < min_smd and not (psi >= min_psi and psi_reliable):
                continue
            rows.append(
                {
                    "column": column,
                    "kind": "numeric",
                    "train_mean": round(float(np.mean(a_values)), 6),
                    "test_mean": round(float(np.mean(b_values)), 6),
                    "train_std": round(float(np.std(a_values, ddof=1)), 6) if a_values.size > 1 else None,
                    "test_std": round(float(np.std(b_values, ddof=1)), 6) if b_values.size > 1 else None,
                    "std_mean_diff": round(smd, 4),
                    "abs_smd": round(abs(smd), 4),
                    "psi": round(psi, 4),
                    "psi_trigger_usable": psi_reliable,
                    "wasserstein": round(metrics.wasserstein_1d(a_values, b_values), 6),
                    "normalized_wasserstein": round(metrics.normalized_wasserstein(a_values, b_values), 4),
                    "ks_statistic": round(ks_stat, 4),
                    "ks_pvalue": ks_p,
                    "n_train": int(a_values.size),
                    "n_test": int(b_values.size),
                }
            )
        else:
            a_levels = a.dropna().astype(str)
            b_levels = b.dropna().astype(str)
            if a_levels.empty or b_levels.empty:
                continue
            keys = metrics.support_union(sorted(set(a_levels)), sorted(set(b_levels)))
            if len(keys) > 200:
                continue  # identifier-like; DD008 owns that question
            pa = [int((a_levels == key).sum()) for key in keys]
            pb = [int((b_levels == key).sum()) for key in keys]
            tv = metrics.tv_distance(pa, pb)
            jsd = metrics.jensen_shannon(pa, pb)
            if tv < min_smd / 2:
                continue
            rows.append(
                {
                    "column": column,
                    "kind": "categorical",
                    "tv_distance": round(tv, 4),
                    "js_distance": round(jsd, 4),
                    "abs_smd": round(tv * 2, 4),  # keep the severity scale comparable
                    "levels": len(keys),
                    "unseen_in_train": len(sorted(set(b_levels) - set(a_levels))),
                    "n_train": int(a_levels.size),
                    "n_test": int(b_levels.size),
                }
            )
    rows.sort(key=lambda row: -row["abs_smd"])
    return rows


# ----------------------------------------------------------- DD015 missingness
def detect_missingness_shift(ctx: AuditContext) -> list[Any]:
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("missingness is a table property", "UNSUPPORTED")
    item = ctx.config.policies.item("missingness_shift")
    if not item.enabled:
        raise NotApplicable("policy missingness_shift.enabled = false", "NOT_RUN")
    reference, targets = _reference_and_targets(ctx)
    threshold = float(item.extra_settings().get("min_rate_delta", 0.1))
    findings: list[Any] = []
    sequence = 1
    for target in targets:
        left, right = ctx.tables[reference], ctx.tables[target]
        deltas: list[dict[str, Any]] = []
        for column in [str(c) for c in left.columns if str(c) in right.columns]:
            before = float(left[column].isna().mean())
            after = float(right[column].isna().mean())
            if abs(after - before) >= threshold:
                deltas.append(
                    {
                        "column": column,
                        f"{reference}_missing_rate": round(before, 4),
                        f"{target}_missing_rate": round(after, 4),
                        "delta": round(after - before, 4),
                    }
                )
        if not deltas:
            continue
        deltas.sort(key=lambda row: -abs(row["delta"]))
        findings.append(
            build_finding(
                ctx,
                rule_id="DD015",
                sequence=sequence,
                title=f"Missingness shift between {reference} and {target}",
                category=Category.SCHEMA,
                severity=Severity.MEDIUM if max(abs(r["delta"]) for r in deltas) >= 0.3 else Severity.LOW,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.STATISTICAL,
                confidence=Confidence.HIGH,
                formal_impact=FormalImpact.POTENTIAL,
                source_split=reference,
                target_split=target,
                columns=[str(row["column"]) for row in deltas],
                description=(
                    f"{len(deltas)} column(s) changed missing rate by >= {threshold:.0%} between "
                    f"{reference} and {target}."
                ),
                why_it_matters=(
                    "Imputation learned on one missingness pattern behaves differently on another, and "
                    "missingness that correlates with the outcome (MNAR) leaks information through the "
                    "missing indicator itself."
                ),
                evidence={
                    "columns": deltas[:50],
                    "threshold": threshold,
                    "rows_train": len(left),
                    "rows_test": len(right),
                },
                metadata={"scope": "cross_split"},
            )
        )
        sequence += 1
    return findings


# --------------------------------------------------------- DD017 image properties
_IMAGE_PROPERTIES = ("width", "height", "brightness", "contrast")


def detect_image_property_shift(ctx: AuditContext) -> list[Any]:
    if ctx.dataset_type is not DatasetType.IMAGE:
        raise NotApplicable("image property shift applies to image datasets", "UNSUPPORTED")
    item = ctx.config.policies.item("image_property_shift")
    if not item.enabled:
        raise NotApplicable("policy image_property_shift.enabled = false", "NOT_RUN")
    by_split: dict[str, dict[str, list[float]]] = {}
    for record in ctx.records:
        if record.metadata.get("inspected") is False or "width" not in record.metadata:
            continue
        bucket = by_split.setdefault(record.split, {key: [] for key in _IMAGE_PROPERTIES})
        for key in _IMAGE_PROPERTIES:
            value = record.metadata.get(key)
            if isinstance(value, (int, float)):
                bucket[key].append(float(value))
        aspect = record.metadata.get("width") and record.metadata.get("height")
        if aspect:
            bucket.setdefault("aspect_ratio", []).append(
                float(record.metadata["width"]) / float(record.metadata["height"])
            )
    if len(by_split) < 2:
        raise InsufficientEvidence(
            "fewer than two splits have decoded pixel metadata; re-run with `--fingerprint full`"
        )
    properties = [*_IMAGE_PROPERTIES, "aspect_ratio"]
    trains = [name for name in by_split if ctx.role_of(name) is SplitRole.TRAIN]
    reference = trains[0] if trains else sorted(by_split)[0]
    findings: list[Any] = []
    sequence = 1
    for target in sorted(name for name in by_split if name != reference):
        shifted: list[dict[str, Any]] = []
        for prop in properties:
            a = by_split[reference].get(prop, [])
            b = by_split[target].get(prop, [])
            if len(a) < 5 or len(b) < 5:
                continue
            smd = metrics.std_mean_diff(a, b)
            if abs(smd) < 0.5:
                continue
            shifted.append(
                {
                    "property": prop,
                    f"{reference}_mean": round(float(np.mean(a)), 3),
                    f"{target}_mean": round(float(np.mean(b)), 3),
                    "std_mean_diff": round(smd, 3),
                    "ks_statistic": round(metrics.ks_statistic(a, b)[0], 3),
                }
            )
        if not shifted:
            continue
        findings.append(
            build_finding(
                ctx,
                rule_id="DD017",
                sequence=sequence,
                title=f"IMAGE_PROPERTY_SHIFT: {reference} vs {target}",
                category=Category.DISTRIBUTION,
                severity=Severity.MEDIUM if max(abs(row["std_mean_diff"]) for row in shifted) >= 1.5 else Severity.LOW,
                status=AuditStatus.WARNING,
                evidence_type=EvidenceType.STATISTICAL,
                confidence=Confidence.MEDIUM,
                formal_impact=FormalImpact.POTENTIAL,
                source_split=reference,
                target_split=target,
                affected_count=len(by_split[target].get("width", [])),
                description=(
                    f"{len(shifted)} image property(ies) differ materially between {reference} and {target}: "
                    + ", ".join(f"{row['property']} (|SMD| {abs(row['std_mean_diff']):.2f})" for row in shifted)
                    + "."
                ),
                why_it_matters=(
                    "Resolution or luminance differences between splits can be a preprocessing artefact that "
                    "the network latches onto. Whether it invalidates the evaluation depends on whether the "
                    "deployment images look like the test images - that is a task judgement, not a data one."
                ),
                evidence={"properties": shifted, "min_std_mean_diff": 0.5},
                limitations=[
                    "Brightness and contrast are mean/std of the luma channel, not perceptual colour "
                    "metrics; a palette difference with matched luminance will not appear here.",
                ],
                metadata={"scope": "cross_split"},
            )
        )
        sequence += 1
    return findings
