"""SQLite store queries, signals, feedback, scores, retention and export; the collector API."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsloop.collector.api import create_app
from opsloop.monitor.config import MonitorConfig
from opsloop.store import Signals, TraceStore
from opsloop.timeutil import DEMO_EPOCH


def test_store_insert_get_query_rows(make_trace, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    store = TraceStore(tmp_path / "db" / "t.sqlite")
    t1 = make_trace("a", start=DEMO_EPOCH)
    t2 = make_trace(
        "b",
        start=DEMO_EPOCH + 60,
        status="error",
        error_class="timeout",
        prompt_version="v2",
        session_id="s2",
    )
    store.insert_trace(t1, Signals(0.9, False, None, False, True))
    store.insert_trace(t2)
    assert store.count() == 2 and store.time_range() == (DEMO_EPOCH, t2.end_ts)
    got = store.get_trace("a")
    assert got is not None and got.spans[0].attributes["tool.output"]["total_balance"] == 123456.78
    assert store.get_trace("missing") is None
    assert [t.trace_id for t in store.query(status="error")] == ["b"]
    assert [t.trace_id for t in store.query(prompt_version="v2")] == ["b"]
    assert [t.trace_id for t in store.query(session_id="s1")] == ["a"]
    assert [t.trace_id for t in store.query(since=DEMO_EPOCH + 30, until=DEMO_EPOCH + 120)] == ["b"]
    assert len(store.query(limit=1)) == 1
    rows = store.rows()
    assert rows[0].quality == 0.9 and rows[0].grounded is True and rows[0].json_valid is None
    assert (
        rows[1].status == "error" and rows[1].error_class == "timeout" and rows[1].quality is None
    )
    assert store.span_errors(DEMO_EPOCH, DEMO_EPOCH + 3600)[0].name == "chat"
    store.update_signals("b", Signals(0.1, True, False, True, False))
    row = store.rows(status="error")[0]
    assert row.refusal is True and row.json_valid is False and row.pii_leak is True
    store.close()


def test_store_feedback_scores_prune_export(make_trace, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    store = TraceStore(":memory:")
    for i in range(5):
        store.insert_trace(make_trace(f"t{i}", start=DEMO_EPOCH + i * 3600))
    fid = store.add_feedback("t1", DEMO_EPOCH, True, {"thumbs": "down"})
    assert fid >= 1 and store.feedback_for("t1")[0]["thumbs"] == "down"
    assert store.rows(session_id="s1")[1].negative_feedback is True
    store.add_score(
        "t2",
        scorer="judge",
        model="j",
        prompt_version="judge-v1",
        ts=1.0,
        missing=False,
        repairs=1,
        payload={"mean": 4.0},
        judge_mean=4.0,
    )
    store.add_score(
        "t3",
        scorer="judge",
        model="j",
        prompt_version="judge-v1",
        ts=1.0,
        missing=True,
        repairs=0,
        payload={},
    )
    assert store.scores_for("t2")[0]["mean"] == 4.0 and store.judged_ids() == {"t2", "t3"}
    assert store.rows()[2].judge == 4.0 and store.rows()[3].judge is None
    n = store.export_jsonl(tmp_path / "x" / "export.jsonl", since=DEMO_EPOCH + 3600)
    lines = (tmp_path / "x" / "export.jsonl").read_text(encoding="utf-8").splitlines()
    assert n == 4 and json.loads(lines[0])["feedback"][0]["negative"] is True
    removed = store.prune(DEMO_EPOCH + 2 * 3600)
    assert removed == 2 and store.count() == 3 and store.feedback_for("t1") == []
    assert store.prune(0.0) == 0
    store.close()


def test_store_empty_time_range() -> None:
    assert TraceStore(":memory:").time_range() is None


@pytest.fixture
def client(config: MonitorConfig) -> TestClient:
    return TestClient(create_app(TraceStore(":memory:"), config=config))


def test_collector_ingest_get_list_stats(client: TestClient, make_trace) -> None:  # type: ignore[no-untyped-def]
    assert client.get("/health").json()["traces"] == 0
    r = client.post("/v1/traces", json=make_trace("c1").model_dump(mode="json"))
    assert r.status_code == 202 and r.json() == {"accepted": 1, "scored": 1}
    batch = {
        "traces": [
            make_trace("c2", start=DEMO_EPOCH + 60).model_dump(mode="json"),
            make_trace(
                "c3", start=DEMO_EPOCH + 120, status="error", error_class="timeout"
            ).model_dump(mode="json"),
        ]
    }
    assert client.post("/v1/traces", json=batch).json() == {"accepted": 2, "scored": 1}
    got = client.get("/v1/traces/c1").json()
    assert got["trace_id"] == "c1" and got["feedback"] == [] and got["scores"] == []
    assert client.get("/v1/traces/none").status_code == 404
    listed = client.get("/v1/traces", params={"status": "error"}).json()
    assert listed["count"] == 1 and listed["traces"][0]["trace_id"] == "c3"
    since = client.get("/v1/traces", params={"since": "2026-09-01T00:00:30Z", "limit": 5}).json()
    assert since["count"] == 2
    assert client.get("/v1/traces", params={"since": "garbage"}).status_code == 400
    stats = client.get("/v1/stats", params={"window": "1h"}).json()
    assert stats["requests"] == 3 and stats["errors"] == 1 and stats["grounding_rate"] == 1.0
    assert stats["by_prompt_version"] == {"v1": 3}
    assert client.get("/v1/stats", params={"window": "bad"}).status_code == 400
    metrics = client.get("/metrics").text
    assert "opsloop_error_rate" in metrics and "opsloop_slo_burn_rate" in metrics
    assert client.get("/health").json()["latest_ts"] is not None


def test_collector_stats_on_empty_store(client: TestClient) -> None:
    assert client.get("/v1/stats").json() == {"window": "30m", "requests": 0}
    assert "opsloop_store_traces_total 0.0" in client.get("/metrics").text


def test_collector_feedback(client: TestClient, make_trace) -> None:  # type: ignore[no-untyped-def]
    client.post("/v1/traces", json=make_trace("f1").model_dump(mode="json"))
    assert client.post("/v1/feedback", json={"trace_id": "nope"}).status_code == 404
    r = client.post(
        "/v1/feedback", json={"trace_id": "f1", "thumbs": "down", "wrong_part": "numbers"}
    )
    assert (
        r.status_code == 201
        and r.json()["negative"] is True
        and "thumbs_down" in r.json()["reasons"]
    )
    edited = client.post(
        "/v1/feedback",
        json={
            "trace_id": "f1",
            "edited_text": "Completely different answer with new numbers 1 2 3.",
        },
    ).json()
    assert (
        edited["edit_ratio"] is not None
        and edited["edit_ratio"] > 0.3
        and edited["negative"] is True
    )
    positive = client.post(
        "/v1/feedback", json={"trace_id": "f1", "thumbs": "up", "ts": 5.0}
    ).json()
    assert positive["negative"] is False and positive["ts"] == 5.0
    assert len(client.get("/v1/traces/f1").json()["feedback"]) == 3
