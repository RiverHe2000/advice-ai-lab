"""Prompt canary with automatic rollback.

Assignment hashes the session id into 100 buckets so a session always sees the same prompt
version and the split is reproducible. ``evaluate_canary`` compares the canary cohort with the
control cohort on the same window: one-sided two-proportion tests for error and refusal rates
(canary worse than control by more than the allowed delta), a bootstrap interval on the
difference in heuristic quality means, and a minimum sample size per cohort before any decision.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from pydantic import BaseModel, Field

from opsloop.stats import percentile, two_proportion_test
from opsloop.store import TraceRow
from opsloop.timeutil import iso

Cohort = Literal["canary", "control"]
Action = Literal["advance", "rollback", "hold", "promote"]


class CanaryState(BaseModel):
    version: str
    stage: int = 10
    started: str | None = None


class PromptRelease(BaseModel):
    active: str
    canary: CanaryState | None = None
    stages: list[int] = Field(default_factory=lambda: [10, 50, 100])
    history: list[dict[str, Any]] = Field(default_factory=list)


class CanaryPolicy(BaseModel):
    min_samples: int = 100
    error_rate_delta: float = 0.02
    refusal_rate_delta: float = 0.05
    quality_margin: float = 0.05
    alpha: float = 0.05
    n_boot: int = 1000


class ReleaseFile(BaseModel):
    policy: CanaryPolicy = Field(default_factory=CanaryPolicy)
    environments: dict[str, dict[str, PromptRelease]] = Field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> ReleaseFile:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls.model_validate(raw)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(self.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
            encoding="utf-8",
        )

    def get(self, environment: str, name: str) -> PromptRelease:
        try:
            return self.environments[environment][name]
        except KeyError as exc:
            msg = f"no release entry for {name!r} in environment {environment!r}"
            raise KeyError(msg) from exc


def bucket(session_id: str) -> int:
    return int(hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:8], 16) % 100


def assign(session_id: str, stage_pct: int) -> Cohort:
    return "canary" if bucket(session_id) < stage_pct else "control"


def resolve_version(release: PromptRelease, session_id: str) -> str:
    if release.canary is None or release.canary.stage <= 0:
        return release.active
    return (
        release.canary.version
        if assign(session_id, release.canary.stage) == "canary"
        else release.active
    )


@dataclass(frozen=True, slots=True)
class CohortMetrics:
    version: str
    n: int
    errors: int
    refusals: int
    error_rate: float
    refusal_rate: float
    quality_mean: float
    quality_values: tuple[float, ...]
    negative_feedback_rate: float
    latency_p95_ms: float
    cost_mean_usd: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "n": self.n,
            "errors": self.errors,
            "refusals": self.refusals,
            "error_rate": round(self.error_rate, 4),
            "refusal_rate": round(self.refusal_rate, 4),
            "quality_mean": round(self.quality_mean, 4)
            if not math.isnan(self.quality_mean)
            else None,
            "negative_feedback_rate": round(self.negative_feedback_rate, 4),
            "latency_p95_ms": round(self.latency_p95_ms, 1)
            if not math.isnan(self.latency_p95_ms)
            else None,
            "cost_mean_usd": round(self.cost_mean_usd, 6)
            if not math.isnan(self.cost_mean_usd)
            else None,
        }


def cohort_metrics(rows: Sequence[TraceRow], version: str) -> CohortMetrics:
    n = len(rows)
    errors = sum(1 for r in rows if r.status == "error")
    ok = [r for r in rows if r.status == "ok"]
    refusals = sum(1 for r in ok if r.refusal)
    quality = tuple(float(r.quality) for r in ok if r.quality is not None)
    costs = [float(r.cost_usd) for r in rows if r.cost_usd is not None]
    return CohortMetrics(
        version=version,
        n=n,
        errors=errors,
        refusals=refusals,
        error_rate=errors / n if n else math.nan,
        refusal_rate=refusals / len(ok) if ok else math.nan,
        quality_mean=float(np.mean(quality)) if quality else math.nan,
        quality_values=quality,
        negative_feedback_rate=sum(1 for r in rows if r.negative_feedback) / n if n else math.nan,
        latency_p95_ms=percentile([r.latency_ms for r in rows], 95),
        cost_mean_usd=float(np.mean(costs)) if costs else math.nan,
    )


class CanaryDecision(BaseModel):
    action: Action
    reasons: list[str]
    canary: dict[str, Any]
    control: dict[str, Any]
    tests: dict[str, Any]
    from_stage: int
    to_stage: int | None


def _quality_diff_ci(
    canary: Sequence[float], control: Sequence[float], *, n_boot: int, seed: int
) -> tuple[float, float, float]:
    a = np.asarray(canary, dtype=np.float64)
    b = np.asarray(control, dtype=np.float64)
    if a.size == 0 or b.size == 0:
        return math.nan, math.nan, math.nan
    rng = np.random.default_rng(seed)
    ia = rng.integers(0, a.size, size=(n_boot, a.size))
    ib = rng.integers(0, b.size, size=(n_boot, b.size))
    diffs = a[ia].mean(axis=1) - b[ib].mean(axis=1)
    lo, hi = (float(x) for x in np.quantile(diffs, [0.025, 0.975]))
    return float(a.mean() - b.mean()), lo, hi


def evaluate_canary(
    rows: Sequence[TraceRow],
    release: PromptRelease,
    policy: CanaryPolicy,
    *,
    seed: int = 0,
    control_rows: Sequence[TraceRow] | None = None,
) -> CanaryDecision:
    """Compare the canary cohort in ``rows`` with the control cohort. ``control_rows`` lets the
    caller supply a historical control (the last window before a 100 % stage, when no
    concurrent control traffic exists any more)."""
    if release.canary is None:
        return CanaryDecision(
            action="hold",
            reasons=["no canary in flight"],
            canary={},
            control={},
            tests={},
            from_stage=0,
            to_stage=None,
        )
    stage = release.canary.stage
    canary_rows = [r for r in rows if r.prompt_version == release.canary.version]
    control_pool = rows if control_rows is None else control_rows
    control_cohort = [r for r in control_pool if r.prompt_version == release.active]
    cm = cohort_metrics(canary_rows, release.canary.version)
    ct = cohort_metrics(control_cohort, release.active)
    tests: dict[str, Any] = {}
    reasons: list[str] = []
    if cm.n < policy.min_samples or ct.n < policy.min_samples:
        reasons.append(
            f"insufficient samples: canary {cm.n}, control {ct.n} (need {policy.min_samples} each)"
        )
        return CanaryDecision(
            action="hold",
            reasons=reasons,
            canary=cm.as_dict(),
            control=ct.as_dict(),
            tests=tests,
            from_stage=stage,
            to_stage=None,
        )
    rollback = False
    err = two_proportion_test(cm.errors, cm.n, ct.errors, ct.n, alternative="greater")
    tests["error_rate"] = {
        "diff": round(err.diff, 4),
        "z": round(err.z, 3),
        "p": round(err.p_value, 4),
    }
    if err.diff > policy.error_rate_delta and err.p_value < policy.alpha:
        rollback = True
        reasons.append(
            f"error rate {cm.error_rate:.3f} vs control {ct.error_rate:.3f} "
            f"(+{err.diff:.3f} > {policy.error_rate_delta}, p={err.p_value:.4f})"
        )
    n_ok_c = cm.n - cm.errors
    n_ok_t = ct.n - ct.errors
    ref = two_proportion_test(cm.refusals, n_ok_c, ct.refusals, n_ok_t, alternative="greater")
    tests["refusal_rate"] = {
        "diff": round(ref.diff, 4),
        "z": round(ref.z, 3),
        "p": round(ref.p_value, 4),
    }
    if ref.diff > policy.refusal_rate_delta and ref.p_value < policy.alpha:
        rollback = True
        reasons.append(
            f"refusal rate {cm.refusal_rate:.3f} vs control {ct.refusal_rate:.3f} "
            f"(+{ref.diff:.3f} > {policy.refusal_rate_delta}, p={ref.p_value:.4f})"
        )
    diff, lo, hi = _quality_diff_ci(
        cm.quality_values, ct.quality_values, n_boot=policy.n_boot, seed=seed
    )
    tests["quality_mean"] = {
        "diff": round(diff, 4),
        "ci_low": round(lo, 4),
        "ci_high": round(hi, 4),
    }
    if not math.isnan(hi) and hi < -policy.quality_margin:
        rollback = True
        reasons.append(
            f"quality mean {cm.quality_mean:.3f} vs control {ct.quality_mean:.3f}: "
            f"95% CI [{lo:+.3f}, {hi:+.3f}] entirely below -{policy.quality_margin}"
        )
    if rollback:
        return CanaryDecision(
            action="rollback",
            reasons=reasons,
            canary=cm.as_dict(),
            control=ct.as_dict(),
            tests=tests,
            from_stage=stage,
            to_stage=0,
        )
    later = [s for s in release.stages if s > stage]
    if not later:
        reasons.append("canary healthy at 100%: promote to active")
        return CanaryDecision(
            action="promote",
            reasons=reasons,
            canary=cm.as_dict(),
            control=ct.as_dict(),
            tests=tests,
            from_stage=stage,
            to_stage=100,
        )
    reasons.append(f"canary healthy at {stage}%: advance to {later[0]}%")
    return CanaryDecision(
        action="advance",
        reasons=reasons,
        canary=cm.as_dict(),
        control=ct.as_dict(),
        tests=tests,
        from_stage=stage,
        to_stage=later[0],
    )


def start_canary(
    release: PromptRelease, version: str, *, now: float, stage: int | None = None
) -> None:
    first = stage if stage is not None else (release.stages[0] if release.stages else 10)
    release.canary = CanaryState(version=version, stage=first, started=iso(now))
    release.history.append({"ts": iso(now), "event": "start", "version": version, "stage": first})


def advance(release: PromptRelease, *, now: float, reason: str = "manual") -> int:
    if release.canary is None:
        msg = "no canary in flight"
        raise ValueError(msg)
    later = [s for s in release.stages if s > release.canary.stage]
    if not later:
        promoted = release.canary.version
        release.history.append(
            {
                "ts": iso(now),
                "event": "promote",
                "version": promoted,
                "from": release.active,
                "reason": reason,
            }
        )
        release.active = promoted
        release.canary = None
        return 100
    release.canary.stage = later[0]
    release.history.append(
        {
            "ts": iso(now),
            "event": "advance",
            "version": release.canary.version,
            "stage": later[0],
            "reason": reason,
        }
    )
    return later[0]


def rollback(release: PromptRelease, *, now: float, reason: str = "manual") -> str:
    if release.canary is None:
        msg = "no canary in flight"
        raise ValueError(msg)
    version = release.canary.version
    release.history.append(
        {
            "ts": iso(now),
            "event": "rollback",
            "version": version,
            "from_stage": release.canary.stage,
            "reason": reason,
        }
    )
    release.canary = None
    return version


def apply_decision(release: PromptRelease, decision: CanaryDecision, *, now: float) -> None:
    reason = "; ".join(decision.reasons)
    if decision.action == "rollback":
        rollback(release, now=now, reason=reason)
    elif decision.action in ("advance", "promote"):
        advance(release, now=now, reason=reason)
