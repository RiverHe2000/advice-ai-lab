"""Scenario YAML: traffic shape plus planted incidents with start/end minutes. The incidents are
the ground truth for ``opsloop monitor evaluate``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

IncidentKind = Literal[
    "latency_spike", "error_burst", "regressed_prompt", "topic_shift", "cost_creep", "pii_leak"
]

# Which alert families count as *detecting* each incident kind.
EXPECTED_ALERTS: dict[str, list[str]] = {
    "latency_spike": ["latency_p95"],
    "error_burst": ["error_rate"],
    "regressed_prompt": ["quality_mean", "refusal_rate", "json_validity", "grounding_rate"],
    "topic_shift": ["topic_drift"],
    "cost_creep": ["cost_per_request"],
    "pii_leak": ["pii_leak_rate"],
}
DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    "latency_spike": {"multiplier": 2.0},
    "error_burst": {
        "error_rate": 0.25,
        "kinds": ["timeout", "provider_error"],
        "tool_error_rate": 0.0,
    },
    "regressed_prompt": {"version": "v2-regressed"},
    "topic_shift": {"share": 0.35},
    "cost_creep": {"verbosity": 5.0},
    "pii_leak": {},
}


class Incident(BaseModel):
    kind: IncidentKind
    start_minute: float = Field(ge=0)
    end_minute: float = Field(gt=0)
    params: dict[str, Any] = Field(default_factory=dict)
    expected_alerts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _defaults(self) -> Incident:
        if self.end_minute <= self.start_minute:
            msg = f"{self.kind}: end_minute must be after start_minute"
            raise ValueError(msg)
        merged = {**DEFAULT_PARAMS[self.kind], **self.params}
        object.__setattr__(self, "params", merged)
        if not self.expected_alerts:
            object.__setattr__(self, "expected_alerts", list(EXPECTED_ALERTS[self.kind]))
        return self

    def active(self, minute: float) -> bool:
        return self.start_minute <= minute < self.end_minute


class TrafficSpec(BaseModel):
    rate_per_minute: float = 5.0
    sessions: int = 40
    clients: int = 200
    book_seed: int = 7
    sample_rate: float = 1.0
    out_of_scope_share: float = 0.03
    base_error_rate: float = 0.003
    tfn_in_question_rate: float = 0.01
    feedback: bool = True


class CanarySpec(BaseModel):
    version: str
    stage: int = 10


class Scenario(BaseModel):
    name: str
    description: str = ""
    traffic: TrafficSpec = Field(default_factory=TrafficSpec)
    active_version: str = "v1"
    canary: CanarySpec | None = None
    incidents: list[Incident] = Field(default_factory=list)

    def active_incidents(self, minute: float) -> list[Incident]:
        return [i for i in self.incidents if i.active(minute)]

    def incident_active(self, minute: float) -> bool:
        return any(i.active(minute) for i in self.incidents)


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return Scenario.model_validate(raw)


def load_scenarios(paths: list[Path]) -> list[Scenario]:
    return [load_scenario(p) for p in paths]
