"""Prometheus exporter: the latest monitor evaluation as gauges. Windows are anchored on the
newest trace in the store (``as_of`` = last end timestamp) so simulated or replayed traffic is
observable; a live deployment would pass ``as_of=None`` and get wall-clock time."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Response
from prometheus_client import CollectorRegistry, Gauge, generate_latest

from opsloop.monitor.config import MonitorConfig
from opsloop.monitor.core import Evaluation, Monitor, MonitorState
from opsloop.store import TraceStore

CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
SUMMARY_GAUGES: dict[str, str] = {
    "error_rate": "opsloop_error_rate",
    "latency_p95_ms": "opsloop_latency_p95_ms",
    "latency_p50_ms": "opsloop_latency_p50_ms",
    "cost_per_request_usd": "opsloop_cost_per_request_usd",
    "quality_mean": "opsloop_quality_mean",
    "judge_mean": "opsloop_judge_mean",
    "refusal_rate": "opsloop_refusal_rate",
    "negative_feedback_rate": "opsloop_negative_feedback_rate",
    "json_validity_rate": "opsloop_json_validity_rate",
    "pii_leak_rate": "opsloop_pii_leak_rate",
    "grounding_rate": "opsloop_grounding_rate",
}


@dataclass
class Metrics:
    registry: CollectorRegistry
    slo_bad_fraction: Gauge
    slo_burn: Gauge
    slo_budget: Gauge
    alert_active: Gauge
    window_requests: Gauge
    summary: dict[str, Gauge]
    drift_js: Gauge
    drift_threshold: Gauge
    drift_p: Gauge
    drift_detected: Gauge
    store_traces: Gauge
    as_of: Gauge
    last_refresh: Gauge


def build_metrics() -> Metrics:
    reg = CollectorRegistry()
    return Metrics(
        registry=reg,
        slo_bad_fraction=Gauge(
            "opsloop_slo_bad_fraction",
            "Bad-event fraction in the fast long window",
            ["slo"],
            registry=reg,
        ),
        slo_burn=Gauge(
            "opsloop_slo_burn_rate",
            "Burn rate (bad fraction / budget) in the fast long window",
            ["slo"],
            registry=reg,
        ),
        slo_budget=Gauge(
            "opsloop_slo_budget", "Error budget (max bad fraction)", ["slo"], registry=reg
        ),
        alert_active=Gauge(
            "opsloop_alert_active", "1 while an alert is firing", ["name", "severity"], registry=reg
        ),
        window_requests=Gauge(
            "opsloop_window_requests", "Requests in the fast long window", registry=reg
        ),
        summary={
            k: Gauge(v, f"{k} over the fast long window", registry=reg)
            for k, v in SUMMARY_GAUGES.items()
        },
        drift_js=Gauge(
            "opsloop_topic_drift_js",
            "Jensen-Shannon distance of the topic mix vs baseline",
            registry=reg,
        ),
        drift_threshold=Gauge(
            "opsloop_topic_drift_threshold", "Bootstrap JS threshold", registry=reg
        ),
        drift_p=Gauge(
            "opsloop_topic_drift_p_value",
            "Two-sample chi-square p-value on the topic mix",
            registry=reg,
        ),
        drift_detected=Gauge(
            "opsloop_topic_drift_detected", "1 when the drift test fired", registry=reg
        ),
        store_traces=Gauge("opsloop_store_traces_total", "Traces in the store", registry=reg),
        as_of=Gauge(
            "opsloop_evaluation_as_of_seconds",
            "Timestamp the windows are anchored on",
            registry=reg,
        ),
        last_refresh=Gauge(
            "opsloop_last_refresh_timestamp_seconds",
            "Wall-clock time of the last refresh",
            registry=reg,
        ),
    )


def refresh(
    metrics: Metrics,
    store: TraceStore,
    config: MonitorConfig,
    *,
    as_of: float | None = None,
    state: MonitorState | None = None,
) -> Evaluation | None:
    rng = store.time_range()
    metrics.store_traces.set(store.count())
    metrics.last_refresh.set(time.time())
    for slo in config.slos:
        metrics.slo_budget.labels(slo=slo.name).set(slo.budget)
    if rng is None:
        return None
    anchor = as_of if as_of is not None else rng[1]
    monitor = Monitor(config, store.rows, start_ts=rng[0], state=state)
    ev = monitor.evaluate(anchor)
    metrics.as_of.set(anchor)
    metrics.window_requests.set(ev.n_requests)
    for name, ind in ev.indicators.items():
        frac = ind.get("fraction")
        burn = ind.get("burn")
        metrics.slo_bad_fraction.labels(slo=name).set(float("nan") if frac is None else frac)
        metrics.slo_burn.labels(slo=name).set(float("nan") if burn is None else burn)
    active = {(a.name, a.severity) for a in ev.alerts}
    known = {(s.name, sev) for s in config.slos for sev in ("warning", "critical")}
    known |= {("topic_drift", "warning"), ("topic_drift", "critical")}
    known |= {(f"{s.name}_low", "warning") for s in config.slos if s.floor is not None}
    for name, sev in known | active:
        metrics.alert_active.labels(name=name, severity=sev).set(
            1.0 if (name, sev) in active else 0.0
        )
    for key, gauge in metrics.summary.items():
        value = ev.summary.get(key)
        gauge.set(math.nan if value is None else float(value))
    if ev.drift is not None:
        metrics.drift_js.set(ev.drift.js)
        metrics.drift_threshold.set(ev.drift.threshold)
        metrics.drift_p.set(ev.drift.p_value)
        metrics.drift_detected.set(1.0 if ev.drift.drifted else 0.0)
    return ev


def metrics_app(
    store: TraceStore, config: MonitorConfig, *, metrics: Metrics | None = None
) -> FastAPI:
    app = FastAPI(title="opsloop monitor exporter")
    m = metrics or build_metrics()
    state = MonitorState()

    @app.get("/metrics")
    def _metrics() -> Response:
        refresh(m, store, config, state=state)
        return Response(content=generate_latest(m.registry), media_type=CONTENT_TYPE)

    @app.get("/health")
    def _health() -> dict[str, Any]:
        return {"status": "ok", "traces": store.count()}

    return app
