"""``POST /v1/traces`` (one trace or ``{"traces": [...]}``), ``GET /v1/traces/{id}``,
``GET /v1/traces?since=&until=&status=&prompt_version=&session_id=&limit=``,
``GET /v1/stats?window=30m``, ``POST /v1/feedback``, ``GET /metrics``, ``GET /health``.

Every ingested trace goes through the heuristic scorers (``quality.pipeline.ingest_trace``)
so the monitor and the exporter see the same signals as the in-process path."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Response
from prometheus_client import generate_latest
from pydantic import BaseModel, Field

from opsloop import __version__
from opsloop.feedback import build_feedback
from opsloop.monitor.config import MonitorConfig
from opsloop.monitor.exporter import CONTENT_TYPE, Metrics, build_metrics, refresh
from opsloop.monitor.slo import window_summary
from opsloop.quality.pipeline import ingest_trace
from opsloop.sdk.models import Trace
from opsloop.store import TraceStore
from opsloop.timeutil import from_iso, parse_duration


class TraceBatch(BaseModel):
    traces: list[Trace] = Field(default_factory=list)


class FeedbackIn(BaseModel):
    trace_id: str
    ts: float | None = None
    thumbs: Literal["up", "down"] | None = None
    comment: str | None = None
    wrong_part: Literal["numbers", "answer", "tone", "refusal", "format", "other"] | None = None
    regenerated: bool = False
    edited_text: str | None = None


def _parse_ts(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        return from_iso(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"bad timestamp {value!r}") from exc


def create_app(
    store: TraceStore,
    *,
    config: MonitorConfig | None = None,
    metrics: Metrics | None = None,
) -> FastAPI:
    app = FastAPI(title="opsloop collector", version=__version__)
    cfg = config or MonitorConfig()
    m = metrics or build_metrics()

    @app.get("/health")
    def health() -> dict[str, Any]:
        rng = store.time_range()
        return {
            "status": "ok",
            "version": __version__,
            "traces": store.count(),
            "latest_ts": None if rng is None else rng[1],
        }

    @app.post("/v1/traces", status_code=202)
    def ingest(payload: Trace | TraceBatch) -> dict[str, Any]:
        traces = payload.traces if isinstance(payload, TraceBatch) else [payload]
        scored = 0
        for trace in traces:
            if ingest_trace(store, trace) is not None:
                scored += 1
        return {"accepted": len(traces), "scored": scored}

    @app.get("/v1/traces/{trace_id}")
    def get_trace(trace_id: str) -> dict[str, Any]:
        trace = store.get_trace(trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        return {
            **trace.model_dump(mode="json"),
            "feedback": store.feedback_for(trace_id),
            "scores": store.scores_for(trace_id),
        }

    @app.get("/v1/traces")
    def list_traces(
        since: str | None = None,
        until: str | None = None,
        status: str | None = None,
        prompt_version: str | None = None,
        session_id: str | None = None,
        limit: int = Query(default=100, ge=1, le=10_000),
    ) -> dict[str, Any]:
        traces = store.query(
            since=_parse_ts(since),
            until=_parse_ts(until),
            status=status,
            prompt_version=prompt_version,
            session_id=session_id,
            limit=limit,
        )
        return {"count": len(traces), "traces": [t.model_dump(mode="json") for t in traces]}

    @app.get("/v1/stats")
    def stats(window: str = "30m", as_of: str | None = None) -> dict[str, Any]:
        try:
            seconds = parse_duration(window)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        rng = store.time_range()
        if rng is None:
            return {"window": window, "requests": 0}
        anchor = _parse_ts(as_of) or rng[1]
        rows = store.rows(anchor - seconds, anchor + 1e-6)
        return {"window": window, "as_of": anchor, **window_summary(rows)}

    @app.post("/v1/feedback", status_code=201)
    def feedback(payload: FeedbackIn) -> dict[str, Any]:
        trace = store.get_trace(payload.trace_id)
        if trace is None:
            raise HTTPException(status_code=404, detail="trace not found")
        fb = build_feedback(
            payload.trace_id,
            ts=payload.ts if payload.ts is not None else trace.end_ts,
            thumbs=payload.thumbs,
            comment=payload.comment,
            wrong_part=payload.wrong_part,
            regenerated=payload.regenerated,
            original_text=trace.output_text if payload.edited_text is not None else None,
            edited_text=payload.edited_text,
        )
        row_id = store.add_feedback(
            fb.trace_id,
            fb.ts,
            fb.negative,
            fb.model_dump(mode="json", exclude={"trace_id", "ts", "negative"}),
        )
        return {"id": row_id, **fb.model_dump(mode="json")}

    @app.get("/metrics")
    def metrics_endpoint() -> Response:
        refresh(m, store, cfg)
        return Response(content=generate_latest(m.registry), media_type=CONTENT_TYPE)

    return app
