"""HTTP surface over the workflow: upload, job status, review queue, review decisions,
Prometheus metrics, health. Pydantic validation at the boundary, a request id on every
response, and no client names in log lines (the redactor masks names it has seen)."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from advicedoc import __version__
from advicedoc.metrics import PrometheusMetrics
from advicedoc.workflow import Job, Workflow

MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approved: bool
    reviewer: str = Field(min_length=1, max_length=120)
    corrections: dict[str, Any] | None = None


def _job_view(job: Job, workflow: Workflow) -> dict[str, Any]:
    payload = job.payload
    extraction = payload.get("extraction")
    return {
        "id": job.id,
        "state": job.state,
        "route": job.route,
        "doc_type": job.doc_type,
        "attempts": job.attempts,
        "error": job.error,
        "classification": payload.get("classification"),
        "metadata": payload.get("metadata"),
        "extraction": extraction["extraction"] if extraction else None,
        "violations": payload.get("violations", []),
        "routing": payload.get("routing"),
        "reconciliation": payload.get("reconciliation"),
        "review": payload.get("review"),
        "transitions": workflow.store.transitions(job.id),
    }


def create_app(
    workflow: Workflow, *, inbox_dir: str | Path, metrics: PrometheusMetrics | None = None
) -> FastAPI:
    inbox = Path(inbox_dir)
    inbox.mkdir(parents=True, exist_ok=True)
    prom = metrics or PrometheusMetrics()
    if metrics is None:
        workflow.deps.metrics = prom
    app = FastAPI(title="advicedoc", version=__version__)

    @app.middleware("http")
    async def request_id(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "extractor": workflow.deps.extractor.name}

    @app.post("/documents", status_code=202)
    async def upload(background: BackgroundTasks, file: UploadFile = File(...)) -> dict[str, Any]:  # noqa: B008
        name = Path(file.filename or "upload.pdf").name
        suffix = Path(name).suffix.lower()
        if suffix not in {".pdf", ".json", ".txt"}:
            raise HTTPException(status_code=415, detail="PDF (or text/json for tests) only")
        data = await file.read()
        if not data or len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="empty or too large")
        target = inbox / f"{uuid.uuid4().hex[:8]}_{name}"
        target.write_bytes(data)
        job_id = workflow.submit(target)
        background.add_task(workflow.process_next)
        return {"job_id": job_id, "state": "received"}

    @app.get("/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        found = workflow.store.get(job_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return _job_view(found, workflow)

    @app.get("/review")
    def review_queue() -> dict[str, Any]:
        pending = workflow.pending_review()
        return {"count": len(pending), "jobs": [_job_view(j, workflow) for j in pending]}

    @app.post("/review/{job_id}")
    def review(job_id: str, body: ReviewRequest, background: BackgroundTasks) -> dict[str, Any]:
        try:
            decided = workflow.review_decision(
                job_id, approved=body.approved, reviewer=body.reviewer, corrections=body.corrections
            )
        except ValidationError as exc:  # a patch that breaks the extraction schema
            raise HTTPException(status_code=422, detail=str(exc)[:500]) from exc
        except ValueError as exc:  # not awaiting review
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if body.approved:
            background.add_task(workflow.process_next)
        return _job_view(decided, workflow)

    @app.get("/metrics")
    def metrics_endpoint() -> PlainTextResponse:
        return PlainTextResponse(
            prom.render().decode("utf-8"), media_type="text/plain; version=0.0.4"
        )

    @app.get("/summary")
    def summary() -> dict[str, Any]:
        return workflow.summary()

    return app
