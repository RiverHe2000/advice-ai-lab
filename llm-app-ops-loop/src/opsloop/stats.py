"""The statistics every decision in this project rests on: seeded bootstrap intervals, paired
bootstrap on per-case deltas, exact McNemar, a two-proportion test, a two-sample chi-square,
Jensen-Shannon distance, and expected calibration error with a reliability table."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike
from scipy import stats as sps


@dataclass(frozen=True, slots=True)
class Interval:
    mean: float
    low: float
    high: float
    n: int

    def as_dict(self) -> dict[str, float | int]:
        return {"mean": self.mean, "low": self.low, "high": self.high, "n": self.n}


def bootstrap_mean_ci(
    values: ArrayLike, *, n_boot: int = 1000, seed: int = 0, level: float = 0.95
) -> Interval:
    """Percentile bootstrap of the mean (seeded). Empty input → NaN interval, n = 0."""
    arr = np.asarray(values, dtype=np.float64).ravel()
    if arr.size == 0:
        return Interval(math.nan, math.nan, math.nan, 0)
    mean = float(arr.mean())
    if arr.size == 1 or n_boot <= 0:
        return Interval(mean, mean, mean, int(arr.size))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, arr.size, size=(n_boot, arr.size))
    means = arr[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = (float(x) for x in np.quantile(means, [alpha, 1.0 - alpha]))
    return Interval(mean, lo, hi, int(arr.size))


@dataclass(frozen=True, slots=True)
class PairedResult:
    n: int
    delta: float
    low: float
    high: float
    p_improve: float
    wins: int
    losses: int
    ties: int


def paired_bootstrap(
    candidate: Sequence[float],
    baseline: Sequence[float],
    *,
    n_boot: int = 2000,
    seed: int = 0,
    level: float = 0.95,
) -> PairedResult:
    """Bootstrap the mean of per-case differences (candidate - baseline) on the *same* cases."""
    c = np.asarray(list(candidate), dtype=np.float64)
    b = np.asarray(list(baseline), dtype=np.float64)
    if c.shape != b.shape:
        msg = f"paired inputs differ in length: {c.size} vs {b.size}"
        raise ValueError(msg)
    if c.size == 0:
        return PairedResult(0, math.nan, math.nan, math.nan, math.nan, 0, 0, 0)
    deltas = c - b
    wins = int((deltas > 0).sum())
    losses = int((deltas < 0).sum())
    ties = int(deltas.size - wins - losses)
    if deltas.size == 1 or n_boot <= 0:
        d = float(deltas.mean())
        return PairedResult(int(deltas.size), d, d, d, float(d > 0), wins, losses, ties)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, deltas.size, size=(n_boot, deltas.size))
    means = deltas[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = (float(x) for x in np.quantile(means, [alpha, 1.0 - alpha]))
    return PairedResult(
        int(deltas.size),
        float(deltas.mean()),
        lo,
        hi,
        float((means > 0).mean()),
        wins,
        losses,
        ties,
    )


def mcnemar_exact(wins: int, losses: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs (binomial with p = 0.5)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2.0 * tail))


@dataclass(frozen=True, slots=True)
class ProportionTest:
    rate_a: float
    rate_b: float
    diff: float
    z: float
    p_value: float


def two_proportion_test(
    k_a: int, n_a: int, k_b: int, n_b: int, *, alternative: str = "greater"
) -> ProportionTest:
    """Pooled two-proportion z-test of rate_a vs rate_b.

    ``alternative="greater"`` tests H1: rate_a > rate_b (the canary is *worse* than control on
    an error-type rate); ``"two-sided"`` for a plain difference.
    """
    if n_a <= 0 or n_b <= 0:
        return ProportionTest(math.nan, math.nan, math.nan, math.nan, 1.0)
    pa, pb = k_a / n_a, k_b / n_b
    pooled = (k_a + k_b) / (n_a + n_b)
    se = math.sqrt(pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b))
    if se == 0.0:
        return ProportionTest(pa, pb, pa - pb, 0.0, 1.0)
    z = (pa - pb) / se
    if alternative == "greater":
        p = float(sps.norm.sf(z))
    elif alternative == "less":
        p = float(sps.norm.cdf(z))
    else:
        p = float(2.0 * sps.norm.sf(abs(z)))
    return ProportionTest(pa, pb, pa - pb, float(z), p)


def js_distance(p: ArrayLike, q: ArrayLike) -> float:
    """Jensen-Shannon *distance* (sqrt of the divergence, base 2, bounded in [0, 1])."""
    a = np.asarray(p, dtype=np.float64).ravel()
    b = np.asarray(q, dtype=np.float64).ravel()
    if a.sum() <= 0 or b.sum() <= 0:
        return 0.0
    a = a / a.sum()
    b = b / b.sum()
    m = 0.5 * (a + b)

    def _kl(x: Any, y: Any) -> float:
        mask = x > 0
        return float(np.sum(x[mask] * np.log2(x[mask] / y[mask])))

    div = 0.5 * _kl(a, m) + 0.5 * _kl(b, m)
    return float(math.sqrt(max(div, 0.0)))


def chi_square_two_sample(counts_a: ArrayLike, counts_b: ArrayLike) -> tuple[float, float]:
    """Two-sample chi-square on a 2 x k table (both rows are samples). Categories that are empty
    in both samples are dropped; fewer than two remaining categories → (0, 1)."""
    a = np.asarray(counts_a, dtype=np.float64).ravel()
    b = np.asarray(counts_b, dtype=np.float64).ravel()
    keep = (a + b) > 0
    a, b = a[keep], b[keep]
    if a.size < 2 or a.sum() == 0 or b.sum() == 0:
        return 0.0, 1.0
    stat, p, _, _ = sps.chi2_contingency(np.vstack([a, b]), correction=False)
    return float(stat), float(p)


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    low: float
    high: float
    n: int
    mean_prob: float
    mean_outcome: float


@dataclass(frozen=True, slots=True)
class Calibration:
    ece: float
    bins: tuple[ReliabilityBin, ...]
    n: int


def expected_calibration_error(
    probs: Sequence[float], outcomes: Sequence[int | bool], *, n_bins: int = 10
) -> Calibration:
    """ECE with equal-width bins and the reliability table behind it."""
    p = np.asarray(list(probs), dtype=np.float64)
    y = np.asarray([1.0 if o else 0.0 for o in outcomes], dtype=np.float64)
    if p.size == 0:
        return Calibration(math.nan, (), 0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    rows: list[ReliabilityBin] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        mask = (p >= lo) & ((p < hi) if i < n_bins - 1 else (p <= hi))
        n = int(mask.sum())
        if n == 0:
            continue
        mp, my = float(p[mask].mean()), float(y[mask].mean())
        ece += (n / p.size) * abs(mp - my)
        rows.append(ReliabilityBin(lo, hi, n, mp, my))
    return Calibration(float(ece), tuple(rows), int(p.size))


def percentile(values: ArrayLike, q: float) -> float:
    arr = np.asarray(values, dtype=np.float64).ravel()
    if arr.size == 0:
        return math.nan
    return float(np.percentile(arr, q))
