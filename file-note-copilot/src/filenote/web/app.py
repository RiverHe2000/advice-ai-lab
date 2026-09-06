"""HTTP surface. Validation at the boundary (Pydantic), stable error codes, a request id on
every response, a Content-Security-Policy that forbids inline script, and the accountability
rule enforced server-side: a note cannot be approved while an unsupported claim remains that
the adviser has not edited or deleted."""

from __future__ import annotations

import difflib
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from filenote import __version__
from filenote.audit import AuditLog
from filenote.config import STRATEGIES, Settings
from filenote.draft import Drafter, DraftError, DraftEvent, build_drafter
from filenote.llm import ChatModel, build_model
from filenote.pii import Pseudonymiser
from filenote.schema import FileNote, Transcript
from filenote.store import DraftStore
from filenote.verify import Verifier
from filenote.web.jobs import Job, JobRegistry

STATIC_DIR = Path(__file__).parent / "static"
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
)


class CreateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1)
    strategy: str | None = None
    meeting_id: str | None = Field(default=None, max_length=64)


class UpdateDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: dict[str, Any]
    editor: str = Field(default="adviser", max_length=120)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approver: str = Field(min_length=1, max_length=120)


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thumbs: Literal["up", "down"]
    comment: str = Field(default="", max_length=2000)
    wrong_claims: list[str] = Field(default_factory=list, max_length=200)


class Metrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.drafts = Counter(
            "filenote_drafts_total", "Drafts by final status", ["status"], registry=self.registry
        )
        self.in_progress = Gauge(
            "filenote_drafts_in_progress",
            "Drafts currently being generated",
            registry=self.registry,
        )
        self.draft_seconds = Histogram(
            "filenote_draft_seconds",
            "Wall-clock seconds per draft",
            registry=self.registry,
            buckets=(0.5, 1, 2, 5, 10, 20, 40, 80, 160),
        )
        self.claims = Counter(
            "filenote_claims_total",
            "Claims in AI drafts by verifier status",
            ["status"],
            registry=self.registry,
        )
        self.approvals = Counter(
            "filenote_approvals_total", "Approved notes", registry=self.registry
        )
        self.blocked = Counter(
            "filenote_approvals_blocked_total",
            "Approval attempts refused because unsupported claims remained",
            registry=self.registry,
        )
        self.feedback = Counter(
            "filenote_feedback_total", "Feedback by thumbs", ["thumbs"], registry=self.registry
        )
        self.edits = Counter("filenote_edits_total", "Adviser edits saved", registry=self.registry)


def note_diff(before: FileNote, after: FileNote) -> tuple[str, int]:
    a = before.to_markdown().splitlines()
    b = after.to_markdown().splitlines()
    diff = list(difflib.unified_diff(a, b, "ai_draft.md", "approved.md", lineterm=""))
    changed = sum(
        1 for line in diff[2:] if line[:1] in "+-" and not line.startswith(("+++", "---"))
    )
    return "\n".join(diff) + ("\n" if diff else ""), changed


def create_app(
    settings: Settings | None = None,
    *,
    model: ChatModel | None = None,
    store: DraftStore | None = None,
    audit: AuditLog | None = None,
    drafter_factory: Callable[[str], Drafter] | None = None,
) -> FastAPI:
    cfg = settings or Settings()
    chat_model = model or build_model(cfg)
    db = store or DraftStore(cfg.db_path)
    log = audit or AuditLog(cfg.audit_path)
    verifier = Verifier(cfg.verifier)
    metrics = Metrics()
    jobs = JobRegistry()

    def make_drafter(strategy: str) -> Drafter:
        if drafter_factory is not None:
            return drafter_factory(strategy)
        return build_drafter(strategy, chat_model, cfg)

    app = FastAPI(title="file-note-copilot", version=__version__)
    app.state.store = db
    app.state.audit = log
    app.state.metrics = metrics
    app.state.jobs = jobs

    @app.middleware("http")
    async def headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    # ----- static front end -----------------------------------------------------------------

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    # ----- operations -------------------------------------------------------------------------

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "model": chat_model.name}

    @app.get("/readyz")
    def readyz() -> dict[str, str]:
        if not chat_model.ready():
            raise HTTPException(status_code=503, detail="model backend not ready")
        return {"status": "ready", "model": chat_model.name}

    @app.get("/metrics", include_in_schema=False)
    def prometheus() -> Response:
        return Response(generate_latest(metrics.registry), media_type=CONTENT_TYPE_LATEST)

    # ----- drafting job -----------------------------------------------------------------------

    def run_job(job: Job, transcript: Transcript, strategy: str) -> None:
        draft_id = job.draft_id
        db.set_status(draft_id, "drafting")
        metrics.in_progress.inc()
        pseud = Pseudonymiser(transcript.attendees) if cfg.pseudonymise else None
        model_input = pseud.transcript(transcript) if pseud is not None else transcript
        job.push("stage", {"stage": "started", "message": f"strategy {strategy}"})

        def progress(ev: DraftEvent) -> None:
            data: dict[str, Any] = {"stage": ev.stage, "message": ev.message}
            if ev.section is not None:
                data["section"] = ev.section
            if ev.payload is not None:
                data.update(ev.payload)
            if ev.stage == "done":
                return
            job.push("partial" if ev.stage == "partial" else "stage", data)

        try:
            with metrics.draft_seconds.time():
                result = make_drafter(strategy).draft(model_input, progress=progress)
        except DraftError as exc:
            db.set_status(draft_id, "failed", error=str(exc))
            metrics.drafts.labels(status="failed").inc()
            metrics.in_progress.dec()
            log.record("draft_failed", draft_id, error=str(exc))
            job.push("error", {"message": str(exc)})
            return
        note = result.note
        if pseud is not None:
            note = pseud.restore_note(note)
            note.meeting.attendees = list(transcript.attendees)
        report = verifier.verify(note, transcript)
        note = verifier.apply(note, report)
        summary = report.summary()
        for status, count in report.counts.items():
            metrics.claims.labels(status=status).inc(count)
        db.add_version(draft_id, note, source="ai", verification=summary)
        db.set_status(draft_id, "done")
        metrics.drafts.labels(status="done").inc()
        metrics.in_progress.dec()
        log.record(
            "draft_done",
            draft_id,
            strategy=strategy,
            model=result.model,
            claims=summary["claims"],
            unsupported=summary["unsupported"],
            model_calls=result.model_calls,
            json_repairs=result.json_repairs,
            latency_s=round(result.latency_s, 3),
            pseudonymised=pseud is not None,
        )
        job.push(
            "done",
            {
                "draft_id": draft_id,
                "note": note.model_dump(mode="json"),
                "verification": summary,
                "unsupported_count": note.unsupported_count(),
            },
        )

    def _start(
        transcript_text: str, strategy: str | None, meeting_id: str | None
    ) -> dict[str, Any]:
        if len(transcript_text) > cfg.web.max_transcript_chars:
            raise HTTPException(status_code=413, detail="transcript too large")
        chosen = strategy or cfg.draft.strategy
        if chosen not in STRATEGIES:
            raise HTTPException(status_code=422, detail=f"unknown strategy {chosen!r}")
        try:
            transcript = Transcript.from_text(transcript_text, meeting_id=meeting_id or "pasted")
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail=f"could not parse transcript: {exc}"
            ) from exc
        draft_id = uuid.uuid4().hex[:12]
        db.create_draft(
            draft_id,
            transcript,
            strategy=chosen,
            model=chat_model.name,
            pseudonymised=cfg.pseudonymise,
        )
        log.record(
            "draft_created",
            draft_id,
            meeting_id=transcript.meeting_id,
            segments=len(transcript.segments),
            strategy=chosen,
            pseudonymised=cfg.pseudonymise,
        )
        job = jobs.create(draft_id)
        jobs.start(job, lambda j: run_job(j, transcript, chosen))
        return {"draft_id": draft_id, "status": "queued", "segments": len(transcript.segments)}

    @app.post("/api/drafts", status_code=202)
    def create_draft(body: CreateDraftRequest) -> dict[str, Any]:
        return _start(body.transcript, body.strategy, body.meeting_id)

    @app.post("/api/drafts/upload", status_code=202)
    async def upload_draft(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI dependency idiom
        strategy: str | None = Form(default=None),
    ) -> dict[str, Any]:
        raw = await file.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=422, detail="file must be UTF-8 text") from exc
        return _start(text, strategy, Path(file.filename or "upload").stem[:64])

    @app.get("/api/drafts/{draft_id}/events")
    def events(draft_id: str, request: Request, last_id: int = 0) -> StreamingResponse:
        job = jobs.get(draft_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        header = request.headers.get("Last-Event-ID")
        after = int(header) if header and header.isdigit() else last_id
        return StreamingResponse(
            job.stream(after=after, heartbeat_s=cfg.web.heartbeat_s),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def _draft_payload(draft_id: str) -> dict[str, Any]:
        record = db.get_draft(draft_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        latest = db.latest_version(draft_id)
        approval = db.approval(draft_id)
        return {
            "draft_id": draft_id,
            "status": record.status,
            "strategy": record.strategy,
            "model": record.model,
            "pseudonymised": record.pseudonymised,
            "error": record.error,
            "transcript": record.transcript.model_dump(mode="json"),
            "version": latest.n if latest else 0,
            "version_source": latest.source if latest else None,
            "note": latest.note.model_dump(mode="json") if latest else None,
            "verification": latest.verification if latest else None,
            "unsupported_count": latest.note.unsupported_count() if latest else 0,
            "approval": approval.model_dump() if approval else None,
            "feedback": [f.model_dump() for f in db.feedback(draft_id)],
        }

    @app.get("/api/drafts/{draft_id}")
    def get_draft(draft_id: str) -> dict[str, Any]:
        return _draft_payload(draft_id)

    @app.get("/api/drafts/{draft_id}/versions")
    def get_versions(draft_id: str) -> dict[str, Any]:
        if db.get_draft(draft_id) is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        return {
            "draft_id": draft_id,
            "versions": [
                {"n": v.n, "source": v.source, "editor": v.editor, "created_at": v.created_at}
                for v in db.versions(draft_id)
            ],
        }

    @app.put("/api/drafts/{draft_id}")
    def update_draft(draft_id: str, body: UpdateDraftRequest) -> dict[str, Any]:
        record = db.get_draft(draft_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        if record.status == "approved":
            raise HTTPException(status_code=409, detail="draft already approved")
        if db.latest_version(draft_id) is None:
            raise HTTPException(status_code=409, detail="draft not ready")
        try:
            note = FileNote.model_validate(
                body.note, context={"segment_ids": set(record.transcript.segment_ids)}
            )
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=exc.errors()[0]["msg"]) from exc
        report = verifier.verify(note, record.transcript)
        note = verifier.apply(note, report)
        version = db.add_version(
            draft_id, note, source="adviser", editor=body.editor, verification=report.summary()
        )
        metrics.edits.inc()
        log.record(
            "draft_edited",
            draft_id,
            editor=body.editor,
            version=version.n,
            unsupported=note.unsupported_count(),
        )
        return _draft_payload(draft_id)

    @app.post("/api/drafts/{draft_id}/approve")
    def approve(draft_id: str, body: ApproveRequest) -> dict[str, Any]:
        record = db.get_draft(draft_id)
        if record is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        if record.status == "approved":
            raise HTTPException(status_code=409, detail="draft already approved")
        latest = db.latest_version(draft_id)
        first = db.first_version(draft_id)
        if latest is None or first is None or record.status != "done":
            raise HTTPException(status_code=409, detail="draft not ready for approval")
        remaining = latest.note.unsupported_count()
        if remaining:
            metrics.blocked.inc()
            log.record("approval_blocked", draft_id, approver=body.approver, unsupported=remaining)
            raise HTTPException(
                status_code=409,
                detail=f"{remaining} unsupported claim(s) must be edited or deleted first",
            )
        diff, changed = note_diff(first.note, latest.note)
        approval = db.approve(
            draft_id, approver=body.approver, version_n=latest.n, diff=diff, changed_lines=changed
        )
        metrics.approvals.inc()
        log.record(
            "approved",
            draft_id,
            approver=body.approver,
            version=latest.n,
            changed_lines=changed,
            diff=diff,
        )
        return {"approval": approval.model_dump(), **_draft_payload(draft_id)}

    @app.post("/api/drafts/{draft_id}/feedback", status_code=201)
    def feedback(draft_id: str, body: FeedbackRequest) -> dict[str, Any]:
        if db.get_draft(draft_id) is None:
            raise HTTPException(status_code=404, detail="unknown draft")
        record = db.add_feedback(
            draft_id, thumbs=body.thumbs, comment=body.comment, wrong_claims=body.wrong_claims
        )
        metrics.feedback.labels(thumbs=body.thumbs).inc()
        log.record(
            "feedback",
            draft_id,
            thumbs=body.thumbs,
            comment=body.comment,
            wrong_claims=body.wrong_claims,
        )
        return record.model_dump()

    @app.get("/api/drafts")
    def list_drafts(limit: int = 50) -> dict[str, Any]:
        return {"drafts": db.list_drafts(limit=max(1, min(limit, 500)))}

    @app.get("/api/drafts/{draft_id}/audit")
    def audit_entries(draft_id: str) -> dict[str, Any]:
        rows = log.entries(draft_id)
        if not rows:
            raise HTTPException(status_code=404, detail="no audit entries")
        return {"draft_id": draft_id, "entries": rows}

    return app
