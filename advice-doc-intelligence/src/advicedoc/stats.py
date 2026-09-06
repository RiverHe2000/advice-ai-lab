"""Statistics used by every evaluation: seeded percentile bootstrap intervals, a paired
bootstrap plus exact McNemar test for comparing two systems on the same cases, and expected
calibration error with a reliability table for any probability a human will act on."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True, slots=True)
class Interval:
    point: float
    low: float
    high: float
    n: int

    def fmt(self, digits: int = 3, *, pct: bool = False) -> str:
        if math.isnan(self.point):
            return "n/a"
        if pct:
            return (
                f"{100 * self.point:.{digits}f} % "
                f"[{100 * self.low:.{digits}f}, {100 * self.high:.{digits}f}]"
            )
        return f"{self.point:.{digits}f} [{self.low:.{digits}f}, {self.high:.{digits}f}]"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def bootstrap_statistic(
    n: int,
    statistic: Callable[[np.ndarray], float],
    *,
    n_boot: int = 1000,
    seed: int = 0,
    level: float = 0.95,
) -> Interval:
    """Percentile bootstrap of ``statistic(index_array)`` over ``n`` cases."""
    if n == 0:
        return Interval(math.nan, math.nan, math.nan, 0)
    point = float(statistic(np.arange(n)))
    if n == 1 or n_boot == 0:
        return Interval(point, point, point, n)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, n, size=(n_boot, n))
    samples = np.asarray([statistic(row) for row in idx], dtype=np.float64)
    if np.isnan(samples).all():
        return Interval(point, math.nan, math.nan, n)
    alpha = (1.0 - level) / 2.0
    low, high = (float(x) for x in np.nanquantile(samples, [alpha, 1.0 - alpha]))
    return Interval(point, low, high, n)


def bootstrap_mean(
    values: Sequence[float] | np.ndarray,
    *,
    n_boot: int = 1000,
    seed: int = 0,
    level: float = 0.95,
) -> Interval:
    arr = np.asarray(list(values), dtype=np.float64)
    return bootstrap_statistic(
        len(arr), lambda idx: float(arr[idx].mean()), n_boot=n_boot, seed=seed, level=level
    )


def mcnemar_exact(wins: int, losses: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs (binomial, p = 0.5)."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return float(min(1.0, 2.0 * tail))


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

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def paired_bootstrap(
    a: Sequence[float],
    b: Sequence[float],
    *,
    n_boot: int = 1000,
    seed: int = 0,
    level: float = 0.95,
    non_inferiority_margin: float = 0.0,
) -> PairedComparison:
    """Bootstrap the mean of per-case differences ``a - b`` (A is the candidate)."""
    x = np.asarray(list(a), dtype=np.float64)
    y = np.asarray(list(b), dtype=np.float64)
    if len(x) != len(y):
        msg = f"paired comparison needs equal lengths, got {len(x)} and {len(y)}"
        raise ValueError(msg)
    if len(x) == 0:
        nan = math.nan
        return PairedComparison(0, nan, nan, nan, nan, nan, nan, 0, 0, 1.0, "no pairs")
    deltas = x - y
    wins = int((deltas > 0).sum())
    losses = int((deltas < 0).sum())
    ci = bootstrap_mean(deltas, n_boot=n_boot, seed=seed, level=level)
    if len(deltas) == 1 or n_boot == 0:
        p_improve = float(deltas.mean() > 0)
    else:
        rng = np.random.default_rng(seed)
        idx = rng.integers(0, len(deltas), size=(n_boot, len(deltas)))
        p_improve = float((deltas[idx].mean(axis=1) > 0).mean())
    if ci.low > 0:
        verdict = "better"
    elif ci.high < -non_inferiority_margin:
        verdict = "worse"
    elif ci.low >= -non_inferiority_margin:
        verdict = "non-inferior"
    else:
        verdict = "inconclusive"
    return PairedComparison(
        n_pairs=len(x),
        mean_a=float(x.mean()),
        mean_b=float(y.mean()),
        delta=float(deltas.mean()),
        ci_low=ci.low,
        ci_high=ci.high,
        p_improve=p_improve,
        wins=wins,
        losses=losses,
        mcnemar_p=mcnemar_exact(wins, losses),
        verdict=verdict,
    )


def render_paired(label_a: str, label_b: str, c: PairedComparison) -> str:
    return (
        f"| {label_a} vs {label_b} | {c.n_pairs} | {c.mean_a:.3f} | {c.mean_b:.3f} | "
        f"{c.delta:+.3f} | [{c.ci_low:+.3f}, {c.ci_high:+.3f}] | {c.p_improve:.2f} | "
        f"{c.wins} / {c.losses} | {c.mcnemar_p:.3f} | {c.verdict} |"
    )


PAIRED_HEADER = (
    "| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | "
    "McNemar p | Verdict |\n|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|"
)


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    low: float
    high: float
    count: int
    mean_confidence: float
    accuracy: float


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    ece: float
    n: int
    bins: tuple[ReliabilityBin, ...]

    def table_md(self) -> str:
        lines = [
            "| Confidence bin | n | Mean confidence | Accuracy | gap |",
            "|---|---:|---:|---:|---:|",
        ]
        for b in self.bins:
            if b.count == 0:
                lines.append(f"| [{b.low:.1f}, {b.high:.1f}) | 0 | - | - | - |")
            else:
                gap = b.accuracy - b.mean_confidence
                lines.append(
                    f"| [{b.low:.1f}, {b.high:.1f}) | {b.count} | {b.mean_confidence:.3f} | "
                    f"{b.accuracy:.3f} | {gap:+.3f} |"
                )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {"ece": self.ece, "n": self.n, "bins": [asdict(b) for b in self.bins]}


def expected_calibration_error(
    confidences: Sequence[float] | np.ndarray,
    correct: Sequence[bool] | Sequence[int] | np.ndarray,
    *,
    n_bins: int = 10,
) -> CalibrationResult:
    """ECE with equal-width bins on [0, 1]: sum over bins of (n_b / n) * |acc_b - conf_b|."""
    conf = np.asarray(list(confidences), dtype=np.float64)
    hit = np.asarray(list(correct), dtype=np.float64)
    if len(conf) != len(hit):
        msg = "confidences and correctness must have the same length"
        raise ValueError(msg)
    n = len(conf)
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[ReliabilityBin] = []
    ece = 0.0
    for i in range(n_bins):
        low, high = float(edges[i]), float(edges[i + 1])
        mask = (conf >= low) & (conf < high) if i < n_bins - 1 else (conf >= low) & (conf <= high)
        count = int(mask.sum())
        if count == 0:
            bins.append(ReliabilityBin(low, high, 0, math.nan, math.nan))
            continue
        mean_conf = float(conf[mask].mean())
        acc = float(hit[mask].mean())
        ece += (count / n) * abs(acc - mean_conf)
        bins.append(ReliabilityBin(low, high, count, mean_conf, acc))
    return CalibrationResult(ece=float(ece) if n else math.nan, n=n, bins=tuple(bins))
