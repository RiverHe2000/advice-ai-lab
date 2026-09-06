"""Statistics the reports rely on: seeded percentile bootstrap intervals, a cluster bootstrap
for rates whose units are nested in meetings, a paired bootstrap for two systems on the same
cases, the exact McNemar test on discordant pairs, and expected calibration error."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class Interval:
    mean: float
    low: float
    high: float
    n: int

    def fmt(self, pct: bool = False, digits: int = 3) -> str:
        if math.isnan(self.mean):
            return "n/a"
        if pct:
            return f"{100 * self.mean:.1f}% [{100 * self.low:.1f}, {100 * self.high:.1f}]"
        return f"{self.mean:.{digits}f} [{self.low:.{digits}f}, {self.high:.{digits}f}]"

    def to_dict(self) -> dict[str, float | int]:
        return {"mean": self.mean, "low": self.low, "high": self.high, "n": self.n}


def bootstrap_ci(
    values: Sequence[float], *, n_boot: int = 1000, seed: int = 0, level: float = 0.95
) -> Interval:
    x = np.asarray(list(values), dtype=np.float64)
    if x.size == 0:
        return Interval(math.nan, math.nan, math.nan, 0)
    if x.size == 1 or n_boot == 0:
        return Interval(float(x.mean()), float(x.mean()), float(x.mean()), int(x.size))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, x.size, size=(n_boot, x.size))
    means = x[idx].mean(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = (float(q) for q in np.quantile(means, [alpha, 1.0 - alpha]))
    return Interval(float(x.mean()), lo, hi, int(x.size))


def cluster_bootstrap_rate(
    clusters: Sequence[Sequence[float]], *, n_boot: int = 1000, seed: int = 0, level: float = 0.95
) -> Interval:
    """Rate over all units with meetings (clusters) resampled, so correlated claims from one
    meeting do not make the interval overconfident."""
    groups = [np.asarray(list(c), dtype=np.float64) for c in clusters if len(c)]
    n_units = int(sum(g.size for g in groups))
    if n_units == 0:
        return Interval(math.nan, math.nan, math.nan, 0)
    total = float(sum(g.sum() for g in groups)) / n_units
    if len(groups) == 1 or n_boot == 0:
        return Interval(total, total, total, n_units)
    rng = np.random.default_rng(seed)
    sums = np.asarray([g.sum() for g in groups])
    sizes = np.asarray([g.size for g in groups])
    idx = rng.integers(0, len(groups), size=(n_boot, len(groups)))
    rates = sums[idx].sum(axis=1) / sizes[idx].sum(axis=1)
    alpha = (1.0 - level) / 2.0
    lo, hi = (float(q) for q in np.quantile(rates, [alpha, 1.0 - alpha]))
    return Interval(total, lo, hi, n_units)


@dataclass(frozen=True, slots=True)
class PairedComparison:
    n_pairs: int
    mean_a: float
    mean_b: float
    delta: float
    ci_low: float
    ci_high: float
    p_improve: float
    wins: int
    losses: int
    mcnemar_p: float
    verdict: str

    def to_dict(self) -> dict[str, float | int | str]:
        return {
            "n_pairs": self.n_pairs,
            "mean_a": self.mean_a,
            "mean_b": self.mean_b,
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "p_improve": self.p_improve,
            "wins": self.wins,
            "losses": self.losses,
            "mcnemar_p": self.mcnemar_p,
            "verdict": self.verdict,
        }


def mcnemar_exact(wins: int, losses: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs (binomial, p = 0.5)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2.0 * tail))


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 1000,
    seed: int = 0,
    level: float = 0.95,
    non_inferiority_margin: float = 0.0,
    binary: Sequence[tuple[bool, bool]] | None = None,
) -> PairedComparison:
    """Compare system A with system B on the same cases (A - B). ``binary`` gives per-case
    boolean outcomes for the McNemar test; without it wins/losses come from the sign of the
    per-case difference."""
    x = np.asarray(list(a), dtype=np.float64)
    y = np.asarray(list(b), dtype=np.float64)
    if x.size != y.size:
        msg = "paired comparison needs equal-length sequences"
        raise ValueError(msg)
    if x.size == 0:
        return PairedComparison(
            0, math.nan, math.nan, math.nan, math.nan, math.nan, math.nan, 0, 0, 1.0, "no pairs"
        )
    deltas = x - y
    if binary is not None:
        wins = sum(1 for pa, pb in binary if pa and not pb)
        losses = sum(1 for pa, pb in binary if pb and not pa)
    else:
        wins = int((deltas > 0).sum())
        losses = int((deltas < 0).sum())
    if x.size == 1 or n_boot == 0:
        lo = hi = float(deltas.mean())
        p_improve = float(deltas.mean() > 0)
    else:
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, deltas.size, size=(n_boot, deltas.size))
        means = deltas[idx].mean(axis=1)
        alpha = (1.0 - level) / 2.0
        lo, hi = (float(q) for q in np.quantile(means, [alpha, 1.0 - alpha]))
        p_improve = float((means > 0).mean())
    if lo > 0:
        verdict = "better"
    elif hi < -non_inferiority_margin:
        verdict = "worse"
    elif lo >= -non_inferiority_margin:
        verdict = "non-inferior"
    else:
        verdict = "inconclusive"
    return PairedComparison(
        n_pairs=int(x.size),
        mean_a=float(x.mean()),
        mean_b=float(y.mean()),
        delta=float(deltas.mean()),
        ci_low=lo,
        ci_high=hi,
        p_improve=p_improve,
        wins=wins,
        losses=losses,
        mcnemar_p=mcnemar_exact(wins, losses),
        verdict=verdict,
    )


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    low: float
    high: float
    n: int
    mean_confidence: float
    mean_accuracy: float


@dataclass(frozen=True, slots=True)
class Calibration:
    ece: float
    bins: list[CalibrationBin]
    n: int

    def to_dict(self) -> dict[str, object]:
        return {
            "ece": self.ece,
            "n": self.n,
            "bins": [
                {
                    "low": b.low,
                    "high": b.high,
                    "n": b.n,
                    "mean_confidence": b.mean_confidence,
                    "mean_accuracy": b.mean_accuracy,
                }
                for b in self.bins
            ],
        }

    def table(self) -> str:
        lines = ["| Bin | n | Mean score | Fraction genuine |", "|---|---:|---:|---:|"]
        for b in self.bins:
            if b.n == 0:
                continue
            lines.append(
                f"| {b.low:.1f}-{b.high:.1f} | {b.n} | {b.mean_confidence:.3f} | "
                f"{b.mean_accuracy:.3f} |"
            )
        return "\n".join(lines)


def expected_calibration_error(
    confidences: Sequence[float], outcomes: Sequence[bool], *, n_bins: int = 10
) -> Calibration:
    c = np.asarray(list(confidences), dtype=np.float64)
    o = np.asarray([1.0 if x else 0.0 for x in outcomes], dtype=np.float64)
    if c.size == 0:
        return Calibration(math.nan, [], 0)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[CalibrationBin] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        mask = (c >= lo) & (c < hi) if i < n_bins - 1 else (c >= lo) & (c <= hi)
        n = int(mask.sum())
        if n == 0:
            bins.append(CalibrationBin(lo, hi, 0, math.nan, math.nan))
            continue
        mc = float(c[mask].mean())
        ma = float(o[mask].mean())
        ece += n / c.size * abs(mc - ma)
        bins.append(CalibrationBin(lo, hi, n, mc, ma))
    return Calibration(float(ece), bins, int(c.size))
