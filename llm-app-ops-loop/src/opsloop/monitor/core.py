"""The monitor: at each evaluation tick, window the traces, evaluate every SLO on every burn
window pair, run the drift test against the baseline, escalate alerts that persist, and return
an ``Evaluation`` record."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from opsloop.monitor.alerts import Alert, burn_rate_alert, floor_alert
from opsloop.monitor.config import MonitorConfig
from opsloop.monitor.drift import DriftResult, Embedder, TopicModel, build_embedder, drift_test
from opsloop.monitor.slo import RowWindow, evaluate_slo, window_summary
from opsloop.store import TraceRow

Fetch = Callable[[float, float], list[TraceRow]]


class MonitorState(BaseModel):
    consecutive: dict[str, int] = Field(default_factory=dict)
    last_as_of: float | None = None

    @classmethod
    def load(cls, path: Path) -> MonitorState:
        if not path.exists():
            return cls()
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), indent=2), encoding="utf-8")


class Evaluation(BaseModel):
    as_of: float
    n_requests: int
    indicators: dict[str, dict[str, Any]]
    alerts: list[Alert]
    drift: DriftResult | None = None
    summary: dict[str, Any] = Field(default_factory=dict)

    @property
    def alert_names(self) -> set[str]:
        return {a.name for a in self.alerts}


class Monitor:
    def __init__(
        self,
        config: MonitorConfig,
        fetch: Fetch,
        *,
        start_ts: float | None = None,
        baseline: tuple[float, float] | None = None,
        embedder: Embedder | None = None,
        state: MonitorState | None = None,
    ) -> None:
        self.config = config
        self.fetch = fetch
        self.state = state or MonitorState()
        self.start_ts = start_ts
        self._baseline = baseline
        if baseline is None and start_ts is not None and config.baseline_minutes > 0:
            self._baseline = (start_ts, start_ts + config.baseline_minutes * 60.0)
        self._embedder = embedder or build_embedder(config.drift.embedder, dim=config.drift.dim)
        self._topics: TopicModel | None = None

    @property
    def baseline(self) -> tuple[float, float] | None:
        return self._baseline

    def _fit_topics(self) -> TopicModel | None:
        if self._topics is not None or self._baseline is None or not self.config.drift.enabled:
            return self._topics
        rows = self.fetch(self._baseline[0], self._baseline[1])
        texts = [r.input_text for r in rows if r.input_text]
        if len(texts) < self.config.drift.min_requests:
            return None
        self._topics = TopicModel(
            self._embedder,
            k=self.config.drift.k,
            seed=self.config.drift.seed,
            min_df=self.config.drift.min_df,
            holdout=self.config.drift.holdout,
            novelty_quantile=self.config.drift.novelty_quantile,
        ).fit(texts)
        return self._topics

    def evaluate(self, as_of: float) -> Evaluation:
        cfg = self.config
        horizon = as_of - cfg.max_window_minutes * 60.0
        window = RowWindow(self.fetch(horizon, as_of))
        alerts: list[Alert] = []
        indicators: dict[str, dict[str, Any]] = {}
        fast = min(cfg.windows, key=lambda w: w.long_minutes) if cfg.windows else None
        # A window is evaluated only once it has existed for its full length: a 2-hour window
        # holding five minutes of data is not a 2-hour window.
        full = [w for w in cfg.windows if self._full(w.long_minutes, as_of)]
        for slo in cfg.slos:
            fired: Alert | None = None
            for w in sorted(full, key=lambda w: w.long_minutes):
                long_rows = window.between(as_of - w.long_minutes * 60.0, as_of)
                short_rows = window.between(as_of - w.short_minutes * 60.0, as_of)
                candidate = burn_rate_alert(slo, w, long_rows, short_rows, as_of=as_of)
                if candidate is not None and (fired is None or _rank(candidate) > _rank(fired)):
                    fired = candidate
            if fired is not None:
                alerts.append(fired)
            slowest = max(cfg.windows, key=lambda w: w.long_minutes) if cfg.windows else None
            if slo.floor is not None and slowest is not None and slowest in full:
                low = floor_alert(
                    slo,
                    slowest,
                    window.between(as_of - slowest.long_minutes * 60.0, as_of),
                    as_of=as_of,
                )
                if low is not None:
                    alerts.append(low)
            if fast is not None:
                value = evaluate_slo(slo, window.between(as_of - fast.long_minutes * 60.0, as_of))
                indicators[slo.name] = value.as_dict()
        drift: DriftResult | None = None
        if cfg.drift.enabled and self._baseline is not None:
            drift = self._evaluate_drift(window, as_of)
            if drift is not None and drift.drifted:
                alerts.append(
                    Alert(
                        name="topic_drift",
                        severity="warning",
                        kind="drift",
                        window=f"{cfg.drift.window_minutes:g}m",
                        value=drift.js,
                        threshold=drift.threshold,
                        as_of=as_of,
                        evidence={
                            "trigger": drift.trigger,
                            "p_value": drift.p_value,
                            "chi2": drift.chi2,
                            "novel_share_baseline": drift.novel_share_baseline,
                            "novel_share_current": drift.novel_share_current,
                            "novel_p_value": drift.novel_p_value,
                            "grown": [g.model_dump() for g in drift.grown[:3]],
                            "n_current": drift.n_current,
                            "n_baseline": drift.n_baseline,
                        },
                        message=(
                            f"topic drift ({drift.trigger}): JS {drift.js:.3f} vs "
                            f"{drift.threshold:.3f}, chi-square p={drift.p_value:.2e}, novel share "
                            f"{drift.novel_share_baseline:.0%} -> {drift.novel_share_current:.0%} "
                            f"(p={drift.novel_p_value:.1e}); grown: "
                            + ", ".join(
                                f"{'novel' if g.novel else f'topic {g.topic}'} "
                                f"({' '.join(g.terms)}) +{g.delta:.0%}"
                                for g in drift.grown[:3]
                            )
                        ),
                    )
                )
        alerts = self._escalate(alerts)
        summary_rows = window.between(
            as_of - (fast.long_minutes if fast else cfg.max_window_minutes) * 60.0, as_of
        )
        self.state.last_as_of = as_of
        return Evaluation(
            as_of=as_of,
            n_requests=len(summary_rows),
            indicators=indicators,
            alerts=alerts,
            drift=drift,
            summary=window_summary(summary_rows),
        )

    def _full(self, minutes: float, as_of: float) -> bool:
        return self.start_ts is None or as_of - minutes * 60.0 >= self.start_ts - 1e-6

    def _evaluate_drift(self, window: RowWindow, as_of: float) -> DriftResult | None:
        assert self._baseline is not None
        cfg = self.config.drift
        t0 = as_of - cfg.window_minutes * 60.0
        if t0 < self._baseline[1]:
            return None
        model = self._fit_topics()
        if model is None:
            return None
        texts = [r.input_text for r in window.between(t0, as_of) if r.input_text]
        if len(texts) < cfg.min_requests:
            return None
        return drift_test(
            model,
            texts,
            alpha=cfg.alpha,
            n_boot=cfg.n_boot,
            quantile=cfg.quantile,
            seed=cfg.seed,
            novel_alpha=cfg.novel_alpha,
            novel_min=cfg.novel_min,
        )

    def _escalate(self, alerts: list[Alert]) -> list[Alert]:
        fired = {a.name for a in alerts}
        for name in list(self.state.consecutive):
            if name not in fired:
                self.state.consecutive[name] = 0
        out: list[Alert] = []
        for a in alerts:
            count = self.state.consecutive.get(a.name, 0) + 1
            self.state.consecutive[a.name] = count
            severity = a.severity
            if severity == "warning" and count >= self.config.escalation_consecutive:
                severity = "critical"
            out.append(a.model_copy(update={"consecutive": count, "severity": severity}))
        return out

    def run(
        self, start_ts: float, end_ts: float, *, step_minutes: float | None = None
    ) -> list[Evaluation]:
        step = (step_minutes or self.config.step_minutes) * 60.0
        evaluations: list[Evaluation] = []
        t = start_ts + step
        while t <= end_ts + 1e-9:
            evaluations.append(self.evaluate(t))
            t += step
        return evaluations


def _rank(alert: Alert) -> int:
    return 2 if alert.severity == "critical" else 1


def alerts_table(evaluations: Sequence[Evaluation], start_ts: float) -> str:
    lines = ["| minute | alerts |", "|---:|---|"]
    for ev in evaluations:
        names = ", ".join(f"{a.name} ({a.severity}, {a.window})" for a in ev.alerts) or "-"
        lines.append(f"| {(ev.as_of - start_ts) / 60.0:.0f} | {names} |")
    return "\n".join(lines)
