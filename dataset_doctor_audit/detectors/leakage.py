"""DD005 entity/group leakage, DD006 temporal leakage, DD007 target leakage,
DD008 identifier leakage.

The common thread: each of these can make a test number look good without the model
being good. Entity leakage is exact and reportable as CRITICAL; target leakage is split
into a deterministic layer and a heuristic layer, and the heuristic layer is only ever a
CANDIDATE (spec sections 34-37).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable
from typing import Any

import numpy as np
import pandas as pd

from ..models import (
    AuditStatus,
    Category,
    Confidence,
    EvidenceType,
    FormalImpact,
    Severity,
    SplitRole,
)
from .context import AuditContext, InsufficientEvidence, NotApplicable, build_finding


# ------------------------------------------------------------------ DD005 group
def detect_group_leakage(ctx: AuditContext) -> list[Any]:
    if not ctx.spec.group_columns:
        raise NotApplicable("no group columns declared (groups.columns / groups.entity_column)", "NOT_RUN")
    available = ctx.group_column_available()
    if not available:
        raise InsufficientEvidence(
            f"declared group columns {ctx.spec.group_columns} are not present in the data, so entity "
            "leakage cannot be measured. This is not a PASS."
        )
    ctx.needs_splits()
    findings: list[Any] = []
    sequence = 1
    by_split = dict(ctx.tables)
    for column in available:
        presence: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        positions: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
        rows_in_scope = 0
        rows_without_entity = 0
        for split, frame in by_split.items():
            if column not in frame.columns:
                continue
            for position, value in enumerate(frame[column].tolist()):
                rows_in_scope += 1
                key = _entity_key(value)
                if key is None:
                    # An absent entity is not an entity. It is counted here rather than
                    # passed into the comparison, because skipping it silently is how a
                    # rule with 20% coverage ends up reporting PASS.
                    rows_without_entity += 1
                    continue
                presence[key][split] += 1
                positions[key][split].append(position)
        checked = rows_in_scope - rows_without_entity
        coverage = _entity_coverage(rows_in_scope, rows_without_entity)
        if not presence:
            findings.append(_unmeasurable_group_column(ctx, column, coverage, sequence))
            sequence += 1
            continue
        unique_ratio = len(presence) / max(checked, 1)
        cross = {e: dict(sp) for e, sp in presence.items() if len(sp) > 1}
        if not cross:
            degenerate = _degenerate_group_column(ctx, column, presence, unique_ratio, sequence)
            if degenerate is not None:
                findings.append(degenerate)
                sequence += 1
            if rows_without_entity:
                findings.append(_partial_entity_coverage(ctx, column, coverage, sequence))
                sequence += 1
            continue
        for split_a, split_b, entities in _entity_pairs(ctx, cross):
            affected = [
                f"{split}:{position}"
                for entity, splits in entities.items()
                for split in splits
                for position in positions[entity][split]
            ]
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD005",
                    sequence=sequence,
                    title=f"Entity leakage on '{column}': {split_a} / {split_b}",
                    category=Category.LEAKAGE,
                    severity=Severity.CRITICAL if {split_a, split_b} == {"train", "test"} else Severity.HIGH,
                    status=AuditStatus.FAIL,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.BLOCKING,
                    affected_count=sum(sum(sp.values()) for sp in entities.values()),
                    affected=[],
                    source_split=split_a,
                    target_split=split_b,
                    description=(
                        f"{len(entities)} distinct value(s) of {column} appear in both {split_a} and "
                        f"{split_b} ({sum(sum(sp.values()) for sp in entities.values())} rows). Entity "
                        f"metadata covers {checked} of {rows_in_scope} rows "
                        f"({coverage['entity_coverage_ratio']:.1%}); the remaining {rows_without_entity} "
                        f"row(s) carry no {column} value and cannot be attributed to any entity."
                    ),
                    why_it_matters=(
                        "The model can meet the same entity at evaluation time that it fitted during "
                        "training. With repeated measures per entity, a per-row split does not test "
                        "generalisation to unseen entities, which is what almost every deployment claims."
                    ),
                    evidence={
                        "group_column": column,
                        "entities": len(entities),
                        "entity_coverage": coverage,
                        **coverage,
                        "examples": [
                            {"entity": entity, "splits": splits}
                            for entity, splits in sorted(entities.items(), key=lambda item: -sum(item[1].values()))[:20]
                        ],
                    },
                    limitations=(
                        [
                            f"{rows_without_entity} row(s) carry no {column} value and were not compared, "
                            "so rows without an entity can still hide a cross-split match."
                        ]
                        if rows_without_entity
                        else []
                    ),
                    recommended_action=(
                        f"Re-split with `dataset-doctor-audit split <file> --group-by {column}` so every "
                        f"{column} lands in exactly one split, then re-audit."
                    ),
                    metadata={
                        "scope": "cross_split",
                        "affected_sample_ids": affected[:200],
                        "affected_sample_ids_truncated": len(affected) > 200,
                    },
                )
            )
            sequence += 1
    return findings


def _entity_coverage(rows_in_scope: int, rows_without_entity: int) -> dict[str, Any]:
    checked = rows_in_scope - rows_without_entity
    ratio = checked / rows_in_scope if rows_in_scope else 0.0
    return {
        "group_column_rows": rows_in_scope,
        "rows_checked": checked,
        "rows_without_entity": rows_without_entity,
        "entity_coverage_ratio": round(ratio, 4),
    }


def _unmeasurable_group_column(ctx: AuditContext, column: str, coverage: dict[str, Any], sequence: int) -> Any:
    """Declared entity column with no usable value anywhere: not a PASS, not a FAIL."""
    return build_finding(
        ctx,
        rule_id="DD005",
        sequence=sequence,
        title=f"Group column '{column}' has no usable entity values",
        category=Category.LEAKAGE,
        severity=Severity.HIGH,
        status=AuditStatus.INCONCLUSIVE,
        evidence_type=EvidenceType.DETERMINISTIC,
        confidence=Confidence.HIGH,
        formal_impact=FormalImpact.BLOCKING,
        affected=[],
        description=(
            f"None of the {coverage['group_column_rows']} row(s) carries a usable {column} value, so no "
            "entity comparison was possible."
        ),
        why_it_matters=(
            "A group column that is empty, all-blank or all-sentinel answers nothing: reporting it as "
            "clean would certify entity disjointness on zero evidence, which is the one claim an "
            "entity-disjoint evaluation must never take from this rule."
        ),
        evidence={"group_column": column, **coverage},
        recommended_action=(
            f"Populate {column} (or point groups.columns at the real entity column), then re-audit. "
            "Until then the entity-leakage question is unanswered."
        ),
        metadata={"scope": "cross_split", "coverage_only": True},
    )


def _partial_entity_coverage(ctx: AuditContext, column: str, coverage: dict[str, Any], sequence: int) -> Any:
    """No overlap among the rows that carry an entity id, and how much of the data that is."""
    ratio = float(coverage["entity_coverage_ratio"])
    return build_finding(
        ctx,
        rule_id="DD005",
        sequence=sequence,
        title=f"Entity check on '{column}' covers {ratio:.1%} of rows",
        category=Category.LEAKAGE,
        severity=Severity.LOW,
        status=AuditStatus.WARNING,
        evidence_type=EvidenceType.DETERMINISTIC,
        confidence=Confidence.HIGH,
        formal_impact=FormalImpact.NONE,
        affected=[],
        description=(
            f"{coverage['rows_without_entity']} of {coverage['group_column_rows']} row(s) carry no {column} "
            f"value, so entity leakage was ruled out on {coverage['rows_checked']} rows ({ratio:.1%}) only."
        ),
        why_it_matters=(
            "Rows without an entity id are invisible to a group split: a missing customer can be the same "
            "customer as a row on the other side. 'No shared entity observed' is therefore weaker than "
            "'proven disjoint' by exactly this many rows."
        ),
        evidence={"group_column": column, **coverage},
        recommended_action=(
            f"Backfill {column} (or drop the rows that cannot be attributed) if the evaluation claims "
            "generalisation to unseen entities."
        ),
        metadata={"scope": "cross_split", "coverage_only": True},
    )


def _degenerate_group_column(
    ctx: AuditContext, column: str, presence: dict[str, dict[str, int]], unique_ratio: float, sequence: int
) -> Any:
    if unique_ratio > 0.98:
        # An entity column where every value is unique cannot leak across splits, so the
        # leakage answer here is 'nothing found'. The advisory stays LOW/NON-BLOCKING on
        # purpose: a *declared* group column that is row-unique usually means the user
        # named a row id where they meant a patient id, which is worth one line - but it
        # must not turn a clean dataset into a RISKY verdict (spec TEST 6).
        return build_finding(
            ctx,
            rule_id="DD005",
            sequence=sequence,
            title=f"Group column '{column}' has no repeated entities",
            category=Category.LEAKAGE,
            severity=Severity.LOW,
            status=AuditStatus.WARNING,
            evidence_type=EvidenceType.HEURISTIC,
            confidence=Confidence.MEDIUM,
            formal_impact=FormalImpact.NONE,
            description=(
                f"{len(presence)} unique values over {sum(sum(sp.values()) for sp in presence.values())} "
                f"rows: every entity appears once."
            ),
            why_it_matters=(
                "Entity leakage is undetectable through a per-row key. If this column is really a row id "
                "rather than a patient/session/device id, the split is still ungrouped."
            ),
            evidence={"group_column": column, "unique_ratio": round(unique_ratio, 4)},
        )
    return None


def _entity_pairs(
    ctx: AuditContext, cross: dict[str, dict[str, int]]
) -> list[tuple[str, str, dict[str, dict[str, int]]]]:
    grouped: dict[tuple[str, str], dict[str, dict[str, int]]] = defaultdict(dict)
    for entity, splits in cross.items():
        names = sorted(splits)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                pair = (names[i], names[j])
                grouped[pair][entity] = {names[i]: splits[names[i]], names[j]: splits[names[j]]}
    ordered = sorted(
        grouped.items(),
        key=lambda item: (
            0 if {item[0][0], item[0][1]} == {"train", "test"} else 1,
            -len(item[1]),
        ),
    )
    return [(pair[0], pair[1], entities) for pair, entities in ordered]


def _entity_key(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    text = str(value).strip()
    return text or None


# --------------------------------------------------------------- DD006 temporal
def detect_temporal_leakage(ctx: AuditContext) -> list[Any]:
    if not ctx.spec.temporal_column:
        raise NotApplicable("temporal.column is not configured", "NOT_RUN")
    ctx.needs_splits()
    policy = ctx.config.policies.item("temporal_leakage")
    if not policy.enabled:
        raise NotApplicable("policy temporal_leakage.enabled = false", "NOT_RUN")
    require_order = bool(policy.extra_settings().get("train_before_test", ctx.config.temporal.train_before_test))
    if not require_order:
        raise NotApplicable(
            "policy does not require train to precede test, so time overlap is not an error here",
            "NOT_RUN",
        )
    column = ctx.spec.temporal_column
    parsed: dict[str, pd.Series] = {}
    for split, frame in ctx.tables.items():
        if column not in frame.columns:
            continue
        parsed[split] = pd.to_datetime(frame[column], errors="coerce", utc=False)
    parseable = int(sum(int(series.notna().sum()) for series in parsed.values()))
    unparseable = int(sum(len(series) for series in parsed.values())) - parseable
    if len(parsed) < 2:
        return [
            _unmeasurable_temporal_boundary(
                ctx,
                column,
                f"'{column}' is missing from most splits or could not be parsed as datetime",
                parseable,
            )
        ]
    train_splits = [s for s in parsed if ctx.role_of(s) is SplitRole.TRAIN] or ["train"]
    test_splits = [s for s in parsed if ctx.role_of(s) is SplitRole.TEST]
    if not test_splits:
        return [
            _unmeasurable_temporal_boundary(
                ctx,
                column,
                "no test split has a parseable time column, so ordering cannot be checked",
                parseable,
            )
        ]
    if parseable == 0:
        # spec 28: a column that never parses is a config error, not a PASS. Checking zero
        # timestamps cannot establish anything about the temporal boundary.
        return [
            _unmeasurable_temporal_boundary(
                ctx,
                column,
                f"'{column}' produced no parseable timestamp in any split ({unparseable} row value(s) "
                "excluded), so the temporal boundary cannot be checked",
                parseable,
            )
        ]
    findings: list[Any] = []
    sequence = 1
    compared = 0
    for train_split in train_splits:
        for test_split in test_splits:
            train_times = parsed[train_split].dropna()
            test_times = parsed[test_split].dropna()
            if train_times.empty or test_times.empty:
                continue
            compared += 1
            overlap_start = test_times.min()
            violating = int((train_times >= overlap_start).sum())
            if violating == 0:
                continue
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD006",
                    sequence=sequence,
                    title=f"Temporal leakage: {train_split} rows dated at or after {test_split}",
                    category=Category.LEAKAGE,
                    severity=Severity.HIGH,
                    status=AuditStatus.FAIL,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.BLOCKING,
                    affected_count=violating,
                    source_split=train_split,
                    target_split=test_split,
                    description=(
                        f"max({train_split}.{column}) = {train_times.max()} is at or after "
                        f"min({test_split}.{column}) = {overlap_start}; {violating} training row(s) are "
                        "not strictly earlier than the evaluation window."
                    ),
                    why_it_matters=(
                        "If the task is to forecast the future, training on records from inside the "
                        "evaluation window lets the model see outcomes before they were supposed to be "
                        "unknown."
                    ),
                    evidence={
                        "column": column,
                        "train_max": str(train_times.max()),
                        "test_min": str(overlap_start),
                        "violating_rows": violating,
                        "unparseable_timestamps": unparseable,
                    },
                    limitations=(
                        [
                            f"{unparseable} value(s) in '{column}' did not parse as datetime and were "
                            "excluded from the comparison."
                        ]
                        if unparseable
                        else []
                    )
                    + [
                        "Time overlap is only an error for forecasting tasks. This rule fires because "
                        "temporal.train_before_test is set in the policy."
                    ],
                    metadata={"scope": "cross_split"},
                )
            )
            sequence += 1
    if not compared:
        return [
            _unmeasurable_temporal_boundary(
                ctx,
                column,
                "no train/test pair had parseable timestamps on both sides, so the temporal boundary "
                f"cannot be checked ({unparseable} unparseable value(s) excluded)",
                parseable,
            )
        ]
    return findings


def _unmeasurable_temporal_boundary(ctx: AuditContext, column: str, detail: str, parseable: int) -> Any:
    """temporal.column is declared but the ordering question cannot be answered: not a PASS."""
    return build_finding(
        ctx,
        rule_id="DD006",
        sequence=1,
        title=f"Temporal boundary on '{column}' could not be measured",
        category=Category.LEAKAGE,
        severity=Severity.HIGH,
        status=AuditStatus.INCONCLUSIVE,
        evidence_type=EvidenceType.DETERMINISTIC,
        confidence=Confidence.HIGH,
        formal_impact=FormalImpact.BLOCKING,
        affected=[],
        description=(
            f"{detail}. This is not a PASS: a temporal split was declared and no timestamp pair was "
            "compared, so the tool has no evidence about the boundary either way."
        ),
        why_it_matters=(
            "Reported ordering is the only defence against training on the evaluation window. Reading "
            "a clean verdict here would take that assurance from a check that never happened."
        ),
        evidence={"column": column, "parseable_timestamps": parseable},
        recommended_action=(
            f"Fix {column} (parseable ISO timestamps in every split the policy orders), then re-audit. "
            "Until then the temporal-leakage question is unanswered."
        ),
        metadata={"scope": "cross_split", "coverage_only": True},
    )


# --------------------------------------------------------------- DD007 target
def detect_target_leakage(ctx: AuditContext) -> list[Any]:
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("target leakage is defined for tabular datasets", "UNSUPPORTED")
    label = ctx.label_column()
    if not label:
        raise InsufficientEvidence(
            "no label column declared, so leakage into features cannot be measured. Set labels.column."
        )
    ctx.needs_splits()
    settings = ctx.config.policies.item("target_leakage").extra_settings()
    level2_enabled = bool(settings.get("heuristic", True))
    candidate_auc = float(settings.get("min_single_feature_auc", 0.95))
    candidate_mi = float(settings.get("min_normalized_mutual_info", 0.6))
    combined = _concat_features(
        ctx,
        exclude={ctx.spec.split_column, *ctx.spec.group_columns, *ctx.spec.id_columns},
    )
    if combined is None:
        raise InsufficientEvidence("no readable table data for target leakage analysis")
    y = combined[label]
    mask = y.notna()
    y = y[mask]
    if y.nunique() < 2:
        raise InsufficientEvidence(
            f"label column '{label}' has {y.nunique()} distinct value(s); leakage against a constant "
            "target cannot be assessed"
        )
    findings: list[Any] = []
    sequence = 1
    for column in [c for c in combined.columns if str(c) != label]:
        feature = combined[column][mask]
        if feature.notna().sum() < 2:
            continue
        verdict = _deterministic_check(y, feature)
        if verdict is not None:
            kind, detail = verdict
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD007",
                    sequence=sequence,
                    title=f"Target leakage: '{column}' is {kind}",
                    category=Category.LEAKAGE,
                    severity=Severity.CRITICAL,
                    status=AuditStatus.FAIL,
                    evidence_type=EvidenceType.DETERMINISTIC,
                    confidence=Confidence.HIGH,
                    formal_impact=FormalImpact.BLOCKING,
                    affected_count=int(feature.shape[0]),
                    columns=[str(column), str(label)],
                    description=(
                        f"Column '{column}' reproduces the label '{label}' ({detail}). Any model that "
                        "sees this column is being handed the answer."
                    ),
                    why_it_matters=(
                        "Deterministic feature-to-label dependence means evaluation measures copying, not "
                        "prediction. This is exact arithmetic, not a threshold."
                    ),
                    evidence={"feature": str(column), "label": str(label), "relation": kind, "detail": detail},
                    metadata={"scope": "column"},
                )
            )
            sequence += 1
            continue
        if not level2_enabled:
            continue
        score = _predictive_signal(y, feature)
        if score is None:
            continue
        auc, normalized_mi = score
        if (auc is not None and auc >= candidate_auc) or normalized_mi >= candidate_mi:
            auc_text = f"AUC={auc:.3f}" if auc is not None else "AUC=not defined for a non-numeric column"
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD007",
                    sequence=sequence,
                    title=f"TARGET_LEAKAGE_CANDIDATE: '{column}' predicts the label unusually well",
                    category=Category.LEAKAGE,
                    severity=Severity.MEDIUM,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.HEURISTIC,
                    confidence=Confidence.LOW,
                    formal_impact=FormalImpact.POTENTIAL,
                    affected_count=int(feature.shape[0]),
                    columns=[str(column), str(label)],
                    description=(
                        f"Single-feature separation of '{column}' against '{label}': {auc_text}, "
                        f"normalised mutual information={normalized_mi:.3f}."
                    ),
                    why_it_matters=(
                        "Suspiciously clean single-feature separation is where post-outcome columns tend to "
                        "show up - but a genuinely predictive biomarker looks identical in data. Only a "
                        "domain check can tell them apart, which is why this is a candidate and not a verdict."
                    ),
                    evidence={
                        "feature": str(column),
                        "label": str(label),
                        "single_feature_auc": round(auc, 4) if auc is not None else None,
                        "normalized_mutual_info": round(normalized_mi, 4),
                        "thresholds": {
                            "min_single_feature_auc": candidate_auc,
                            "min_normalized_mutual_info": candidate_mi,
                        },
                    },
                    limitations=[
                        "High predictive power is not leakage. This finding needs a human answer to "
                        "'was this value known before the outcome?'"
                    ],
                    metadata={"scope": "column", "candidate": True},
                )
            )
            sequence += 1
    return findings


def _deterministic_check(y: pd.Series, feature: pd.Series) -> tuple[str, str] | None:
    left = y.astype(str)
    right = feature.astype(str)
    if left.equals(right):
        return ("identical to the label", "values match row for row")
    pairs = pd.DataFrame({"f": right, "y": left}).drop_duplicates()
    f_to_y = pairs.groupby("f")["y"].nunique()
    y_to_f = pairs.groupby("y")["f"].nunique()
    if int(f_to_y.max()) == 1 and int(y_to_f.max()) == 1:
        return (
            "a deterministic relabeling of the label",
            f"one-to-one mapping over {len(pairs)} value pairs",
        )
    if int(f_to_y.max()) == 1 and pairs["f"].nunique() <= 20 and y.nunique() >= 2:
        # Every feature value pins one label, and the feature is coarse enough that this is
        # structure rather than a row identifier trivially determining its own label.
        return (
            "a deterministic function of the label",
            f"{pairs['f'].nunique()} distinct feature values each map to exactly one label",
        )
    numeric = pd.to_numeric(feature, errors="coerce").dropna()
    if numeric.size >= 3 and y.nunique() == 2:
        codes = pd.to_numeric(y, errors="coerce").dropna()
        spread = float(np.std(numeric.to_numpy(dtype=float)))
        if codes.size == numeric.size and codes.nunique() == 2 and spread > 0:
            correlation = float(np.corrcoef(numeric.to_numpy(dtype=float), codes.to_numpy(dtype=float))[0, 1])
            if abs(correlation) >= 0.999999:
                return (
                    "perfectly linearly correlated with the label",
                    f"pearson r={correlation:+.6f}",
                )
    return None


def _predictive_signal(y: pd.Series, feature: pd.Series) -> tuple[float | None, float] | None:
    """(single-feature AUC via ranks, normalised mutual information). Both bounded.

    The AUC is ``None`` for a non-numeric feature: a category cannot be ranked, but its
    mutual information is still comparable.
    """
    classes = sorted(y.astype(str).unique())
    if len(classes) > 50:
        return None
    y_str = y.astype(str)
    numeric = pd.to_numeric(feature, errors="coerce")
    if numeric.notna().sum() >= 0.8 * len(feature) and numeric.dropna().nunique() > 2:
        values = numeric.to_numpy(dtype=float)
        labels = y_str.to_numpy()
        mask = ~np.isnan(values)
        values, labels = values[mask], labels[mask]
        if len(set(labels.tolist())) < 2 or values.size < 4:
            return None
        auc = _rank_auc(values, labels, classes)
        binned = _qbin(values, min(10, max(2, int(math.sqrt(values.size)))))
        mi = _normalized_mi(binned.astype(str), pd.Series(labels))
        return auc, mi
    return None, _normalized_mi(feature.astype(str), y_str)


def _rank_auc(values: np.ndarray, labels: np.ndarray, classes: list[str]) -> float:
    positive = labels == classes[-1]
    negative = ~positive
    if positive.sum() == 0 or negative.sum() == 0:
        return 0.5
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(values.size, dtype=float)
    ranks[order] = np.arange(1, values.size + 1, dtype=float)
    # ties: average ranks
    sorted_values = values[order]
    i = 0
    while i < sorted_values.size:
        j = i
        while j + 1 < sorted_values.size and sorted_values[j + 1] == sorted_values[i]:
            j += 1
        if j > i:
            ranks[order[i : j + 1]] = ranks[order[i : j + 1]].mean()
        i = j + 1
    sum_positive = ranks[positive].sum()
    n_pos, n_neg = int(positive.sum()), int(negative.sum())
    return float((sum_positive - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg))


def _qbin(values: np.ndarray, bins: int) -> np.ndarray:
    edges = np.unique(np.quantile(values, np.linspace(0, 1, bins + 1)))
    if edges.size < 2:
        return np.zeros(values.size, dtype=int)
    return np.clip(np.searchsorted(edges, values, side="right") - 1, 0, edges.size - 2)


def _normalized_mi(left: pd.Series, right: pd.Series) -> float:
    frame = pd.DataFrame({"x": left, "y": right}).dropna()
    if frame.empty:
        return 0.0
    counts = frame.groupby(["x", "y"], observed=True).size()
    total = float(counts.sum())
    px = counts.groupby(level=0).sum() / total
    py = counts.groupby(level=1).sum() / total
    mi = 0.0
    for (x, y), value in counts.items():
        pxy = float(value) / total
        mi += pxy * math.log(pxy / (float(px[x]) * float(py[y])))
    hy = -float(sum(p * math.log(p) for p in py if p > 0))
    if hy <= 1e-12:
        return 0.0
    return float(max(mi, 0.0) / hy)


def _concat_features(ctx: AuditContext, exclude: Iterable[str | None]) -> pd.DataFrame | None:
    """Every split stacked with a `__split__` marker, minus the columns that are not features.

    `exclude` may contain ``None``: an undeclared split column is a legitimate state.
    """
    frames = []
    for split, frame in ctx.tables.items():
        if frame.empty:
            continue
        copy = frame.copy()
        copy["__split__"] = split
        frames.append(copy)
    if not frames:
        return None
    named = {item for item in exclude if item}
    combined = pd.concat(frames, ignore_index=True)
    return combined.drop(columns=[c for c in named if c in combined.columns] + ["__split__"])


# ------------------------------------------------------------ DD008 identifier
def detect_identifier_leakage(ctx: AuditContext) -> list[Any]:
    if not ctx.adapter.supports("tabular"):
        raise NotApplicable("identifier leakage is defined for tabular datasets", "UNSUPPORTED")
    settings = ctx.config.policies.item("identifier_leakage").extra_settings()
    threshold = float(settings.get("unique_ratio", 0.98))
    label = ctx.label_column()
    declared = set(ctx.spec.id_columns) | set(ctx.spec.group_columns)
    findings: list[Any] = []
    sequence = 1
    for split, frame in sorted(ctx.tables.items()):
        if frame.empty:
            continue
        rows = len(frame)
        for column in frame.columns:
            name = str(column)
            if name == label or name in declared or name == ctx.spec.split_column:
                continue
            series = frame[column]
            unique_ratio = float(series.nunique(dropna=True)) / max(rows, 1)
            looks_like_id = _name_suggests_id(name)
            if unique_ratio < threshold and not looks_like_id:
                continue
            if unique_ratio < threshold:
                continue
            findings.append(
                build_finding(
                    ctx,
                    rule_id="DD008",
                    sequence=sequence,
                    title=f"IDENTIFIER_FEATURE_CANDIDATE: '{name}' is near-unique in '{split}'",
                    category=Category.LEAKAGE,
                    severity=Severity.MEDIUM if looks_like_id else Severity.LOW,
                    status=AuditStatus.WARNING,
                    evidence_type=EvidenceType.HEURISTIC,
                    confidence=Confidence.MEDIUM,
                    formal_impact=FormalImpact.POTENTIAL,
                    affected_count=rows,
                    source_split=split,
                    columns=[name],
                    description=(
                        f"'{name}' takes {series.nunique(dropna=True)} distinct values across {rows} rows "
                        f"(unique ratio {unique_ratio:.3f})."
                    ),
                    why_it_matters=(
                        "A per-row identifier in the feature matrix lets a high-capacity model memorise "
                        "row-level associations instead of learning transferable structure, and it is the "
                        "usual home of path or id leakage."
                    ),
                    evidence={
                        "column": name,
                        "unique_ratio": round(unique_ratio, 4),
                        "threshold": threshold,
                        "name_suggests_identifier": looks_like_id,
                        "dtype": str(series.dtype),
                        "example_shape": _value_shape(series),
                    },
                    limitations=[
                        "High cardinality alone is not leakage: free text, timestamps and measurements "
                        "are near-unique and legitimate. Only copy this column out after checking it "
                        "carries no information about the outcome."
                    ],
                    recommended_action=(
                        f"Drop '{name}' from the feature matrix, or declare it under id_columns so it is "
                        "treated as identity rather than signal."
                    ),
                    metadata={"scope": "column", "candidate": True},
                )
            )
            sequence += 1
    return _dedupe_by_column(findings)


def _name_suggests_id(name: str) -> bool:
    lowered = name.lower()
    markers = ("id", "uuid", "guid", "filename", "file_name", "path", "row_no", "rownum", "index")
    return any(marker in lowered for marker in markers)


def _value_shape(series: pd.Series) -> dict[str, Any]:
    """Shape statistics only: never copy raw values into a report (spec section 95)."""
    values = series.dropna().astype(str)
    if values.empty:
        return {"non_null": 0}
    lengths = values.str.len()
    return {
        "non_null": int(values.size),
        "min_length": int(lengths.min()),
        "max_length": int(lengths.max()),
        "all_digits": bool((values.str.isdigit()).mean() > 0.95),
    }


def _dedupe_by_column(findings: list[Any]) -> list[Any]:
    seen: set[str] = set()
    out: list[Any] = []
    for finding in findings:
        column = finding.location.columns[0] if finding.location.columns else finding.title
        if column in seen:
            continue
        seen.add(column)
        out.append(finding)
    return out
