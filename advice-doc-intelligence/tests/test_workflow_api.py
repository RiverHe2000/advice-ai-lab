from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from advicedoc.api import create_app
from advicedoc.classify.model import Prediction
from advicedoc.corpus.generator import load_manifest, records_of_type
from advicedoc.extract import ExtractionResult
from advicedoc.extract.rules import RulesExtractor
from advicedoc.ingest import Document
from advicedoc.logging_utils import REDACTOR, Redactor, configure_logging, log_event
from advicedoc.metrics import NullMetrics, PrometheusMetrics
from advicedoc.route.model import ConstantModel, ReviewRouter
from advicedoc.workflow import (
    InMemoryQueue,
    Job,
    JobStore,
    PipelineDeps,
    PipelineInterruptedError,
    Workflow,
    default_holdings_lookup,
)
from conftest import PrefixClassifier


def _inbox(json_corpus: Path, tmp_path: Path, doc_ids: list[str]) -> Path:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for doc_id in doc_ids:
        doc_type = doc_id.rsplit("_", 1)[0]
        src = json_corpus / doc_type / f"{doc_id}.doc.json"
        shutil.copy(src, inbox / src.name)
        holdings = json_corpus / doc_type / f"{doc_id}.holdings.json"
        if holdings.exists():
            shutil.copy(holdings, inbox / holdings.name)
    return inbox


def _deps(router: ReviewRouter | None = None, **kw: Any) -> PipelineDeps:
    return PipelineDeps(
        classifier=PrefixClassifier(),
        extractor=RulesExtractor(),
        router=router,
        rules_extractor=RulesExtractor() if router else None,
        holdings_lookup=default_holdings_lookup,
        **kw,
    )


# ----- store and queue ----------------------------------------------------------------------


def test_job_store_round_trip(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs.sqlite")
    job = Job(id="j1", source_path="x.pdf")
    store.create(job)
    job.state = "classified"
    job.payload["k"] = {"nested": 1}
    store.save(job)
    loaded = store.get("j1")
    assert (
        loaded is not None and loaded.state == "classified" and loaded.payload["k"]["nested"] == 1
    )
    assert loaded.to_dict()["id"] == "j1" and store.get("missing") is None
    store.log_transition("j1", "received", "classified", started=0.0, ok=True)
    assert store.transitions("j1")[0]["to_state"] == "classified"
    store.add_correction("j1", "reviewer", True, "risk_profile", "Growth", "Balanced")
    assert store.corrections()[0]["field"] == "risk_profile"
    assert [j.id for j in store.list_jobs("classified")] == ["j1"] and store.list_jobs("done") == []
    store.close()


def test_in_memory_queue_dedupes_and_acks() -> None:
    q = InMemoryQueue()
    q.put("a")
    q.put("a")
    q.put("b")
    assert len(q) == 2 and q.get() == "a"
    q.put("a")  # a retry while the first delivery is still in flight is queued once
    q.put("a")
    assert len(q) == 2
    q.ack("a")
    assert q.get() == "b" and q.get() == "a" and q.get() is None
    q.ack("zzz")  # unknown ids are ignored


# ----- pipeline -----------------------------------------------------------------------------


def test_workflow_processes_soa_and_other_types(json_corpus: Path, tmp_path: Path) -> None:
    inbox = _inbox(json_corpus, tmp_path, ["soa_0001", "fds_0001"])
    workflow = Workflow(JobStore(), InMemoryQueue(), _deps())
    jobs = workflow.run_inbox(inbox)
    assert [j.state for j in jobs] == ["done", "done"]
    soa = next(j for j in jobs if j.doc_type == "soa")
    assert soa.payload["reconciliation"] is not None and soa.route == "auto"
    assert soa.payload["routing"]["hard_violations"] == 0
    other = next(j for j in jobs if j.doc_type == "fds")
    assert other.payload["extraction"] is None and other.payload["reconciliation"] is None
    assert other.payload["routing"]["reason"] == "not an SoA"
    transitions = workflow.store.transitions(soa.id)
    assert [t["to_state"] for t in transitions] == [
        "classified",
        "extracted",
        "validated",
        "routed",
        "reconciled",
        "done",
    ]
    assert all(t["duration_ms"] >= 0 for t in transitions)
    summary = workflow.summary()
    assert (
        summary["jobs"] == 2
        and summary["by_type"] == {"soa": 1, "fds": 1}
        and summary["review_rate"] == 0.0
    )
    assert workflow.process_next() is None
    with pytest.raises(KeyError):
        workflow.process("nope")


def test_workflow_resumes_after_a_crash_without_repeating_work(
    json_corpus: Path, tmp_path: Path
) -> None:
    inbox = _inbox(json_corpus, tmp_path, ["soa_0002"])
    store = JobStore(tmp_path / "jobs.sqlite")
    first = Workflow(store, InMemoryQueue(), _deps(), stop_after="extracted")
    job_id = first.submit(next(inbox.glob("*.doc.json")))
    with pytest.raises(PipelineInterruptedError):
        first.process(job_id)
    assert first.store.get(job_id).state == "extracted"  # type: ignore[union-attr]
    assert first.step_runs["classified"] == 1

    second = Workflow(JobStore(tmp_path / "jobs.sqlite"), InMemoryQueue(), _deps())
    assert second.resume() == [job_id]
    done = second.process_next()
    assert done is not None and done.state == "done"
    assert second.step_runs["received"] == 0 and second.step_runs["classified"] == 0
    assert second.step_runs["extracted"] == 1
    assert second.resume() == []


def test_workflow_retries_then_fails(json_corpus: Path, tmp_path: Path) -> None:
    class Boom:
        name = "boom"

        def extract(self, doc: Document) -> ExtractionResult:
            del doc
            raise RuntimeError("model down")

    inbox = _inbox(json_corpus, tmp_path, ["soa_0003"])
    deps = PipelineDeps(classifier=PrefixClassifier(), extractor=Boom())
    workflow = Workflow(JobStore(), InMemoryQueue(), deps, max_retries=1)
    job_id = workflow.submit(next(inbox.glob("*.doc.json")))
    first = workflow.process_next()
    assert first is not None and first.state == "classified" and first.attempts == 1
    assert len(workflow.queue) == 1  # re-enqueued
    second = workflow.process_next()
    assert second is not None and second.state == "failed" and "model down" in (second.error or "")
    assert workflow.process_next() is None
    failed = workflow.store.transitions(job_id)
    assert failed[-1]["ok"] == 0


def test_review_route_and_decision(json_corpus: Path, tmp_path: Path) -> None:
    inbox = _inbox(json_corpus, tmp_path, ["soa_0004"])
    router = ReviewRouter(ConstantModel(0.1), tau=0.5)
    workflow = Workflow(JobStore(), InMemoryQueue(), _deps(router=router))
    jobs = workflow.run_inbox(inbox)
    job = jobs[0]
    assert job.state == "routed" and job.route == "review" and job.awaiting_review
    assert workflow.pending_review()[0].id == job.id
    assert workflow.resume() == []
    with pytest.raises(ValidationError):
        workflow.review_decision(
            job.id, approved=True, reviewer="r", corrections={"risk_profile": "Aggressive"}
        )
    decided = workflow.review_decision(
        job.id, approved=True, reviewer="r", corrections={"risk_profile": "Growth"}
    )
    assert decided.payload["review"]["corrections"] == ["risk_profile"]
    assert workflow.store.corrections()[0]["after"] == '"Growth"'
    done = workflow.process_next()
    assert done is not None and done.state == "done"
    assert done.payload["extraction"]["extraction"]["risk_profile"] == "Growth"
    with pytest.raises(ValueError, match="not awaiting review"):
        workflow.review_decision(job.id, approved=True, reviewer="r")


def test_review_rejection_fails_the_job(json_corpus: Path, tmp_path: Path) -> None:
    inbox = _inbox(json_corpus, tmp_path, ["soa_0005"])
    workflow = Workflow(
        JobStore(), InMemoryQueue(), _deps(router=ReviewRouter(ConstantModel(0.0), tau=0.5))
    )
    job = workflow.run_inbox(inbox)[0]
    rejected = workflow.review_decision(job.id, approved=False, reviewer="r")
    assert rejected.state == "failed" and rejected.error == "rejected by reviewer"
    assert workflow.store.corrections()[0]["field"] == "*"


def test_hard_violations_route_to_review_without_a_router(
    json_corpus: Path, tmp_path: Path
) -> None:
    class Broken(RulesExtractor):
        def extract(self, doc: Document) -> ExtractionResult:
            result = super().extract(doc)
            result.extraction.recommendations[0].product_name = "Zenith Alpha Fund"
            from advicedoc.validate import validate_extraction

            result.violations = validate_extraction(result.extraction)
            return result

    inbox = _inbox(json_corpus, tmp_path, ["soa_0006"])
    deps = PipelineDeps(classifier=PrefixClassifier(), extractor=Broken())
    job = Workflow(JobStore(), InMemoryQueue(), deps).run_inbox(inbox)[0]
    assert job.route == "review" and "hard validator" in job.payload["routing"]["reason"]


def test_default_holdings_lookup(json_corpus: Path) -> None:
    records = records_of_type(load_manifest(json_corpus), "soa")
    path = json_corpus / records[0].pdf_path
    found = default_holdings_lookup(path, Document.from_text(""))
    assert found is not None and found.doc_id == records[0].doc_id
    assert (
        default_holdings_lookup(json_corpus / "fds" / "fds_0001.doc.json", Document.from_text(""))
        is None
    )


# ----- metrics and logging ------------------------------------------------------------------


def test_prometheus_metrics_render() -> None:
    m = PrometheusMetrics()
    m.document_classified("soa")
    m.document_routed("review")
    m.violation("fee_arithmetic")
    m.extraction_latency(0.2)
    text = m.render().decode()
    assert 'advicedoc_documents_total{doc_type="soa"} 1.0' in text
    assert "advicedoc_extraction_latency_seconds_bucket" in text
    null = NullMetrics()
    null.document_classified("x")
    null.document_routed("x")
    null.violation("x")
    null.extraction_latency(1.0)


def test_redactor_masks_pii(capfd: pytest.CaptureFixture[str]) -> None:
    r = Redactor()
    r.register_names(["Alice Oakes"])
    text = r.redact("Alice Oakes <alice@example.com> 0412 345 678 TFN 123 456 782")
    assert "[name]" in text and "[email]" in text and "[phone]" in text and "[tfn]" in text
    configure_logging("INFO")
    REDACTOR.register_names(["Bruno Vance"])
    log = logging.getLogger("advicedoc.test")
    log_event(log, "hello", client="Bruno Vance")
    err = capfd.readouterr().err
    assert "Bruno Vance" not in err and "hello client=[name]" in err


# ----- API ----------------------------------------------------------------------------------


@pytest.fixture
def client(json_corpus: Path, tmp_path: Path) -> TestClient:
    workflow = Workflow(JobStore(), InMemoryQueue(), _deps())
    return TestClient(create_app(workflow, inbox_dir=tmp_path / "api_inbox"))


def test_api_upload_and_job_lifecycle(client: TestClient, json_corpus: Path) -> None:
    assert client.get("/health").json()["status"] == "ok"
    src = json_corpus / "soa" / "soa_0001.doc.json"
    resp = client.post(
        "/documents", files={"file": (src.name, src.read_bytes(), "application/json")}
    )
    assert resp.status_code == 202 and "X-Request-ID" in resp.headers
    job_id = resp.json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["state"] == "done" and job["doc_type"] == "soa" and job["extraction"]["risk_profile"]
    assert client.get("/jobs/nope").status_code == 404
    assert client.get("/summary").json()["jobs"] == 1
    metrics = client.get("/metrics").text
    assert 'advicedoc_documents_total{doc_type="soa"} 1.0' in metrics
    assert (
        client.post(
            "/documents", files={"file": ("x.exe", b"abc", "application/octet-stream")}
        ).status_code
        == 415
    )
    assert (
        client.post("/documents", files={"file": ("x.pdf", b"", "application/pdf")}).status_code
        == 413
    )
    assert client.get("/review").json()["count"] == 0
    assert (
        client.post(f"/review/{job_id}", json={"approved": True, "reviewer": "r"}).status_code
        == 409
    )


def test_api_review_flow(json_corpus: Path, tmp_path: Path) -> None:
    workflow = Workflow(
        JobStore(), InMemoryQueue(), _deps(router=ReviewRouter(ConstantModel(0.0), tau=0.5))
    )
    prom = PrometheusMetrics()
    client = TestClient(create_app(workflow, inbox_dir=tmp_path / "inbox", metrics=prom))
    src = json_corpus / "soa" / "soa_0002.doc.json"
    job_id = client.post(
        "/documents", files={"file": (src.name, src.read_bytes(), "application/json")}
    ).json()["job_id"]
    queue = client.get("/review").json()
    assert queue["count"] == 1 and queue["jobs"][0]["route"] == "review"
    bad = client.post(
        f"/review/{job_id}",
        json={"approved": True, "reviewer": "r", "corrections": {"risk_profile": "Aggressive"}},
    )
    assert bad.status_code == 422
    ok = client.post(
        f"/review/{job_id}",
        json={"approved": True, "reviewer": "r", "corrections": {"risk_profile": "Growth"}},
    )
    assert ok.status_code == 200 and ok.json()["review"]["approved"] is True
    assert client.get(f"/jobs/{job_id}").json()["state"] == "done"
    assert (
        client.post(
            f"/review/{job_id}", json={"approved": True, "reviewer": "r", "extra": 1}
        ).status_code
        == 422
    )


def test_prediction_final_label() -> None:
    assert Prediction("soa", 0.4, {"soa": 0.4}, True).final_label == "unknown"
