from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from filenote.config import Settings
from filenote.corpus import Meeting
from filenote.draft import DraftError
from filenote.llm import ChatMessage, ScriptedChatModel
from filenote.schema import Transcript
from filenote.web import create_app
from filenote.web.app import note_diff
from filenote.web.jobs import Job
from tests.conftest import read_sse, wait_done


def test_health_ready_index_and_headers(client: TestClient) -> None:
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/readyz").json()["status"] == "ready"
    index = client.get("/")
    assert index.status_code == 200 and "<title>File-note copilot" in index.text
    assert "script-src 'self'" in index.headers["Content-Security-Policy"]
    assert index.headers["X-Content-Type-Options"] == "nosniff"
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/", headers={"X-Request-ID": "abc"}).headers["X-Request-ID"] == "abc"
    assert "on" not in [a.split("=")[0] for a in index.text.split("<") if a.startswith("button on")]


def test_draft_streams_edits_approves_and_records(client: TestClient, meeting: Meeting) -> None:
    created = client.post(
        "/api/drafts", json={"transcript": meeting.transcript.to_text(), "strategy": "verified"}
    )
    assert created.status_code == 202
    draft_id = created.json()["draft_id"]
    frames = read_sse(client, draft_id)
    events = [f["event"] for f in frames if "event" in f]
    assert events[0] == "stage" and events[-1] == "done"
    assert "partial" in events
    ids = [int(f["id"]) for f in frames if "id" in f]
    assert ids == list(range(1, len(ids) + 1))
    done = frames[-1]["data"]
    assert done["unsupported_count"] == 1
    assert done["verification"]["claims"] > 5

    resumed = read_sse(client, draft_id, last_id=ids[-3])
    assert [int(f["id"]) for f in resumed if "id" in f] == ids[-2:]

    payload = client.get(f"/api/drafts/{draft_id}").json()
    assert (
        payload["status"] == "done"
        and payload["version"] == 1
        and payload["unsupported_count"] == 1
    )
    assert client.get(f"/api/drafts/{draft_id}/versions").json()["versions"][0]["source"] == "ai"
    blocked = client.post(f"/api/drafts/{draft_id}/approve", json={"approver": "alice"})
    assert blocked.status_code == 409 and "unsupported" in blocked.json()["detail"]

    note = payload["note"]
    flagged = [i for i, d in enumerate(note["decisions"]) if d["unsupported"]]
    assert len(flagged) == 1
    bad = dict(note)
    bad["decisions"] = [{"text": "x", "evidence": ["s999"]}]
    assert client.put(f"/api/drafts/{draft_id}", json={"note": bad}).status_code == 422
    note["decisions"][flagged[0]]["text"] = (
        "Client agreed to review the invented item (adviser corrected)."
    )
    note["decisions"][flagged[0]]["edited"] = True
    updated = client.put(f"/api/drafts/{draft_id}", json={"note": note, "editor": "alice"})
    assert (
        updated.status_code == 200
        and updated.json()["version"] == 2
        and updated.json()["unsupported_count"] == 0
    )

    approved = client.post(f"/api/drafts/{draft_id}/approve", json={"approver": "alice"})
    assert approved.status_code == 200
    approval = approved.json()["approval"]
    assert (
        approval["approver"] == "alice"
        and approval["version_n"] == 2
        and approval["changed_lines"] >= 1
    )
    assert "--- ai_draft.md" in approval["diff"] and "+" in approval["diff"]
    assert (
        client.post(f"/api/drafts/{draft_id}/approve", json={"approver": "alice"}).status_code
        == 409
    )
    assert client.put(f"/api/drafts/{draft_id}", json={"note": note}).status_code == 409
    assert client.get(f"/api/drafts/{draft_id}").json()["status"] == "approved"

    fb = client.post(
        f"/api/drafts/{draft_id}/feedback",
        json={"thumbs": "down", "comment": "call 0412 345 678", "wrong_claims": ["decisions[0]"]},
    )
    assert fb.status_code == 201 and fb.json()["thumbs"] == "down"
    assert (
        client.get(f"/api/drafts/{draft_id}").json()["feedback"][0]["comment"]
        == "call 0412 345 678"
    )
    audit = client.get(f"/api/drafts/{draft_id}/audit").json()["entries"]
    assert [e["kind"] for e in audit] == [
        "draft_created",
        "draft_done",
        "approval_blocked",
        "draft_edited",
        "approved",
        "feedback",
    ]
    assert audit[-1]["comment"] == "call [PHONE]"
    assert audit[-2]["approver"] == "alice"
    assert client.get("/api/drafts").json()["drafts"][0]["id"] == draft_id

    metrics = client.get("/metrics").text
    assert 'filenote_drafts_total{status="done"} 1.0' in metrics
    assert "filenote_approvals_blocked_total 1.0" in metrics
    assert "filenote_approvals_total 1.0" in metrics
    assert 'filenote_feedback_total{thumbs="down"} 1.0' in metrics
    assert 'filenote_claims_total{status="unsupported"} 1.0' in metrics


def test_upload_and_validation_errors(client: TestClient, meeting: Meeting) -> None:
    up = client.post(
        "/api/drafts/upload",
        files={"file": ("meeting.txt", meeting.transcript.to_text().encode(), "text/plain")},
        data={"strategy": "single_shot"},
    )
    assert up.status_code == 202
    wait_done(client, up.json()["draft_id"])
    assert (
        client.post(
            "/api/drafts/upload", files={"file": ("m.txt", b"\xff\xfe\x00bad", "text/plain")}
        ).status_code
        == 422
    )
    assert (
        client.post("/api/drafts", json={"transcript": "x", "strategy": "magic"}).status_code == 422
    )
    assert client.post("/api/drafts", json={"transcript": ""}).status_code == 422
    assert client.post("/api/drafts", json={"transcript": "a: b", "extra": 1}).status_code == 422
    assert client.post("/api/drafts", json={"transcript": "\n \n"}).status_code == 422
    assert client.get("/api/drafts/nope").status_code == 404
    assert client.get("/api/drafts/nope/events").status_code == 404
    assert client.get("/api/drafts/nope/versions").status_code == 404
    assert client.get("/api/drafts/nope/audit").status_code == 404
    assert client.put("/api/drafts/nope", json={"note": {}}).status_code == 404
    assert client.post("/api/drafts/nope/approve", json={"approver": "a"}).status_code == 404
    assert client.post("/api/drafts/nope/feedback", json={"thumbs": "up"}).status_code == 404


def test_too_large_and_not_ready(settings: Settings, meeting: Meeting) -> None:
    class NotReady(ScriptedChatModel):
        def ready(self) -> bool:
            return False

    small = settings.model_copy(
        update={"web": settings.web.model_copy(update={"max_transcript_chars": 10})}
    )
    app = create_app(small, model=NotReady(default="{}"))
    with TestClient(app) as c:
        assert c.get("/readyz").status_code == 503
        assert (
            c.post("/api/drafts", json={"transcript": meeting.transcript.to_text()}).status_code
            == 413
        )


def test_draft_error_becomes_error_event(settings: Settings, meeting: Meeting) -> None:
    app = create_app(settings, model=ScriptedChatModel(default="not json"))
    with TestClient(app) as c:
        created = c.post(
            "/api/drafts", json={"transcript": "Alice (adviser): hello", "strategy": "single_shot"}
        )
        draft_id = created.json()["draft_id"]
        frames = read_sse(c, draft_id)
        assert frames[-1]["event"] == "error"
        payload = c.get(f"/api/drafts/{draft_id}").json()
        assert payload["status"] == "failed" and payload["error"]
        assert c.post(f"/api/drafts/{draft_id}/approve", json={"approver": "a"}).status_code == 409
        assert c.put(f"/api/drafts/{draft_id}", json={"note": {}}).status_code == 409
        assert 'filenote_drafts_total{status="failed"} 1.0' in c.get("/metrics").text


def test_pseudonymisation_off_and_custom_drafter(meeting: Meeting) -> None:
    calls: list[str] = []

    class Stub:
        strategy = "stub"

        def draft(
            self, transcript: Transcript, *, meeting: Any = None, progress: Any = None
        ) -> Any:
            calls.append(transcript.segments[0].speaker)
            raise DraftError("stub")

    settings = Settings(pseudonymise=False)
    app = create_app(settings, model=ScriptedChatModel(), drafter_factory=lambda s: Stub())
    with TestClient(app) as c:
        did = c.post("/api/drafts", json={"transcript": meeting.transcript.to_text()}).json()[
            "draft_id"
        ]
        read_sse(c, did)
    assert calls == [meeting.transcript.segments[0].speaker]


def test_job_heartbeat_and_note_diff(meeting: Meeting) -> None:
    job = Job("x")
    stream = job.stream(after=0, heartbeat_s=0.05)
    assert next(stream) == ": ping\n\n"
    job.push("stage", {"stage": "s"})
    frame = next(stream)
    assert frame.startswith("id: 1\nevent: stage\n")
    job.push("done", {})
    assert next(stream).startswith("id: 2\nevent: done")
    with pytest.raises(StopIteration):
        next(stream)
    late = job.stream(after=5, heartbeat_s=0.01)
    with pytest.raises(StopIteration):
        next(late)
    edited = meeting.gold.model_copy(deep=True)
    edited.summary = "changed"
    diff, changed = note_diff(meeting.gold, edited)
    assert changed == 2 and "-" in diff
    assert note_diff(meeting.gold, meeting.gold) == ("", 0)


def test_events_are_pushed_while_running(client: TestClient, meeting: Meeting) -> None:
    created = client.post("/api/drafts", json={"transcript": meeting.transcript.to_text()})
    draft_id = created.json()["draft_id"]
    deadline = time.time() + 10
    while time.time() < deadline:
        if client.get(f"/api/drafts/{draft_id}").json()["status"] == "done":
            break
        time.sleep(0.02)
    frames = read_sse(client, draft_id)
    assert frames[-1]["event"] == "done"
    assert ChatMessage("user", "x").role == "user"
