"""SLO / alerting configuration (``slos/default.yaml``)."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

Indicator = Literal[
    "latency",
    "error",
    "cost",
    "quality",
    "judge",
    "refusal",
    "negative_feedback",
    "invalid_json",
    "pii_leak",
    "grounding",
]
Severity = Literal["warning", "critical"]


class SloSpec(BaseModel):
    """Every SLO is "at most ``budget`` of eligible requests may be *bad*"; what "bad" means
    is the indicator (latency above ``threshold`` ms, an error, cost above ``threshold`` USD,
    heuristic quality below ``threshold``, ...). A p95 latency objective is the same statement
    with budget 0.05."""

    name: str
    indicator: Indicator
    budget: float = Field(gt=0.0, le=1.0)
    threshold: float | None = None
    min_requests: int = 20
    min_requests_short: int | None = None
    floor: float | None = None  # band lower bound (e.g. a refusal rate that is suspiciously low)
    description: str = ""

    @property
    def short_min(self) -> int:
        return (
            self.min_requests_short
            if self.min_requests_short is not None
            else max(3, self.min_requests // 4)
        )


class BurnWindow(BaseModel):
    name: str
    long_minutes: float = Field(gt=0)
    short_minutes: float = Field(gt=0)
    burn_rate: float = Field(gt=0)
    severity: Severity = "warning"
    min_bad_events: int = 3  # the long window must hold at least this many bad events


class DriftConfig(BaseModel):
    enabled: bool = True
    window_minutes: float = 20.0
    k: int = 8
    min_df: int = 0
    holdout: float = 0.5
    novelty_quantile: float = 0.95
    novel_alpha: float = 0.001
    novel_min: int = 5
    alpha: float = 0.01
    n_boot: int = 200
    quantile: float = 0.99
    min_requests: int = 30
    embedder: Literal["hashing", "sentence-transformers"] = "hashing"
    dim: int = 256
    seed: int = 0


class MonitorConfig(BaseModel):
    step_minutes: float = 5.0
    baseline_minutes: float = 60.0
    escalation_consecutive: int = 2
    windows: list[BurnWindow] = Field(
        default_factory=lambda: [
            BurnWindow(
                name="page", long_minutes=10, short_minutes=2, burn_rate=3.0, severity="critical"
            ),
            BurnWindow(
                name="fast", long_minutes=30, short_minutes=5, burn_rate=2.0, severity="critical"
            ),
            BurnWindow(
                name="slow", long_minutes=120, short_minutes=15, burn_rate=1.0, severity="warning"
            ),
        ]
    )
    drift: DriftConfig = Field(default_factory=DriftConfig)
    slos: list[SloSpec] = Field(default_factory=list)

    @property
    def max_window_minutes(self) -> float:
        longest = max((w.long_minutes for w in self.windows), default=0.0)
        return max(longest, self.drift.window_minutes if self.drift.enabled else 0.0)

    @classmethod
    def load(cls, path: Path) -> MonitorConfig:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def slo(self, name: str) -> SloSpec:
        for s in self.slos:
            if s.name == name:
                return s
        msg = f"unknown SLO {name!r}"
        raise KeyError(msg)
