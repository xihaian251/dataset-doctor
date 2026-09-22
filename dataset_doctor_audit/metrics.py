"""Statistical primitives. Every function here is unit-tested against hand-computed
edge cases (spec section 109) because a wrong metric silently produces a wrong verdict.

Conventions:
* distances are in [0, 1] where a bounded version exists, so thresholds are comparable
  across features; ``psi`` and ``wasserstein`` are unbounded and carry their own scale
* p-values are never sufficient on their own: effect size travels with them
  (spec section 44)
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

EPS = 1e-12

#: These helpers are array-native: they immediately call ``np.asarray``, so refusing an
#: ndarray at the type level would only force ``.tolist()`` copies on large columns.
Numbers = Sequence[float] | npt.NDArray[np.floating] | npt.NDArray[np.integer]


def as_probs(counts: Numbers) -> npt.NDArray[np.float64]:
    array = np.asarray(counts, dtype=np.float64)
    total = array.sum()
    if total <= 0:
        return np.zeros_like(array)
    return array / total


def _log(values: npt.NDArray[np.float64], base: float) -> npt.NDArray[np.float64]:
    """numpy's log has no `base` argument; a second positional arg is silently misread."""
    natural = np.log(values)
    return natural if base == np.e else natural / math.log(base)


def support_union(keys_a: Sequence[str], keys_b: Sequence[str]) -> list[str]:
    return sorted(set(keys_a) | set(keys_b))


def tv_distance(p: Sequence[float], q: Sequence[float]) -> float:
    """Total variation distance: 0 identical, 1 disjoint supports."""
    pa, qa = as_probs(p), as_probs(q)
    if pa.size != qa.size:
        raise ValueError("probability vectors must share the same support order")
    return float(0.5 * np.abs(pa - qa).sum())


def jensen_shannon(p: Sequence[float], q: Sequence[float], log: str = "e") -> float:
    """Jensen-Shannon *distance* (sqrt of divergence): bounded in [0, 1].

    Reported as a distance rather than a divergence on purpose - it is comparable
    across feature types and does not blow up on disjoint supports.
    """
    pa, qa = as_probs(p), as_probs(q)
    if pa.size != qa.size:
        raise ValueError("probability vectors must share the same support order")
    m = 0.5 * (pa + qa)
    base = {"e": np.e, "2": 2.0}[log]

    def kl(a: npt.NDArray[np.float64]) -> float:
        mask = a > 0
        return float(np.sum(a[mask] * _log(a[mask] / np.clip(m[mask], EPS, None), base)))

    divergence = 0.5 * kl(pa) + 0.5 * kl(qa)
    return float(math.sqrt(max(divergence, 0.0)))


def entropy(counts: Sequence[float], log: str = "2") -> float:
    probs = as_probs(counts)
    mask = probs > 0
    if not mask.any():
        return 0.0
    base = {"e": np.e, "2": 2.0}[log]
    return float(-np.sum(probs[mask] * _log(probs[mask], base)))


def effective_class_count(counts: Sequence[float]) -> float:
    """exp(H) for base-2 entropy: how many equally-sized classes the dataset behaves like."""
    return float(2.0 ** entropy(counts))


def imbalance_ratio(counts: Sequence[float]) -> float:
    positive = [c for c in counts if c > 0]
    if len(positive) < 2:
        return 1.0
    return float(max(positive) / min(positive))


def minority_share(counts: Sequence[float]) -> float:
    positive = [c for c in counts if c > 0]
    total = sum(counts)
    if not positive or total <= 0:
        return 0.0
    return float(min(positive) / total)


def wasserstein_1d(a: Numbers, b: Numbers) -> float:
    from scipy.stats import wasserstein_distance

    arr_a, arr_b = _numeric_pair(a, b)
    if arr_a.size == 0 or arr_b.size == 0:
        return float("nan")
    return float(wasserstein_distance(arr_a, arr_b))


def normalized_wasserstein(a: Sequence[float], b: Sequence[float]) -> float:
    """EMD divided by the pooled scale, so one threshold works across features."""
    arr_a, arr_b = _numeric_pair(a, b)
    if arr_a.size == 0 or arr_b.size == 0:
        return float("nan")
    pooled = np.concatenate([arr_a, arr_b])
    scale = float(np.quantile(pooled, 0.95) - np.quantile(pooled, 0.05))
    distance = wasserstein_1d(arr_a, arr_b)
    if scale <= EPS:
        return 0.0 if abs(distance) <= EPS else 1.0
    return float(distance / scale)


def ks_statistic(a: Sequence[float], b: Sequence[float]) -> tuple[float, float]:
    """Returns ( statistic, p_value ). The statistic is the effect size; report both."""
    from scipy.stats import ks_2samp

    arr_a, arr_b = _numeric_pair(a, b)
    if arr_a.size < 2 or arr_b.size < 2:
        return float("nan"), float("nan")
    result = ks_2samp(arr_a, arr_b)
    return float(result.statistic), float(result.pvalue)


def population_stability_index(expected: Sequence[float], actual: Sequence[float], bins: int = 10) -> float:
    """PSI on shared quantile bins. Unbounded; >0.25 is conventionally 'major'."""
    e_arr, a_arr = _numeric_pair(expected, actual)
    if e_arr.size == 0 or a_arr.size == 0:
        return float("nan")
    edges = np.unique(np.quantile(e_arr, np.linspace(0, 1, bins + 1)))
    if edges.size < 2:
        return 0.0
    e_counts, _ = np.histogram(e_arr, bins=edges)
    a_counts, _ = np.histogram(a_arr, bins=edges)
    e_probs = np.clip(as_probs(e_counts), EPS, None)
    a_probs = np.clip(as_probs(a_counts), EPS, None)
    return float(np.sum((a_probs - e_probs) * np.log(a_probs / e_probs)))


def std_mean_diff(a: Sequence[float], b: Sequence[float]) -> float:
    arr_a, arr_b = _numeric_pair(a, b)
    if arr_a.size < 2 or arr_b.size < 2:
        return float("nan")
    pooled_sd = math.sqrt(
        ((arr_a.size - 1) * float(np.var(arr_a, ddof=1)) + (arr_b.size - 1) * float(np.var(arr_b, ddof=1)))
        / max(arr_a.size + arr_b.size - 2, 1)
    )
    if pooled_sd <= EPS:
        return 0.0 if abs(float(np.mean(arr_a) - np.mean(arr_b))) <= EPS else math.inf
    return float((np.mean(arr_b) - np.mean(arr_a)) / pooled_sd)


def cramers_v(a: Sequence[str], b: Sequence[str]) -> float:
    """Effect size for categorical association between split and category."""
    labels = support_union(a, b)
    counts_a = np.array([a.count(label) for label in labels], dtype=float)
    counts_b = np.array([b.count(label) for label in labels], dtype=float)
    table = np.vstack([counts_a, counts_b])
    total = table.sum()
    if total <= 0:
        return 0.0
    row = table.sum(axis=1, keepdims=True)
    col = table.sum(axis=0, keepdims=True)
    expected = row @ col / total
    with np.errstate(divide="ignore", invalid="ignore"):
        chi2 = float(np.nansum(np.where(expected > 0, (table - expected) ** 2 / expected, 0.0)))
    denominator = min(row[0, 0], row[1, 0]) if table.shape[1] > 1 else total
    if denominator <= 0:
        return 0.0
    return float(math.sqrt((chi2 / denominator) / (min(table.shape) - 1)))


def benjamini_hochberg(p_values: Sequence[float], alpha: float = 0.05) -> tuple[list[int], list[float]]:
    """Returns (rejected indices, adjusted p-values). NaN p-values stay NaN."""
    values = np.asarray(p_values, dtype=float)
    adjusted = np.full(values.shape, np.nan)
    present = np.where(~np.isnan(values))[0]
    if present.size == 0:
        return [], [float(value) for value in adjusted]
    order = present[np.argsort(values[present])]
    ranked = values[order]
    total = order.size
    stepped = np.minimum.accumulate((ranked * total / np.arange(1, total + 1))[::-1])[::-1]
    stepped = np.clip(stepped, 0.0, 1.0)
    adjusted[order] = stepped
    rejected = sorted(int(index) for index in order[stepped <= alpha])
    return rejected, [float(value) for value in adjusted]


def hamming(left: str, right: str) -> int:
    if len(left) != len(right):
        raise ValueError("hex hashes must have equal length")
    return bin(int(left, 16) ^ int(right, 16)).count("1")


def ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return float(numerator) / float(denominator)


def _numeric_pair(a: Numbers, b: Numbers) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    return _numeric(a), _numeric(b)


def _numeric(values: Numbers) -> npt.NDArray[np.float64]:
    array = np.asarray(list(values), dtype=object)
    if array.size == 0:
        return np.array([], dtype=np.float64)
    coerced = np.array([_to_float(value) for value in array.ravel()], dtype=float)
    return coerced[~np.isnan(coerced)]


def _to_float(value: object) -> float:
    if value is None:
        return float("nan")
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float, np.floating, np.integer)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float("nan")
