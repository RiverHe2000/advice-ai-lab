from __future__ import annotations

import datetime as dt
import json

import pytest

from filenote.config import DraftSettings, Settings
from filenote.corpus import Meeting
from filenote.draft import (
    DraftError,
    DraftEvent,
    ExtractThenComposeDrafter,
    Fact,
    SingleShotDrafter,
    VerifiedDrafter,
    build_drafter,
    compose_from_facts,
)
from filenote.draft.facts import compliance_facts, facts_from_note
from filenote.draft.prompts import (
    json_block_in,
    last_user,
    meeting_id_of,
    repair_messages,
    retry_message,
    single_shot_messages,
    task_of,
)
from filenote.draft.strategies import coerce_note, default_meeting
from filenote.fake import Corruption, GoldFakeChatModel
from filenote.llm import ChatMessage, ScriptedChatModel
from filenote.pii import Pseudonymiser
from filenote.schema import MeetingMeta, Transcript
from tests.conftest import FakeFactory

STRATEGIES = ("single_shot", "extract_then_compose", "verified", "verified_single_shot")


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_fake_at_zero_corruption_reproduces_gold(
    strategy: str, corpus: list[Meeting], make_fake: FakeFactory, settings: Settings
) -> None:
    drafter = build_drafter(strategy, make_fake(0.0), settings)
    assert drafter.strategy == strategy
    for m in corpus[:4]:
        result = drafter.draft(m.transcript, meeting=m.gold.meeting)
        assert result.parse_failures == 0
        assert result.json_repairs == 0
        assert result.note.model_dump(exclude={"meeting"}) == m.gold.model_dump(exclude={"meeting"})
        assert result.events[-1].stage == "done"
        assert result.latency_s >= 0.0
        assert result.prompt_tokens > 0
        if strategy == "verified":
            assert result.verification is not None
            assert result.verification.counts["unsupported"] == 0


@pytest.mark.parametrize("strategy", STRATEGIES)
def test_corruption_exercises_every_path(
    strategy: str, corpus: list[Meeting], make_fake: FakeFactory, settings: Settings
) -> None:
    model = make_fake(0.3, seed=1)
    drafter = build_drafter(strategy, model, settings)
    repairs = failures = 0
    for m in corpus:
        result = drafter.draft(m.transcript, meeting=m.gold.meeting)
        repairs += result.json_repairs
        failures += result.parse_failures
        assert result.note.meeting == m.gold.meeting
    assert repairs > 0
    assert failures == 0
    kinds = {k.split("|")[0] for k in model.calls}
    if strategy == "single_shot":
        assert kinds == {"single_shot"}
    elif strategy == "verified_single_shot":
        assert kinds == {"single_shot", "repair"}
    else:
        assert {"extract", "compose"} <= kinds
    if strategy in ("verified", "verified_single_shot"):
        assert "repair" in kinds


def test_verified_flags_and_repairs(
    corpus: list[Meeting], make_fake: FakeFactory, settings: Settings
) -> None:
    model = make_fake(
        1.0, kinds=frozenset({"invented_decision", "small_talk_leakage", "deferred_as_decided"})
    )
    drafter = build_drafter("verified", model, settings)
    m = corpus[1]
    result = drafter.draft(m.transcript, meeting=m.gold.meeting)
    assert isinstance(drafter, VerifiedDrafter)
    assert result.repair_dropped, "invented items must be dropped by the repair pass"
    assert result.note.unsupported_count() == 0
    stages = [e.stage for e in result.events]
    assert "verifying" in stages and "repairing" in stages
    assert [c.text for c in result.note.decisions] == [c.text for c in m.gold.decisions]


def test_verified_keeps_unsupported_when_model_insists(
    corpus: list[Meeting], make_fake: FakeFactory, settings: Settings
) -> None:
    model = make_fake(1.0, kinds=frozenset({"invented_decision", "repair_keep"}))
    # ``repair_keep`` makes the model insist on the invented claim instead of dropping it
    result = build_drafter("verified", model, settings).draft(
        corpus[2].transcript, meeting=corpus[2].gold.meeting
    )
    assert result.note.unsupported_count() == 1
    flagged = [c for c in result.note.decisions if c.unsupported]
    assert flagged and flagged[0].reasons
    assert result.events[-1].payload is not None and result.events[-1].payload["unsupported"] == 1


def test_parse_failure_is_recorded_not_defaulted(settings: Settings, meeting: Meeting) -> None:
    always_bad = ScriptedChatModel(default="not json at all")
    with pytest.raises(DraftError):
        SingleShotDrafter(always_bad, DraftSettings(max_parse_retries=1)).draft(meeting.transcript)
    assert len(always_bad.calls) == 2
    assert always_bad.calls[1][-1].content.startswith("Your previous output")
    with pytest.raises(DraftError):
        ExtractThenComposeDrafter(always_bad, DraftSettings(max_parse_retries=0)).draft(
            meeting.transcript
        )


def test_window_failure_is_recorded_and_compose_continues(meeting: Meeting) -> None:
    window_count = len(meeting.transcript.windows(20))

    def responder(messages: list[ChatMessage]) -> str:
        task = task_of(messages)
        if task == "extract" and "# window: 1/" in last_user(messages):
            return "garbage"
        if task == "extract":
            return json.dumps(
                {"facts": [{"category": "goal", "text": "Retire at 65", "evidence": ["s005"]}]}
            )
        return json.dumps(
            {"summary": "s", "goals": [{"text": "Retire at 65", "evidence": ["s005"]}]}
        )

    model = ScriptedChatModel(default=lambda msgs: responder(list(msgs)))
    result = ExtractThenComposeDrafter(model, DraftSettings(max_parse_retries=0)).draft(
        meeting.transcript
    )
    assert result.failed_windows == [1]
    assert result.parse_failures == 1
    assert result.model_calls == window_count + 1
    assert result.note.goals[0].text == "Retire at 65"
    assert len(result.facts) == window_count - 1


def test_validation_error_triggers_retry(meeting: Meeting) -> None:
    calls = {"n": 0}

    def responder(messages: list[ChatMessage]) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            return json.dumps({"facts": [{"category": "nonsense"}]})
        return json.dumps({"facts": []})

    model = ScriptedChatModel(default=lambda msgs: responder(list(msgs)))
    drafter = ExtractThenComposeDrafter(model, DraftSettings(max_parse_retries=1, window_size=500))
    drafter._extract(
        meeting.transcript,
        meeting.gold.meeting,
        __import__("filenote.draft.base", fromlist=["DraftResult"]).DraftResult(
            note=meeting.gold, strategy="x", model="m"
        ),
        None,
    )
    assert calls["n"] == 2


def test_coerce_note_is_lenient() -> None:
    meta = MeetingMeta(date=dt.date(2026, 1, 1), type="initial")
    note = coerce_note(
        {
            "summary": 5,
            "goals": [{"text": "a", "evidence": ["s001", "s001", ""]}, {"text": ""}, "junk"],
            "decisions": "not a list",
            "action_items": [
                {"description": "do", "owner": "CLIENT", "due": "2026-02-30"},
                {"text": "alt", "owner": "nobody", "due": "2026-02-01T00:00"},
            ],
            "compliance": {
                "risk_profile_confirmed": "true",
                "risk_profile": "Growth",
                "fee_consent_discussed": "maybe",
                "vulnerability_indicators": [{"text": "v"}],
            },
            "follow_up": {"text": "next", "evidence": []},
            "extra": 1,
        },
        meta,
    )
    assert note.summary == "5"
    assert [g.evidence for g in note.goals] == [["s001"]]
    assert note.decisions == []
    assert note.action_items[0].owner == "client" and note.action_items[0].due is None
    assert note.action_items[1].owner == "adviser" and note.action_items[1].due == dt.date(
        2026, 2, 1
    )
    assert note.action_items[1].evidence == ["unknown"]
    assert note.compliance.risk_profile_confirmed is True
    assert note.compliance.fee_consent_discussed is None
    assert note.compliance.vulnerability_indicators[0].evidence == ["unknown"]
    assert note.follow_up is not None and note.follow_up.evidence == ["unknown"]
    assert coerce_note({"compliance": "nope", "follow_up": {"text": ""}}, meta).follow_up is None


def test_default_meeting_from_transcript(meeting: Meeting) -> None:
    meta = default_meeting(meeting.transcript)
    assert meta.date == meeting.transcript.date
    assert meta.type == meeting.transcript.type
    bare = Transcript.from_text("Someone: hello there")
    meta2 = default_meeting(bare)
    assert meta2.type == "annual_review" and meta2.date == dt.date.today()


def test_facts_compose_and_inverse(meeting: Meeting) -> None:
    facts = facts_from_note(meeting.gold) + compliance_facts(meeting.gold.compliance)
    note = compose_from_facts(facts, meeting.gold.meeting, meeting.gold.summary)
    assert note.model_dump() == meeting.gold.model_dump()
    dup = [
        Fact(category="goal", text="Retire at 65", evidence=["s001"]),
        Fact(category="goal", text="retire at 65", evidence=["s002"]),
    ]
    merged = compose_from_facts(
        [
            *dup,
            Fact(category="follow_up", text="x", evidence=["s003"]),
            Fact(category="follow_up", text="y", evidence=["s004"]),
            Fact(category="topic", text="  "),
        ],
        meeting.gold.meeting,
        "s",
    )
    assert len(merged.goals) == 1 and merged.goals[0].evidence == ["s001", "s002"]
    assert merged.follow_up is not None and merged.follow_up.text == "x"
    assert merged.topics_discussed == []
    only = facts_from_note(meeting.gold, only_ids={"s999"})
    assert only == []


def test_prompt_helpers(meeting: Meeting) -> None:
    msgs = single_shot_messages(meeting.transcript, meeting.gold.meeting)
    assert task_of(msgs) == "single_shot"
    assert meeting_id_of(msgs) == meeting.id
    assert task_of([ChatMessage("user", "x")]) == "unknown"
    assert meeting_id_of([ChatMessage("user", "x")]) is None
    assert (
        last_user(
            [
                ChatMessage("user", "a"),
                ChatMessage("assistant", "b"),
                ChatMessage("user", "Your previous output was bad"),
            ]
        )
        == "a"
    )
    assert last_user([ChatMessage("system", "s")]) == ""
    repair = repair_messages(
        meeting.transcript,
        meeting.gold.meeting,
        [{"index": 0, "text": "t"}],
        meeting.transcript.segments[:2],
    )
    assert json_block_in(repair[1].content) == {"claims": [{"index": 0, "text": "t"}]}
    assert json_block_in("no block") is None
    assert json_block_in("```json\nnot json\n```") is None
    assert json_block_in("```json\n[1]\n```") is None


def test_fake_handles_unknown_transcript_and_pseudonyms(
    corpus: list[Meeting], make_fake: FakeFactory, settings: Settings
) -> None:
    model = make_fake(0.0)
    pasted = Transcript.from_text(
        "# meeting: pasted\nAlice (adviser): Your super balance is $500,000 and the fee is 0.5%.\nBob (client): Great.\nAlice (adviser): We could increase your life cover to $800,000."
    )
    for strategy in STRATEGIES:
        result = build_drafter(strategy, model, settings).draft(pasted)
        assert result.note.topics_discussed, strategy
        assert all(c.evidence[0].startswith("s") for c in result.note.topics_discussed)
    m = corpus[3]
    pseud = Pseudonymiser(m.transcript.attendees)
    result = build_drafter("verified", model, settings).draft(
        pseud.transcript(m.transcript), meeting=m.gold.meeting
    )
    texts = " ".join(c.label for c in result.note.all_claims()) + result.note.summary
    for name in pseud.mapping:
        assert name not in texts
    restored = pseud.restore_note(result.note)
    assert restored.model_dump(exclude={"meeting"}) == m.gold.model_dump(exclude={"meeting"})
    assert result.note.unsupported_count() == 0


def test_fake_malformed_json_styles_and_attempts(
    corpus: list[Meeting], gold_map: dict[str, Meeting]
) -> None:
    model = GoldFakeChatModel(
        gold_map, corruption=Corruption(p=1.0, seed=0, kinds=frozenset({"malformed_json"}))
    )
    m = corpus[0]
    msgs = single_shot_messages(m.transcript, m.gold.meeting)
    first = model.chat(msgs).text
    assert model.chat(msgs).text == first, "same prompt, same (malformed) answer"
    with pytest.raises(json.JSONDecodeError):
        json.loads(first)
    retry = [*msgs, ChatMessage("assistant", first), retry_message("no JSON object found")]
    second = model.chat(retry).text
    assert json.loads(second)
    assert model.name == "fake[p=1]"
    plain = GoldFakeChatModel(gold_map)
    assert (
        plain.chat(
            [ChatMessage("system", "# task: nothing"), ChatMessage("user", "# meeting: m0001")]
        ).text
        == "{}"
    )


def test_build_drafter_rejects_unknown(settings: Settings, make_fake: FakeFactory) -> None:
    with pytest.raises(ValueError, match="unknown strategy"):
        build_drafter("magic", make_fake(), settings)


def test_progress_callback_receives_events(
    meeting: Meeting, make_fake: FakeFactory, settings: Settings
) -> None:
    seen: list[DraftEvent] = []
    build_drafter("verified", make_fake(), settings).draft(
        meeting.transcript, meeting=meeting.gold.meeting, progress=seen.append
    )
    assert seen[0].stage == "extracting"
    assert any(e.stage == "partial" and e.section == "decisions" for e in seen)
    assert seen[-1].stage == "done"
