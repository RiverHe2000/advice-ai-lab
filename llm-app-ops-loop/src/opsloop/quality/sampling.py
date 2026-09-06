"""Which traces to send to the (expensive) judge or a human reviewer.

``stratified``: every error, then every trace with negative feedback, then low-heuristic-score
traces, then uniform random - in that priority order until the budget is spent, so the sample
is deliberately failure-heavy (what a judge should look at). ``uniform``: a seeded random sample
(what a representative evaluation set should be grown from). Both exclude already-judged ids
when asked, so repeated runs keep covering new traces."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from opsloop.store import TraceRow

Strategy = Literal["stratified", "uniform"]


class Sample(BaseModel):
    trace_ids: list[str]
    strata: dict[str, int] = Field(default_factory=dict)
    budget: int
    population: int
    seed: int
    strategy: str = "stratified"

    def as_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def sample_traces(
    rows: Sequence[TraceRow],
    *,
    budget: int,
    seed: int = 0,
    low_quality: float = 0.75,
    exclude: set[str] | None = None,
    strategy: Strategy = "stratified",
) -> Sample:
    exclude = exclude or set()
    pool = [r for r in rows if r.trace_id not in exclude]
    chosen: list[str] = []
    seen: set[str] = set()
    strata: dict[str, int] = {"error": 0, "negative_feedback": 0, "low_quality": 0, "random": 0}
    rng = random.Random(seed)

    def take(row: TraceRow, stratum: str) -> bool:
        if len(chosen) >= budget:
            return False
        if row.trace_id in seen:
            return True
        seen.add(row.trace_id)
        chosen.append(row.trace_id)
        strata[stratum] += 1
        return True

    if strategy == "stratified":
        for r in pool:
            if r.status == "error" and not take(r, "error"):
                break
        for r in pool:
            if r.negative_feedback and not take(r, "negative_feedback"):
                break
        low = [r for r in pool if r.quality is not None and r.quality < low_quality]
        rng.shuffle(low)
        for r in low:
            if not take(r, "low_quality"):
                break
    remaining = [r for r in pool if r.trace_id not in seen]
    rng.shuffle(remaining)
    for r in remaining:
        if not take(r, "random"):
            break
    return Sample(
        trace_ids=chosen,
        strata=strata,
        budget=budget,
        population=len(pool),
        seed=seed,
        strategy=strategy,
    )
