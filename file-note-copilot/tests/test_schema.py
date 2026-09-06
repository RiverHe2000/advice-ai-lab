from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from filenote.corpus import Meeting
from filenote.schema import (
    ActionItem,
    Claim,
    ComplianceFlags,
    Evidenced,
    FileNote,
    MeetingMeta,
    Segment,
    Transcript,
)


def _meta() -> MeetingMeta:
    return MeetingMeta(date=dt.date(2026, 3, 12), type="annual_review")


def test_claim_requires_evidence() -> None:
    with pytest.raises(ValidationError):
        Claim(text="x", evidence=[])
    with pytest.raises(ValidationError):
        Claim(text="", evidence=["s001"])


def test_note_rejects_unknown_ids_with_context_and_method() -> None:
    data = {
        "meeting": _meta().model_dump(mode="json"),
        "decisions": [{"text": "Client agreed", "evidence": ["s999"]}],
    }
    with pytest.raises(ValidationError, match="unknown segment ids"):
        FileNote.model_validate(data, context={"segment_ids": {"s001"}})
    note = FileNote.model_validate(data)
    assert note.unknown_evidence({"s001"}) == {"s999"}
    transcript = Transcript(
        meeting_id="m", segments=[Segment(id="s001", t=0, speaker="a", text="hello")]
    )
    with pytest.raises(ValueError, match="s999"):
        note.validate_against(transcript)
    note.decisions[0].evidence = ["s001"]
    note.validate_against(transcript)


def test_transcript_rejects_duplicate_ids_and_bad_patterns() -> None:
    seg = Segment(id="s001", t=0, speaker="a", text="x")
    with pytest.raises(ValidationError, match="duplicate"):
        Transcript(meeting_id="m", segments=[seg, seg.model_copy()])
    with pytest.raises(ValidationError):
        Segment(id="x1", t=0, speaker="a", text="x")


def test_transcript_text_round_trip(meeting: Meeting) -> None:
    text = meeting.transcript.to_text()
    parsed = Transcript.from_text(text)
    assert parsed.meeting_id == meeting.transcript.meeting_id
    assert parsed.date == meeting.transcript.date
    assert parsed.type == meeting.transcript.type
    assert parsed.attendees == meeting.transcript.attendees
    assert parsed.segment_ids == meeting.transcript.segment_ids
    assert [s.text for s in parsed.segments] == [s.text for s in meeting.transcript.segments]
    assert [s.role for s in parsed.segments] == [s.role for s in meeting.transcript.segments]
    assert parsed.by_id()["s001"].speaker == meeting.transcript.segments[0].speaker
    assert parsed.role_of(parsed.attendees[0].name) == parsed.attendees[0].role
    assert parsed.role_of("nobody") == "unknown"


def test_transcript_loose_formats() -> None:
    text = "\n".join(
        [
            "[00:12] Sarah Nguyen (adviser): Welcome back.",
            "James Chen: Thanks, good to be here.",
            "Just a bare line of text",
            "[01:02:03] Sarah Nguyen: Let's start.",
        ]
    )
    t = Transcript.from_text(text, meeting_id="pasted")
    assert t.meeting_id == "pasted"
    assert t.segment_ids == ["s001", "s002", "s003", "s004"]
    assert t.segments[0].t == 12.0
    assert t.segments[0].role == "adviser"
    assert t.segments[1].speaker == "James Chen"
    assert t.segments[1].role == "unknown"
    assert t.segments[2].speaker == "unknown"
    assert t.segments[3].t == 3723.0
    assert t.segments[3].role == "adviser"  # learned from the earlier labelled line
    assert {a.name for a in t.attendees} == {"Sarah Nguyen"}
    with pytest.raises(ValueError, match="no segments"):
        Transcript.from_text("\n\n")


def test_windows_and_timestamp() -> None:
    segs = [Segment(id=f"s{i:03d}", t=i * 61.0, speaker="a", text="x") for i in range(1, 8)]
    t = Transcript(meeting_id="m", segments=segs)
    assert [len(w) for w in t.windows(3)] == [3, 3, 1]
    assert [len(w) for w in t.windows(0)] == [1] * 7
    assert segs[6].timestamp == "00:07:07"


def test_iter_claims_sections_and_counts(meeting: Meeting) -> None:
    note = meeting.gold
    sections = {s for s, _, _ in note.iter_claims()}
    assert "decisions" in sections
    assert "action_items" in sections
    assert len(note.all_claims()) == sum(len(note.section_items(s)) for s in sections)
    assert note.unsupported_count() == 0
    note.decisions[0].unsupported = True
    assert note.unsupported_count() == 1
    note.decisions[0].edited = True
    assert note.unsupported_count() == 0


def test_to_markdown_marks_unsupported_and_empty_sections() -> None:
    note = FileNote(
        meeting=_meta(),
        summary="Summary",
        decisions=[Claim(text="Agreed X", evidence=["s001"], unsupported=True)],
        action_items=[
            ActionItem(
                description="Send form", owner="adviser", due=dt.date(2026, 4, 1), evidence=["s002"]
            )
        ],
        compliance=ComplianceFlags(
            risk_profile_confirmed=True,
            risk_profile="Balanced",
            vulnerability_indicators=[Claim(text="Hearing", evidence=["s003"])],
        ),
    )
    md = note.to_markdown()
    assert "[UNSUPPORTED]" in md
    assert "- (none)" in md
    assert "[adviser] Send form due 2026-04-01" in md
    assert "Vulnerability indicator: Hearing" in md
    assert "## Follow-up\n- (none)" in md
    note.meeting.duration_minutes = 45
    note.follow_up = Claim(text="Next review", evidence=["s004"])
    md2 = note.to_markdown()
    assert "Duration: 45 minutes" in md2
    assert "- Next review (s004)" in md2


def test_evidenced_label_abstract() -> None:
    with pytest.raises(NotImplementedError):
        _ = Evidenced(evidence=["s001"]).label
