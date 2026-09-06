"""Window mathematics: which rows are eligible and bad for each indicator, the bad fraction and
burn rate over a window, and a plain summary of a window (what ``/v1/stats`` returns)."""

from __future__ import annotations

import bisect
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from opsloop.monitor.config import SloSpec
from opsloop.stats import percentile
from opsloop.store import TraceRow


def eligible_and_bad(slo: SloSpec, row: TraceRow) -> tuple[bool, bool]:
    ind = slo.indicator
    if ind == "latency":
        if row.status != "ok":  # errors have their own SLO; a 30 s timeout is not "slow"
            return False, False
        return True, row.latency_ms > float(slo.threshold or 0.0)
    if ind == "error":
        return True, row.status == "error"
    if ind == "cost":
        if row.cost_usd is None:
            return False, False
        return True, row.cost_usd > float(slo.threshold or 0.0)
    if ind == "quality":
        if row.quality is None:
            return False, False
        return True, row.quality < float(slo.threshold or 0.0)
    if ind == "judge":
        if row.judge is None:
            return False, False
        return True, row.judge < float(slo.threshold or 0.0)
    if ind == "refusal":
        if row.status != "ok" or row.refusal is None:
            return False, False
        return True, row.refusal
    if ind == "negative_feedback":
        return True, row.negative_feedback
    if ind == "invalid_json":
        if not row.json_expected or row.json_valid is None:
            return False, False
        return True, not row.json_valid
    if ind == "pii_leak":
        if row.status != "ok" or row.pii_leak is None:
            return False, False
        return True, row.pii_leak
    # grounding
    if row.status != "ok" or row.grounded is None:
        return False, False
    return True, not row.grounded


@dataclass(frozen=True, slots=True)
class IndicatorValue:
    name: str
    n: int
    bad: int
    fraction: float
    budget: float
    burn: float
    examples: tuple[str, ...]

    @property
    def evaluable(self) -> bool:
        return self.n > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "bad": self.bad,
            "fraction": None if math.isnan(self.fraction) else round(self.fraction, 5),
            "budget": self.budget,
            "burn": None if math.isnan(self.burn) else round(self.burn, 3),
        }


def evaluate_slo(
    slo: SloSpec, rows: Sequence[TraceRow], *, max_examples: int = 5
) -> IndicatorValue:
    n = bad = 0
    examples: list[str] = []
    for row in rows:
        eligible, is_bad = eligible_and_bad(slo, row)
        if not eligible:
            continue
        n += 1
        if is_bad:
            bad += 1
            if len(examples) < max_examples:
                examples.append(row.trace_id)
    fraction = bad / n if n else math.nan
    burn = fraction / slo.budget if n else math.nan
    return IndicatorValue(slo.name, n, bad, fraction, slo.budget, burn, tuple(examples))


class RowWindow:
    """Rows sorted by ``start_ts`` with O(log n) sub-window slicing."""

    def __init__(self, rows: Sequence[TraceRow]) -> None:
        self.rows = sorted(rows, key=lambda r: r.start_ts)
        self._ts = [r.start_ts for r in self.rows]

    def between(self, t0: float, t1: float) -> list[TraceRow]:
        """Rows with ``t0 < start_ts <= t1``."""
        lo = bisect.bisect_right(self._ts, t0)
        hi = bisect.bisect_right(self._ts, t1)
        return self.rows[lo:hi]

    def __len__(self) -> int:
        return len(self.rows)


def window_summary(rows: Sequence[TraceRow]) -> dict[str, Any]:
    n = len(rows)
    ok = [r for r in rows if r.status == "ok"]
    errors = n - len(ok)
    costs = [r.cost_usd for r in rows if r.cost_usd is not None]
    quality = [r.quality for r in ok if r.quality is not None]
    judged = [r.judge for r in ok if r.judge is not None]
    refusals = [r for r in ok if r.refusal is not None]
    json_rows = [r for r in ok if r.json_expected and r.json_valid is not None]
    pii_rows = [r for r in ok if r.pii_leak is not None]
    grounded_rows = [r for r in ok if r.grounded is not None]

    def _rate(num: int, den: int) -> float | None:
        return round(num / den, 5) if den else None

    return {
        "requests": n,
        "errors": errors,
        "error_rate": _rate(errors, n),
        "latency_p50_ms": round(percentile([r.latency_ms for r in rows], 50), 1) if n else None,
        "latency_p95_ms": round(percentile([r.latency_ms for r in rows], 95), 1) if n else None,
        "cost_per_request_usd": round(sum(costs) / len(costs), 6) if costs else None,
        "cost_missing": sum(1 for r in rows if r.cost_missing),
        "prompt_tokens_mean": round(sum(r.prompt_tokens for r in rows) / n, 1) if n else None,
        "completion_tokens_mean": round(sum(r.completion_tokens for r in rows) / n, 1)
        if n
        else None,
        "quality_mean": round(sum(quality) / len(quality), 4) if quality else None,
        "judge_mean": round(sum(judged) / len(judged), 3) if judged else None,
        "judged": len(judged),
        "refusal_rate": _rate(sum(1 for r in refusals if r.refusal), len(refusals)),
        "negative_feedback_rate": _rate(sum(1 for r in rows if r.negative_feedback), n),
        "json_validity_rate": _rate(sum(1 for r in json_rows if r.json_valid), len(json_rows)),
        "pii_leak_rate": _rate(sum(1 for r in pii_rows if r.pii_leak), len(pii_rows)),
        "grounding_rate": _rate(sum(1 for r in grounded_rows if r.grounded), len(grounded_rows)),
        "by_prompt_version": _count_by(rows, "prompt_version"),
        "by_error_class": _count_by([r for r in rows if r.status == "error"], "error_class"),
    }


def _count_by(rows: Sequence[TraceRow], attr: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        key = str(getattr(r, attr))
        out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))
