from __future__ import annotations

from pathlib import Path

from filenote.audit import AuditLog
from filenote.corpus import Meeting
from filenote.store import DraftStore


def test_store_lifecycle(tmp_path: Path, meeting: Meeting) -> None:
    store = DraftStore(tmp_path / "db" / "drafts.sqlite")
    record = store.create_draft(
        "d1", meeting.transcript, strategy="verified", model="fake", pseudonymised=True
    )
    assert record.status == "queued" and record.pseudonymised and record.meeting_id == meeting.id
    assert store.get_draft("nope") is None
    assert store.latest_version("d1") is None and store.first_version("d1") is None
    store.set_status("d1", "drafting")
    v1 = store.add_version("d1", meeting.gold, source="ai", verification={"claims": 3})
    assert v1.n == 1 and v1.verification == {"claims": 3}
    edited = meeting.gold.model_copy(deep=True)
    edited.summary = "edited"
    v2 = store.add_version("d1", edited, source="adviser", editor="alice")
    assert v2.n == 2 and v2.editor == "alice" and v2.verification is None
    assert [v.n for v in store.versions("d1")] == [1, 2]
    latest = store.latest_version("d1")
    assert latest is not None and latest.note.summary == "edited"
    first = store.first_version("d1")
    assert first is not None and first.source == "ai"
    store.set_status("d1", "done")
    assert store.approval("d1") is None
    approval = store.approve(
        "d1", approver="alice", version_n=2, diff="--- a\n+++ b\n", changed_lines=1
    )
    assert approval.approver == "alice"
    assert store.get_draft("d1") is not None and store.get_draft("d1").status == "approved"  # type: ignore[union-attr]
    assert store.approval("d1") == approval
    fb = store.add_feedback(
        "d1", thumbs="down", comment="wrong owner", wrong_claims=["action_items[0]"]
    )
    assert fb.id >= 1
    assert [f.thumbs for f in store.feedback("d1")] == ["down"]
    assert store.feedback("none") == []
    listing = store.list_drafts()
    assert listing[0]["id"] == "d1" and listing[0]["status"] == "approved"
    store.set_status("d1", "failed", error="boom")
    assert store.get_draft("d1").error == "boom"  # type: ignore[union-attr]
    store.close()
    memory = DraftStore()
    assert memory.list_drafts() == []


def test_audit_redacts_and_exports(tmp_path: Path) -> None:
    path = tmp_path / "audit" / "trail.jsonl"
    log = AuditLog(path)
    assert log.path == path
    entry = log.record(
        "feedback",
        "d1",
        approver="alice 0412 345 678",
        comment="ring 0412 345 678",
        tfn="123 456 782",
    )
    assert entry["approver"] == "alice 0412 345 678"
    assert entry["comment"] == "ring [PHONE]"
    assert entry["tfn"] == "[TFN]"
    log.record("approved", "d2", approver="bob")
    assert [e["kind"] for e in log.entries()] == ["feedback", "approved"]
    assert len(log.entries("d1")) == 1
    out = tmp_path / "export" / "d1.jsonl"
    assert log.export(out, draft_id="d1") == 1
    assert "[PHONE]" in out.read_text(encoding="utf-8")
    assert "0412 345 678" not in out.read_text(encoding="utf-8").split("approver")[0]
    timeline = log.timeline("d2")
    assert timeline.startswith("# draft d2") and "approved" in timeline


def test_audit_in_memory_and_missing_file(tmp_path: Path) -> None:
    mem = AuditLog()
    mem.record("x", "d")
    assert len(mem.entries()) == 1
    assert mem.path is None
    missing = AuditLog(tmp_path / "nope.jsonl")
    assert missing.entries() == []
    assert missing.export(tmp_path / "out.jsonl") == 0
