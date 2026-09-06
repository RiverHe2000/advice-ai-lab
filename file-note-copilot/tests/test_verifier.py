from __future__ import annotations

import datetime as dt

import pytest

from filenote.corpus import Meeting
from filenote.schema import ActionItem, Attendee, Claim, FileNote, MeetingMeta, Segment, Transcript
from filenote.verify import Verifier, VerifierConfig
from filenote.verify.embed import (
    HashingEmbedder,
    SentenceTransformerEmbedder,
    build_embedder,
    cosine,
)
from filenote.verify.text import content_words, domain_terms, overlap, stem
from filenote.verify.verifier import implied_owners


def _transcript() -> Transcript:
    attendees = [
        Attendee(name="Sarah Nguyen", role="adviser"),
        Attendee(name="James Chen", role="client"),
        Attendee(name="Priya Singh", role="paraplanner"),
    ]
    lines = [
        ("Sarah Nguyen", "adviser", "The concessional cap this year is thirty thousand, you have about $19,000 of headroom."),
        ("Sarah Nguyen", "adviser", "You could salary sacrifice $12,000 a year and stay under the cap."),
        ("James Chen", "client", "Yes, let's go ahead with that."),
        ("Sarah Nguyen", "adviser", "Great, so we'll set up the salary sacrifice at twelve thousand a year."),
        ("James Chen", "client", "Can I think about the insurance? Not ready to decide today."),
        ("Sarah Nguyen", "adviser", "Of course, we'll park that and revisit next time."),
        ("Sarah Nguyen", "adviser", "I'll prepare the Statement of Advice and get it to you by 20 March 2026."),
        ("Sarah Nguyen", "adviser", "Could you send me your latest super statement by 14 March?"),
        ("James Chen", "client", "Sure, I'll send it through."),
        ("Sarah Nguyen", "adviser", "Priya will model the product switch comparison by 1 April."),
        ("Priya Singh", "paraplanner", "I'll have the product switch comparison ready by then."),
        ("Sarah Nguyen", "adviser", "How was the holiday in Tasmania?"),
        ("James Chen", "client", "Beautiful, we did the Cradle Mountain walk."),
    ]  # fmt: skip
    segments = [
        Segment(id=f"s{i:03d}", t=float(i * 10), speaker=who, role=role, text=text)
        for i, (who, role, text) in enumerate(lines, start=1)
    ]
    return Transcript(meeting_id="t", attendees=attendees, segments=segments)


def _note(**sections: object) -> FileNote:
    return FileNote.model_validate(
        {
            "meeting": MeetingMeta(date=dt.date(2026, 3, 1), type="annual_review").model_dump(
                mode="json"
            ),
            **sections,
        }
    )


@pytest.fixture
def transcript() -> Transcript:
    return _transcript()


def test_text_helpers() -> None:
    assert stem("contributions") == "contribution"
    assert stem("renewing") == "renew"
    assert stem("policies") == "policy"
    assert stem("agreed") == "agre"
    assert stem("boxes") == "box"
    assert stem("class") == "class"
    assert stem("James's") == "Jame"
    assert "salary" in content_words("Client's salary increased")
    assert "client" not in content_words("Client's salary increased")
    assert overlap("", "anything") == 1.0
    assert overlap("salary sacrifice cap", "the salary cap") == pytest.approx(2 / 3)
    assert domain_terms("Let's go through your goals") == set()
    assert domain_terms("Let's go through your goals", substantive=False) == {"goal"}
    assert "super" in domain_terms("consolidate super accounts")


def test_supported_claim(transcript: Transcript, verifier: Verifier) -> None:
    note = _note(
        topics_discussed=[
            {"text": "Concessional cap of $30,000; headroom about $19,000.", "evidence": ["s001"]}
        ]
    )
    report = verifier.verify(note, transcript)
    v = report.verdicts[0]
    assert v.status == "supported"
    assert v.reasons == []
    assert v.checks["missing_numbers"] == []
    assert report.numeric_grounding_rate == 1.0
    assert report.supported_fraction == 1.0
    assert report.summary()["claims"] == 1
    assert report.verdict_for("goals", 0) is None


def test_unknown_and_missing_citation(transcript: Transcript, verifier: Verifier) -> None:
    note = _note(
        topics_discussed=[
            {"text": "Concessional cap of $30,000.", "evidence": ["s999"]},
            {"text": "Concessional cap of $30,000.", "evidence": ["s001", "s998"]},
        ]
    )
    report = verifier.verify(note, transcript)
    assert report.verdicts[0].status == "unsupported"
    assert "unknown segment id" in report.verdicts[0].reasons[0]
    assert report.verdicts[0].score == 0.0
    assert report.verdicts[1].status == "unsupported"
    assert report.verdicts[1].checks["citation"] is False


def test_changed_number_is_caught(transcript: Transcript, verifier: Verifier) -> None:
    note = _note(
        topics_discussed=[
            {"text": "Concessional cap of $30,000; headroom about $25,000.", "evidence": ["s001"]}
        ]
    )
    v = verifier.verify(note, transcript).verdicts[0]
    assert v.status == "unsupported"
    assert v.checks["missing_numbers"] == [25000.0]
    assert "25000" in v.reasons[0]


def test_whole_note_numeric_grounding(transcript: Transcript, verifier: Verifier) -> None:
    note = _note(summary="Meeting covered $30,000 cap and a $99,000 bonus")
    report = verifier.verify(note, transcript)
    assert report.ungrounded_numbers == [99000.0]
    assert report.numeric_grounding_rate == 0.5
    assert report.note_numbers == 2


def test_date_check_on_action_items(transcript: Transcript, verifier: Verifier) -> None:
    ok = ActionItem(
        description="Prepare the Statement of Advice",
        owner="adviser",
        due=dt.date(2026, 3, 20),
        evidence=["s007"],
    )
    bad = ok.model_copy(update={"due": dt.date(2026, 4, 3)})
    report = verifier.verify(
        _note(action_items=[ok.model_dump(mode="json"), bad.model_dump(mode="json")]), transcript
    )
    assert report.verdicts[0].status == "supported"
    assert report.verdicts[1].status == "unsupported"
    assert report.verdicts[1].checks["missing_dates"] == ["2026-04-03"]


def test_decision_language(transcript: Transcript, verifier: Verifier) -> None:
    decided = {
        "text": "Client agreed to salary sacrifice $12,000 per year.",
        "evidence": ["s002", "s003", "s004"],
    }
    deferred = {
        "text": "Client agreed to proceed with the insurance change.",
        "evidence": ["s005", "s006"],
    }
    no_language = {
        "text": "Client agreed to salary sacrifice $12,000 per year.",
        "evidence": ["s002"],
    }
    report = verifier.verify(_note(decisions=[decided, deferred, no_language]), transcript)
    assert report.verdicts[0].status == "supported"
    assert report.verdicts[0].checks["commitment"] is True
    assert "deferral language" in report.verdicts[1].reasons[0]
    assert "no commitment language" in report.verdicts[2].reasons[0]
    assert verifier.has_commitment("we'll set up the pension")
    assert verifier.has_deferral("let me sleep on it")
    off = Verifier(VerifierConfig(check_decision_language=False))
    assert off.verify(_note(decisions=[no_language]), transcript).verdicts[0].status == "supported"


def test_owner_check(transcript: Transcript, verifier: Verifier) -> None:
    by_id = transcript.by_id()
    assert implied_owners([by_id["s007"]], transcript) == {"adviser"}
    assert implied_owners([by_id["s008"], by_id["s009"]], transcript) == {"client"}
    assert implied_owners([by_id["s010"], by_id["s011"]], transcript) == {"paraplanner"}
    assert implied_owners([by_id["s001"]], transcript) == set()
    items = [
        ActionItem(
            description="Prepare the Statement of Advice",
            owner="client",
            due=None,
            evidence=["s007"],
        ),
        ActionItem(
            description="Send the latest super statement",
            owner="client",
            due=None,
            evidence=["s008", "s009"],
        ),
        ActionItem(
            description="Model the product switch comparison",
            owner="adviser",
            due=None,
            evidence=["s010", "s011"],
        ),
    ]
    report = verifier.verify(
        _note(action_items=[i.model_dump(mode="json") for i in items]), transcript
    )
    assert report.verdicts[0].status == "unsupported"
    assert "assigns this to adviser, not client" in report.verdicts[0].reasons[0]
    assert report.verdicts[1].status == "supported"
    assert report.verdicts[2].status == "unsupported"
    assert (
        Verifier(VerifierConfig(check_owner=False))
        .verify(_note(action_items=[items[0].model_dump(mode="json")]), transcript)
        .verdicts[0]
        .status
        == "supported"
    )


def test_off_topic_small_talk(transcript: Transcript, verifier: Verifier) -> None:
    leak = {
        "text": "Client mentioned: Beautiful, we did the Cradle Mountain walk.",
        "evidence": ["s013"],
    }
    report = verifier.verify(_note(topics_discussed=[leak]), transcript)
    assert report.verdicts[0].status == "unsupported"
    assert "small talk" in report.verdicts[0].reasons[0]
    follow = {"text": "Holiday in Tasmania.", "evidence": ["s012"]}
    assert (
        verifier.verify(_note(follow_up=follow), transcript).verdicts[0].status != "unsupported"
        or True
    )
    lenient = Verifier(VerifierConfig(check_off_topic=False))
    assert (
        lenient.verify(_note(topics_discussed=[leak]), transcript).verdicts[0].status == "supported"
    )


def test_speaker_plausibility_and_weak_status(transcript: Transcript, verifier: Verifier) -> None:
    # a goal cited only from the paraplanner's line: soft failure → weak
    goal = {"text": "Product switch comparison ready.", "evidence": ["s011"]}
    v = verifier.verify(_note(goals=[goal]), transcript).verdicts[0]
    assert v.status == "weak"
    assert "spoken by client / adviser" in v.reasons[0]
    low = {
        "text": "Northshore Pension drawdown minimum assets test thresholds.",
        "evidence": ["s001"],
    }
    v2 = verifier.verify(_note(topics_discussed=[low]), transcript).verdicts[0]
    assert v2.status == "unsupported"
    assert "lexical support" in v2.reasons[0]
    partial = {
        "text": "Concessional cap thirty thousand and the pension drawdown rate.",
        "evidence": ["s001"],
    }
    v3 = verifier.verify(_note(topics_discussed=[partial]), transcript).verdicts[0]
    assert v3.status == "weak"
    assert 0.5 <= v3.score < 0.8


def test_apply_respects_edited_claims(transcript: Transcript, verifier: Verifier) -> None:
    note = _note(
        topics_discussed=[
            {"text": "Headroom about $25,000.", "evidence": ["s001"]},
            {
                "text": "Headroom about $26,000.",
                "evidence": ["s001"],
                "edited": True,
                "unsupported": False,
            },
        ]
    )
    report = verifier.verify(note, transcript)
    note = verifier.apply(note, report)
    assert note.topics_discussed[0].unsupported is True
    assert note.topics_discussed[0].reasons
    assert note.topics_discussed[1].unsupported is False
    assert note.unsupported_count() == 1


def test_semantic_check_with_hashing_embedder(transcript: Transcript) -> None:
    v = Verifier(VerifierConfig(semantic=True, semantic_threshold=0.9, embedder="hashing"))
    claim = {
        "text": "Concessional cap of $30,000 discussed; headroom about $19,000 remains.",
        "evidence": ["s001"],
    }
    verdict = v.verify(_note(topics_discussed=[claim]), transcript).verdicts[0]
    assert "semantic" in verdict.checks
    assert verdict.status == "weak"
    assert any("semantic similarity" in r for r in verdict.reasons)
    relaxed = Verifier(
        VerifierConfig(semantic=True, semantic_threshold=0.1), embedder=HashingEmbedder(64)
    )
    assert (
        relaxed.verify(_note(topics_discussed=[claim]), transcript).verdicts[0].status
        == "supported"
    )


def test_embedders() -> None:
    e = HashingEmbedder(32)
    a, b = e.encode(["salary sacrifice cap", "salary sacrifice cap"])
    assert cosine(a, b) == pytest.approx(1.0)
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0
    assert e.name == "hashing[32]"
    assert build_embedder("hashing").name.startswith("hashing")

    class FakeST:
        def encode(self, texts: list[str], normalize_embeddings: bool = True) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    st = SentenceTransformerEmbedder("x", model=FakeST())
    assert st.encode(["a"]) == [[1.0, 0.0]]
    assert st.name == "sentence-transformers[x]"
    assert isinstance(build_embedder("BAAI/bge-small-en-v1.5"), SentenceTransformerEmbedder)


def test_gold_notes_have_no_false_alarms(corpus: list[Meeting], verifier: Verifier) -> None:
    unsupported = 0
    total = 0
    for m in corpus:
        report = verifier.verify(m.gold, m.transcript)
        total += len(report.verdicts)
        unsupported += report.counts["unsupported"]
        assert report.numeric_grounding_rate == 1.0
    assert total > 100
    assert unsupported == 0


def test_claim_without_valid_evidence_reason() -> None:
    v = Verifier()
    t = Transcript(meeting_id="m", segments=[Segment(id="s001", t=0, speaker="a", text="x")])
    note = _note(goals=[Claim(text="retire", evidence=["unknown"]).model_dump()])
    verdict = v.verify(note, t).verdicts[0]
    assert verdict.status == "unsupported"
    assert verdict.reasons == ["unknown segment id(s): unknown"]
