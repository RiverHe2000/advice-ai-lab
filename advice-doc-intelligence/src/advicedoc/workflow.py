"""Durable document workflow: a SQLite job table with the states ``received -> classified
-> extracted -> validated -> routed(review|auto) -> reconciled -> done | failed``.

Every step is idempotent (it checks the job payload before doing work) and resumable (a new
``Workflow`` over the same store picks up where the last one stopped); failures are retried
up to a cap; every transition is logged with timestamps and durations; a ``QueueBackend``
protocol with an in-memory implementation is the seam where a Pub/Sub adapter would plug in.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, Protocol

from advicedoc.classify.metadata import extract_metadata
from advicedoc.classify.model import Prediction
from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.extract import ExtractionResult, Extractor
from advicedoc.ingest import Document, load_document
from advicedoc.logging_utils import REDACTOR, log_event
from advicedoc.metrics import MetricsSink, NullMetrics
from advicedoc.reconcile import reconcile
from advicedoc.route.features import field_records
from advicedoc.route.model import ReviewRouter
from advicedoc.schema import HoldingsSnapshot, SoAExtraction
from advicedoc.validate import Violation

log = logging.getLogger("advicedoc.workflow")

JobState = Literal[
    "received", "classified", "extracted", "validated", "routed", "reconciled", "done", "failed"
]
STATES: tuple[JobState, ...] = (
    "received",
    "classified",
    "extracted",
    "validated",
    "routed",
    "reconciled",
    "done",
    "failed",
)
TERMINAL: frozenset[str] = frozenset({"done", "failed"})


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


@dataclass(slots=True)
class Job:
    id: str
    source_path: str
    state: JobState = "received"
    attempts: int = 0
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    doc_type: str | None = None
    route: str | None = None
    error: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def awaiting_review(self) -> bool:
        return self.state == "routed" and self.route == "review" and "review" not in self.payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_path": self.source_path,
            "state": self.state,
            "attempts": self.attempts,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "doc_type": self.doc_type,
            "route": self.route,
            "error": self.error,
            "payload": self.payload,
        }


class JobStore:
    """SQLite persistence for jobs, transitions and reviewer corrections."""

    def __init__(self, path: str | Path = ":memory:") -> None:
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY, source_path TEXT NOT NULL, state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL, doc_type TEXT, route TEXT, error TEXT,
                payload TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE IF NOT EXISTS transitions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                from_state TEXT NOT NULL, to_state TEXT NOT NULL, started_at TEXT NOT NULL,
                ended_at TEXT NOT NULL, duration_ms REAL NOT NULL, ok INTEGER NOT NULL,
                message TEXT
            );
            CREATE TABLE IF NOT EXISTS corrections (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT NOT NULL,
                reviewer TEXT NOT NULL, approved INTEGER NOT NULL, field TEXT NOT NULL,
                before TEXT, after TEXT, created_at TEXT NOT NULL
            );
            """
        )

    def close(self) -> None:
        self._conn.close()

    def create(self, job: Job) -> None:
        self._conn.execute(
            "INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                job.id,
                job.source_path,
                job.state,
                job.attempts,
                job.created_at,
                job.updated_at,
                job.doc_type,
                job.route,
                job.error,
                json.dumps(job.payload, default=str),
            ),
        )
        self._conn.commit()

    def save(self, job: Job) -> None:
        job.updated_at = _now()
        self._conn.execute(
            "UPDATE jobs SET state=?, attempts=?, updated_at=?, doc_type=?, route=?, error=?, "
            "payload=? WHERE id=?",
            (
                job.state,
                job.attempts,
                job.updated_at,
                job.doc_type,
                job.route,
                job.error,
                json.dumps(job.payload, default=str),
                job.id,
            ),
        )
        self._conn.commit()

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> Job:
        return Job(
            id=row["id"],
            source_path=row["source_path"],
            state=row["state"],
            attempts=row["attempts"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            doc_type=row["doc_type"],
            route=row["route"],
            error=row["error"],
            payload=json.loads(row["payload"]),
        )

    def get(self, job_id: str) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_jobs(self, state: JobState | None = None) -> list[Job]:
        if state is None:
            rows = self._conn.execute("SELECT * FROM jobs ORDER BY created_at").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY created_at", (state,)
            ).fetchall()
        return [self._row_to_job(r) for r in rows]

    def log_transition(
        self,
        job_id: str,
        from_state: str,
        to_state: str,
        *,
        started: float,
        ok: bool,
        message: str | None = None,
    ) -> None:
        ended = time.perf_counter()
        self._conn.execute(
            "INSERT INTO transitions (job_id, from_state, to_state, started_at, ended_at, "
            "duration_ms, ok, message) VALUES (?,?,?,?,?,?,?,?)",
            (
                job_id,
                from_state,
                to_state,
                _now(),
                _now(),
                (ended - started) * 1000.0,
                int(ok),
                message,
            ),
        )
        self._conn.commit()

    def transitions(self, job_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM transitions WHERE job_id=? ORDER BY seq", (job_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def add_correction(
        self, job_id: str, reviewer: str, approved: bool, field_name: str, before: Any, after: Any
    ) -> None:
        self._conn.execute(
            "INSERT INTO corrections (job_id, reviewer, approved, field, before, after, "
            "created_at) VALUES (?,?,?,?,?,?,?)",
            (
                job_id,
                reviewer,
                int(approved),
                field_name,
                json.dumps(before, default=str),
                json.dumps(after, default=str),
                _now(),
            ),
        )
        self._conn.commit()

    def corrections(self) -> list[dict[str, Any]]:
        rows = self._conn.execute("SELECT * FROM corrections ORDER BY seq").fetchall()
        return [dict(r) for r in rows]


# ----- queue --------------------------------------------------------------------------------


class QueueBackend(Protocol):
    """Where a Pub/Sub adapter would plug in: ``put`` publishes a job id, ``get`` pulls the
    next one, ``ack`` acknowledges it."""

    def put(self, job_id: str) -> None: ...

    def get(self) -> str | None: ...

    def ack(self, job_id: str) -> None: ...

    def __len__(self) -> int: ...


class InMemoryQueue:
    def __init__(self) -> None:
        self._items: deque[str] = deque()
        self._inflight: set[str] = set()

    def put(self, job_id: str) -> None:
        if job_id not in self._items:
            self._items.append(job_id)

    def get(self) -> str | None:
        if not self._items:
            return None
        job_id = self._items.popleft()
        self._inflight.add(job_id)
        return job_id

    def ack(self, job_id: str) -> None:
        self._inflight.discard(job_id)

    def __len__(self) -> int:
        return len(self._items)


# ----- pipeline -----------------------------------------------------------------------------


class Classifier(Protocol):
    def predict_one(self, doc: Document) -> Prediction: ...


HoldingsLookup = Callable[[Path, Document], HoldingsSnapshot | None]
DocumentLoader = Callable[[Path], Document]


class PipelineInterruptedError(RuntimeError):
    """Raised by the test hook that simulates a crash after a given state."""


@dataclass(slots=True)
class PipelineDeps:
    classifier: Classifier
    extractor: Extractor
    router: ReviewRouter | None = None
    rules_extractor: Extractor | None = None
    tau: float = 0.5
    master: ProductMaster = DEFAULT_MASTER
    holdings_lookup: HoldingsLookup | None = None
    loader: DocumentLoader = load_document
    metrics: MetricsSink = field(default_factory=NullMetrics)


def default_holdings_lookup(path: Path, doc: Document) -> HoldingsSnapshot | None:
    """``<stem>.holdings.json`` next to the document."""
    del doc
    stem = path.name.split(".")[0]
    candidate = path.with_name(f"{stem}.holdings.json")
    if candidate.exists():
        return HoldingsSnapshot.model_validate_json(candidate.read_text(encoding="utf-8"))
    return None


class Workflow:
    def __init__(
        self,
        store: JobStore,
        queue: QueueBackend,
        deps: PipelineDeps,
        *,
        max_retries: int = 2,
        stop_after: JobState | None = None,
    ) -> None:
        self.store = store
        self.queue = queue
        self.deps = deps
        self.max_retries = max_retries
        self.stop_after = stop_after
        self.step_runs: dict[str, int] = dict.fromkeys(STATES, 0)
        self._docs: dict[str, Document] = {}

    # ----- submission -----------------------------------------------------------------------

    def submit(self, path: str | Path) -> str:
        job = Job(id=uuid.uuid4().hex[:12], source_path=str(path))
        self.store.create(job)
        self.queue.put(job.id)
        log_event(log, "job_received", job=job.id)
        return job.id

    def resume(self) -> list[str]:
        """Re-enqueue every job that is neither terminal nor waiting for a reviewer."""
        ids: list[str] = []
        for job in self.store.list_jobs():
            if job.state in TERMINAL or job.awaiting_review:
                continue
            self.queue.put(job.id)
            ids.append(job.id)
        return ids

    def process_next(self) -> Job | None:
        job_id = self.queue.get()
        if job_id is None:
            return None
        try:
            return self.process(job_id)
        finally:
            self.queue.ack(job_id)

    def run_inbox(self, inbox: str | Path, *, pattern: str = "*.pdf") -> list[Job]:
        paths = sorted(Path(inbox).glob(pattern)) + sorted(Path(inbox).glob("*.doc.json"))
        for p in paths:
            self.submit(p)
        jobs: list[Job] = []
        while True:
            job = self.process_next()
            if job is None:
                break
            jobs.append(job)
        return jobs

    # ----- processing -----------------------------------------------------------------------

    def _document(self, job: Job) -> Document:
        if job.id not in self._docs:
            self._docs[job.id] = self.deps.loader(Path(job.source_path))
        return self._docs[job.id]

    def process(self, job_id: str) -> Job:
        job = self.store.get(job_id)
        if job is None:
            msg = f"unknown job {job_id}"
            raise KeyError(msg)
        while job.state not in TERMINAL and not job.awaiting_review:
            from_state = job.state
            started = time.perf_counter()
            try:
                self._step(job)
            except PipelineInterruptedError:
                raise
            except Exception as exc:
                job.attempts += 1
                job.error = f"{type(exc).__name__}: {exc}"
                failed = job.attempts > self.max_retries
                if failed:
                    job.state = "failed"
                self.store.save(job)
                self.store.log_transition(
                    job.id, from_state, job.state, started=started, ok=False, message=job.error
                )
                log_event(
                    log,
                    "step_failed",
                    job=job.id,
                    state=from_state,
                    attempts=job.attempts,
                    failed=failed,
                )
                if not failed:
                    self.queue.put(job.id)
                return job
            self.store.save(job)
            self.store.log_transition(job.id, from_state, job.state, started=started, ok=True)
            log_event(log, "transition", job=job.id, **{"from": from_state, "to": job.state})
            if self.stop_after is not None and job.state == self.stop_after:
                raise PipelineInterruptedError(job.state)
        return job

    def _step(self, job: Job) -> None:
        self.step_runs[job.state] += 1
        if job.state == "received":
            self._classify(job)
        elif job.state == "classified":
            self._extract(job)
        elif job.state == "extracted":
            self._validate(job)
        elif job.state == "validated":
            self._route(job)
        elif job.state == "routed":
            self._reconcile(job)
        elif job.state == "reconciled":
            job.state = "done"

    def _classify(self, job: Job) -> None:
        if "classification" not in job.payload:
            doc = self._document(job)
            pred = self.deps.classifier.predict_one(doc)
            meta = extract_metadata(doc)
            REDACTOR.register_names(meta.client_names)
            job.doc_type = pred.final_label
            job.payload["classification"] = {
                "label": pred.label,
                "confidence": pred.confidence,
                "abstained": pred.abstained,
                "final_label": pred.final_label,
            }
            job.payload["metadata"] = {
                "client_names": meta.client_names,
                "adviser_name": meta.adviser_name,
                "document_date": meta.document_date.isoformat() if meta.document_date else None,
            }
            self.deps.metrics.document_classified(pred.final_label)
        job.state = "classified"

    def _extract(self, job: Job) -> None:
        if "extraction" not in job.payload:
            if job.doc_type == "soa":
                doc = self._document(job)
                result = self.deps.extractor.extract(doc)
                job.payload["extraction"] = result.to_dict()
                self.deps.metrics.extraction_latency(result.latency_s)
                if self.deps.rules_extractor is not None and self.deps.router is not None:
                    rules = self.deps.rules_extractor.extract(doc)
                    job.payload["rules_extraction"] = rules.to_dict()
            else:
                job.payload["extraction"] = None
        job.state = "extracted"

    def _validate(self, job: Job) -> None:
        if "violations" not in job.payload:
            extraction = job.payload.get("extraction")
            violations = extraction["violations"] if extraction else []
            job.payload["violations"] = violations
            for v in violations:
                self.deps.metrics.violation(str(v["code"]))
        job.state = "validated"

    def _route(self, job: Job) -> None:
        if job.route is None:
            extraction = job.payload.get("extraction")
            if extraction is None:
                job.route = "auto"
                job.payload["routing"] = {"reason": "not an SoA"}
            else:
                hard = [v for v in job.payload["violations"] if v["severity"] == "error"]
                score: float | None = None
                if self.deps.router is not None:
                    primary = _result_from_payload(extraction)
                    rules_payload = job.payload.get("rules_extraction")
                    rules = _result_from_payload(rules_payload) if rules_payload else None
                    records = field_records(primary, rules)
                    score = self.deps.router.doc_scores(records).get(primary.doc_id, 1.0)
                    job.route = "review" if score < self.deps.tau else "auto"
                    reason = f"min P(correct)={score:.3f} vs tau={self.deps.tau}"
                else:
                    job.route = "review" if hard else "auto"
                    reason = (
                        f"{len(hard)} hard validator violations" if hard else "no hard violations"
                    )
                job.payload["routing"] = {
                    "reason": reason,
                    "min_p_correct": score,
                    "hard_violations": len(hard),
                }
            self.deps.metrics.document_routed(job.route)
        job.state = "routed"

    def _reconcile(self, job: Job) -> None:
        if "reconciliation" not in job.payload:
            extraction = job.payload.get("extraction")
            holdings = None
            if extraction is not None and self.deps.holdings_lookup is not None:
                holdings = self.deps.holdings_lookup(Path(job.source_path), self._document(job))
            if extraction is None or holdings is None:
                job.payload["reconciliation"] = None
            else:
                report = reconcile(
                    SoAExtraction.model_validate(extraction["extraction"]),
                    holdings,
                    master=self.deps.master,
                )
                job.payload["reconciliation"] = report.to_dict()
        job.state = "reconciled"

    # ----- review ---------------------------------------------------------------------------

    def pending_review(self) -> list[Job]:
        return [j for j in self.store.list_jobs("routed") if j.awaiting_review]

    def review_decision(
        self,
        job_id: str,
        *,
        approved: bool,
        reviewer: str,
        corrections: dict[str, Any] | None = None,
    ) -> Job:
        """Approve or correct an extraction. Corrections are a flat ``{field: value}`` patch
        applied to the extraction and stored as labelled examples for retraining the router."""
        job = self.store.get(job_id)
        if job is None or not job.awaiting_review:
            msg = f"job {job_id} is not awaiting review"
            raise ValueError(msg)
        extraction = job.payload["extraction"]["extraction"]
        patched = {**extraction, **(corrections or {})}
        SoAExtraction.model_validate(patched)  # a bad patch is rejected before anything is stored
        for field_name, value in (corrections or {}).items():
            self.store.add_correction(
                job.id, reviewer, approved, field_name, extraction.get(field_name), value
            )
            extraction[field_name] = value
        if not corrections:
            self.store.add_correction(job.id, reviewer, approved, "*", None, None)
        job.payload["review"] = {
            "approved": approved,
            "reviewer": reviewer,
            "corrections": list((corrections or {}).keys()),
            "decided_at": _now(),
        }
        if not approved:
            job.state = "failed"
            job.error = "rejected by reviewer"
        self.store.save(job)
        if approved:
            self.queue.put(job.id)
        log_event(log, "review_decided", job=job.id, approved=approved)
        return job

    # ----- reporting ------------------------------------------------------------------------

    def summary(self) -> dict[str, Any]:
        jobs = self.store.list_jobs()
        by_state: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for j in jobs:
            by_state[j.state] = by_state.get(j.state, 0) + 1
            if j.doc_type:
                by_type[j.doc_type] = by_type.get(j.doc_type, 0) + 1
        routed = [j for j in jobs if j.route is not None]
        return {
            "jobs": len(jobs),
            "by_state": by_state,
            "by_type": by_type,
            "review_rate": (sum(1 for j in routed if j.route == "review") / len(routed))
            if routed
            else 0.0,
        }


def _result_from_payload(payload: dict[str, Any]) -> ExtractionResult:
    return ExtractionResult(
        strategy=str(payload["strategy"]),
        doc_id=str(payload["doc_id"]),
        extraction=SoAExtraction.model_validate(payload["extraction"]),
        sections_found=dict(payload.get("sections_found", {})),
        missing=dict(payload.get("missing", {})),
        violations=[Violation(**v) for v in payload.get("violations", [])],
        repairs=int(payload.get("repairs", 0)),
        parse_failures=int(payload.get("parse_failures", 0)),
        retries=int(payload.get("retries", 0)),
        field_confidence={k: float(v) for k, v in payload.get("field_confidence", {}).items()},
        product_scores={k: float(v) for k, v in payload.get("product_scores", {}).items()},
    )
