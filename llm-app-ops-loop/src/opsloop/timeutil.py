"""Epoch-seconds helpers and a simulated clock (the demo runs four hours in milliseconds)."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_DURATION = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*$", flags=re.IGNORECASE)
_UNITS = {"s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0, "w": 604800.0}


def parse_duration(text: str) -> float:
    """``"30d"`` / ``"2h"`` / ``"15m"`` / ``"90s"`` → seconds."""
    m = _DURATION.match(text)
    if not m:
        msg = f"invalid duration {text!r} (expected e.g. 30d, 2h, 15m, 90s)"
        raise ValueError(msg)
    return float(m.group(1)) * _UNITS[m.group(2).lower()]


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def from_iso(text: str) -> float:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()


def minutes_between(t0: float, t1: float) -> float:
    return (t1 - t0) / 60.0


class SimClock:
    """A clock the demo advances explicitly instead of sleeping; ``now()`` is epoch seconds."""

    def __init__(self, start: float) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def advance(self, seconds: float) -> float:
        self._now += float(seconds)
        return self._now

    def set(self, ts: float) -> None:
        self._now = float(ts)


DEMO_EPOCH = datetime(2026, 9, 1, 0, 0, tzinfo=UTC).timestamp()
