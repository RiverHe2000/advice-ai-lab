"""Burn-rate alerts (the Google SRE multi-window pattern: the long window says the budget is
really burning, the short window says it is still burning now) and band-floor alerts."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from opsloop.monitor.config import BurnWindow, SloSpec
from opsloop.monitor.slo import evaluate_slo
from opsloop.store import TraceRow

AlertKind = Literal["burn_rate", "floor", "drift"]


class Alert(BaseModel):
    name: str
    severity: Literal["warning", "critical"]
    kind: AlertKind
    window: str
    value: float
    threshold: float
    as_of: float
    consecutive: int = 1
    evidence: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


def burn_rate_alert(
    slo: SloSpec,
    window: BurnWindow,
    long_rows: Sequence[TraceRow],
    short_rows: Sequence[TraceRow],
    *,
    as_of: float,
) -> Alert | None:
    long_v = evaluate_slo(slo, long_rows)
    short_v = evaluate_slo(slo, short_rows)
    if long_v.n < slo.min_requests or short_v.n < slo.short_min:
        return None
    if (
        long_v.burn >= window.burn_rate
        and short_v.burn >= window.burn_rate
        and long_v.bad >= window.min_bad_events
    ):
        return Alert(
            name=slo.name,
            severity=window.severity,
            kind="burn_rate",
            window=window.name,
            value=long_v.burn,
            threshold=window.burn_rate,
            as_of=as_of,
            evidence={
                "long": {"minutes": window.long_minutes, **long_v.as_dict()},
                "short": {"minutes": window.short_minutes, **short_v.as_dict()},
                "examples": list(long_v.examples),
                "indicator": slo.indicator,
                "slo_threshold": slo.threshold,
            },
            message=(
                f"{slo.name}: {long_v.bad}/{long_v.n} bad in {window.long_minutes:g}m "
                f"(burn {long_v.burn:.1f}x) and {short_v.bad}/{short_v.n} in "
                f"{window.short_minutes:g}m (burn {short_v.burn:.1f}x) >= {window.burn_rate}x"
            ),
        )
    return None


def floor_alert(
    slo: SloSpec, window: BurnWindow, long_rows: Sequence[TraceRow], *, as_of: float
) -> Alert | None:
    if slo.floor is None:
        return None
    v = evaluate_slo(slo, long_rows)
    if v.n < slo.min_requests or v.fraction >= slo.floor:
        return None
    return Alert(
        name=f"{slo.name}_low",
        severity="warning",
        kind="floor",
        window=window.name,
        value=v.fraction,
        threshold=slo.floor,
        as_of=as_of,
        evidence={
            "long": {"minutes": window.long_minutes, **v.as_dict()},
            "indicator": slo.indicator,
        },
        message=(
            f"{slo.name}: {v.bad}/{v.n} in {window.long_minutes:g}m is below the floor "
            f"{slo.floor} - a rate this low usually means the signal broke"
        ),
    )
