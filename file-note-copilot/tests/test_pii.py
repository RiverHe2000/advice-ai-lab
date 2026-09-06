from __future__ import annotations

import random

import pytest

from filenote.corpus import Meeting
from filenote.pii import Pseudonymiser, detect, make_tfn, redact, redact_any, tfn_valid
from filenote.schema import Attendee, Claim, FileNote


def test_tfn_checksum() -> None:
    assert tfn_valid("123 456 782")
    assert not tfn_valid("123 456 789")
    assert not tfn_valid("12345678")
    rng = random.Random(0)
    for _ in range(20):
        assert tfn_valid(make_tfn(rng))


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("my TFN is 123 456 782 ok", "TFN"),
        ("call me on 0412 345 678", "PHONE"),
        ("or +61 2 9876 5432", "PHONE"),
        ("mail james.chen@example.com", "EMAIL"),
        ("I was born on 3 May 1971", "DOB"),
        ("date of birth: 03/05/1971", "DOB"),
        ("DOB 1971-05-03", "DOB"),
        ("we moved to 14 Wattle Street, Ryde NSW 2112", "ADDRESS"),
        ("new address 7/22 Banksia Road Camberwell", "ADDRESS"),
    ],
)
def test_detect_kinds(text: str, kind: str) -> None:
    kinds = [m.kind for m in detect(text)]
    assert kind in kinds
    redacted, matches = redact(text)
    assert f"[{kind}]" in redacted
    assert matches


def test_redact_leaves_balances_alone() -> None:
    text = "balance $850,000 and 123 456 789 is not a TFN; 2035 is a year"
    assert redact(text) == (text, [])
    assert detect("nothing") == []


def test_redact_any_preserves_staff_identity() -> None:
    payload = {
        "approver": "alice@northshore 0412 345 678",
        "comment": "call 0412 345 678",
        "items": ["mail a@b.com", 3, None],
        "nested": {"tfn": "123 456 782"},
    }
    out = redact_any(payload)
    assert out["approver"] == payload["approver"]
    assert out["comment"] == "call [PHONE]"
    assert out["items"] == ["mail [EMAIL]", 3, None]
    assert out["nested"]["tfn"] == "[TFN]"


def test_pseudonymiser_round_trip(meeting: Meeting) -> None:
    pseud = Pseudonymiser(meeting.transcript.attendees)
    mapping = pseud.mapping
    assert set(mapping.values()) >= {"ADVISER"}
    assert any(v.startswith("CLIENT") for v in mapping.values())
    t2 = pseud.transcript(meeting.transcript)
    joined = " ".join(s.text + " " + s.speaker for s in t2.segments)
    for name in mapping:
        assert name not in joined
        assert name.split()[0] not in joined.split()
    assert [s.id for s in t2.segments] == meeting.transcript.segment_ids
    assert [a.role for a in t2.attendees] == [a.role for a in meeting.transcript.attendees]
    restored = pseud.restore_note(meeting.gold)
    assert restored == meeting.gold
    pseudonymised_note = FileNote.model_validate(
        {
            **meeting.gold.model_dump(mode="json"),
            "summary": pseud.apply(meeting.gold.summary),
            "circumstance_changes": [
                {"text": pseud.apply(c.text), "evidence": c.evidence}
                for c in meeting.gold.circumstance_changes
            ],
        }
    )
    back = pseud.restore_note(pseudonymised_note)
    assert back.summary == meeting.gold.summary
    assert [c.text for c in back.circumstance_changes] == [
        c.text for c in meeting.gold.circumstance_changes
    ]


def test_pseudonymiser_numbering_and_ambiguous_first_names() -> None:
    attendees = [
        Attendee(name="Sarah Nguyen", role="adviser"),
        Attendee(name="James Chen", role="client"),
        Attendee(name="James Patel", role="client"),
        Attendee(name="Priya Singh", role="paraplanner"),
    ]
    pseud = Pseudonymiser(attendees)
    assert pseud.mapping == {
        "Sarah Nguyen": "ADVISER",
        "James Chen": "CLIENT_1",
        "James Patel": "CLIENT_2",
        "Priya Singh": "PARAPLANNER",
    }
    text = "James Chen and James Patel met Sarah; James was late; Priya's model."
    out = pseud.apply(text)
    assert out == "CLIENT_1 and CLIENT_2 met ADVISER; James was late; PARAPLANNER's model."
    assert (
        pseud.restore(out)
        == "James Chen and James Patel met Sarah Nguyen; James was late; Priya Singh's model."
    )
    empty = Pseudonymiser([])
    assert empty.apply("nothing") == "nothing"
    assert empty.restore("CLIENT_1") == "CLIENT_1"


def test_pseudonymiser_unknown_role_prefix() -> None:
    pseud = Pseudonymiser([Attendee(name="Voice One", role="unknown")])
    assert pseud.apply("Voice One spoke") == "SPEAKER spoke"
    note = FileNote.model_validate(
        {
            "meeting": {"date": "2026-01-01", "type": "initial"},
            "goals": [Claim(text="SPEAKER wants to retire", evidence=["s001"]).model_dump()],
        }
    )
    assert pseud.restore_note(note).goals[0].text == "Voice One wants to retire"
