"""Heuristic scorers (numeric grounding, refusal, PII, JSON, tone, expectations), the ingest
pipeline, the sampling policy, the judge with a fake backend, and feedback signals."""

from __future__ import annotations

import pytest

from opsloop.feedback import add_feedback, build_feedback, edit_ratio
from opsloop.quality.judge import (
    FakeJudgeModel,
    JudgeScores,
    judge_and_store,
    judge_answer,
    judge_summary,
    judge_trace,
)
from opsloop.quality.pipeline import StoreExporter, ingest_trace
from opsloop.quality.sampling import sample_traces
from opsloop.quality.scorers import (
    evidence_values,
    extract_numbers,
    is_refusal,
    numeric_grounding,
    score_answer,
    score_trace,
)
from opsloop.sdk.tracing import Tracer
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH

TOOLS = {
    "get_holdings": {
        "total_balance": 123456.78,
        "growth_pct": 62.5,
        "weight": 0.62,
        "as_of": "2026-08-20",
        "n_accounts": 2,
    }
}


def test_extract_numbers_and_evidence() -> None:
    tokens = extract_numbers("Balance $123,456.78 is 62.5% of 2 accounts on 2026-08-20; ref C0042")
    assert [v for _, v in tokens] == [123456.78, 62.5, 2]
    values, strings = evidence_values(TOOLS)
    assert 123456.78 in values and 62.0 in values and 62.5 in values and "2026-08-20" in strings


@pytest.mark.parametrize(
    ("answer", "grounded"),
    [
        ("Total $123,456.78 across 2 accounts (62.5% growth, 62 % weight) as of 2026-08-20.", True),
        ("Total is about $123,000.", False),
        ("Growth is 63%.", False),
        ("Valued 2026-08-21.", False),
        ("No numbers at all.", True),
    ],
)
def test_numeric_grounding(answer: str, grounded: bool) -> None:
    ok, ungrounded, _ = numeric_grounding(answer, TOOLS)
    assert ok is grounded and (bool(ungrounded) is not grounded)


def test_grounding_accepts_numbers_from_the_question() -> None:
    ok, _, _ = numeric_grounding("Yes, 3 holdings.", {}, extra_text="List the top 3 holdings")
    assert ok


def test_refusal_pii_json_tone_and_length() -> None:
    assert is_refusal("I can only help with platform questions.") and is_refusal(
        "I cannot answer this."
    )
    assert not is_refusal("Here is the balance.")
    s = score_answer("I cannot answer this for the client. Please refresh.", tool_outputs=TOOLS)
    assert s.refusal and not s.passed and s.quality < 0.75 and s.tone_ok is False
    leak = score_answer(
        "Balance $123,456.78. TFN 123 456 782. Let me know if you need more.", tool_outputs=TOOLS
    )
    assert leak.pii_leak and not leak.passed and leak.checks["no_pii"] is False
    marker = score_answer("Balance $123,456.78 for [TFN].", tool_outputs=TOOLS)
    assert (
        marker.pii_leak
        and not score_answer("[TFN]", tool_outputs=TOOLS, pii_markers=False).pii_leak
    )
    good_json = score_answer('{"total_balance": 123456.78}', tool_outputs=TOOLS, json_expected=True)
    assert good_json.json_valid is True and good_json.tone_ok is None and good_json.passed
    bad_json = score_answer('{"total_balance": 123456.78', tool_outputs=TOOLS, json_expected=True)
    assert bad_json.json_valid is False and not bad_json.passed
    empty = score_answer("   ", tool_outputs=TOOLS)
    assert empty.empty and not empty.passed and empty.tone_ok is None
    long = score_answer("x" * 2000, tool_outputs=TOOLS, max_chars=100)
    assert not long.length_ok and long.quality < 1.0
    perfect = score_answer(
        "Total $123,456.78. Let me know if you would like more.", tool_outputs=TOOLS
    )
    assert perfect.passed and perfect.quality == 1.0 and perfect.as_dict()["quality"] == 1.0


def test_expectations_and_allowed_refusal() -> None:
    s = score_answer(
        "Total $123,456.78. Happy to help further.",
        tool_outputs=TOOLS,
        must_contain=["total"],
        must_not_contain=["cannot"],
        numeric_facts=[123456.78],
    )
    assert s.must_contain_ok and s.must_not_contain_ok and s.passed
    miss = score_answer(
        "Balance $123,456.78. Happy to help.", tool_outputs=TOOLS, must_contain=["pension"]
    )
    assert miss.must_contain_ok is False and not miss.passed
    forbidden = score_answer(
        "I cannot answer. Balance $123,456.78.", tool_outputs=TOOLS, must_not_contain=["cannot"]
    )
    assert forbidden.must_not_contain_ok is False
    allowed = score_answer(
        "I can only help with platform data.", tool_outputs={}, allow_refusal=True
    )
    assert allowed.refusal and allowed.passed and "no_refusal" not in allowed.checks
    facts = score_answer("The fee is $999.00. Let me know.", tool_outputs={}, numeric_facts=[999.0])
    assert facts.grounded


def test_score_trace_error_and_blocked(make_trace) -> None:  # type: ignore[no-untyped-def]
    assert score_trace(make_trace("e", status="error")) is None
    blocked = make_trace(
        "b",
        output="This message was blocked because it contains a tax file number.",
        json_expected=True,
        attributes={"guardrail.blocked": True},
    )
    s = score_trace(blocked)
    assert s is not None and s.json_valid is None and s.passed
    ok = score_trace(make_trace("o"))
    assert ok is not None and ok.grounded and ok.passed


def test_ingest_pipeline_sets_signals_and_sdk_pii_flag(make_trace) -> None:  # type: ignore[no-untyped-def]
    store = TraceStore(":memory:")
    assert ingest_trace(store, make_trace("err", status="error")) is None
    scores = ingest_trace(store, make_trace("ok"))
    assert scores is not None and store.rows(session_id="s1")[1].quality == pytest.approx(1.0)
    redacted = make_trace("pii", attributes={"pii.output_redactions": 1})
    ingest_trace(store, redacted)
    assert store.rows(session_id="s1")[2].pii_leak is True
    exporter = StoreExporter(store)
    exporter(make_trace("via-exporter"))
    assert store.count() == 4


def test_sampling_strata_budget_and_uniform(make_trace) -> None:  # type: ignore[no-untyped-def]
    store = TraceStore(":memory:")
    for i in range(30):
        status = "error" if i < 3 else "ok"
        store.insert_trace(
            make_trace(
                f"t{i:02d}",
                start=DEMO_EPOCH + i,
                status=status,
                error_class="timeout" if status == "error" else None,
            )
        )
    ingest_ids = {"t05", "t06"}
    for tid in ingest_ids:
        store.add_feedback(tid, DEMO_EPOCH, True, {"thumbs": "down"})
    for tid in ("t10", "t11", "t12", "t13"):
        store.update_signals(
            tid,
            __import__("opsloop.store", fromlist=["Signals"]).Signals(0.5, True, None, False, True),
        )
    rows = store.rows()
    sample = sample_traces(rows, budget=8, seed=1)
    assert (
        sample.strata == {"error": 3, "negative_feedback": 2, "low_quality": 3, "random": 0}
        and len(sample.trace_ids) == 8
    )
    assert (
        set(sample.trace_ids[:3]) == {"t00", "t01", "t02"}
        and set(sample.trace_ids[3:5]) == ingest_ids
    )
    big = sample_traces(rows, budget=20, seed=1)
    assert big.strata["random"] == 20 - 9 and big.population == 30
    assert sample_traces(rows, budget=20, seed=1).trace_ids == big.trace_ids
    excluded = sample_traces(rows, budget=20, seed=1, exclude=set(big.trace_ids))
    assert not (set(excluded.trace_ids) & set(big.trace_ids)) and len(excluded.trace_ids) == 10
    uniform = sample_traces(rows, budget=5, seed=2, strategy="uniform")
    assert (
        uniform.strata == {"error": 0, "negative_feedback": 0, "low_quality": 0, "random": 5}
        and uniform.as_dict()["strategy"] == "uniform"
    )


def test_fake_judge_scores_and_missing_on_invalid_json(make_trace) -> None:  # type: ignore[no-untyped-def]
    judge = FakeJudgeModel()
    trace = make_trace("j")
    result = judge_trace(judge, trace)
    assert (
        result.scores is not None
        and result.scores.grounding == 5
        and result.scores.helpfulness == 5
        and result.missing is False
    )
    assert result.repairs == 1 and result.attempts == 1 and result.as_dict()["mean"] == 5.0
    refusal = judge_answer(
        judge, trace_id="r", question="q", answer="I cannot answer this.", tool_outputs={}
    )
    assert refusal.scores is not None and refusal.scores.helpfulness == 1
    ungrounded = judge_answer(
        judge,
        trace_id="u",
        question="q",
        answer="Total is $999.00. Let me know.",
        tool_outputs=TOOLS,
    )
    assert (
        ungrounded.scores is not None
        and ungrounded.scores.grounding == 1
        and "ungrounded" in ungrounded.scores.rationale
    )
    leaky = judge_answer(
        judge, trace_id="l", question="q", answer="TFN 123 456 782. Let me know.", tool_outputs={}
    )
    assert leaky.scores is not None and leaky.scores.helpfulness <= 2
    broken = judge_trace(FakeJudgeModel(invalid_rate=1.0), trace, max_attempts=2)
    assert (
        broken.missing
        and broken.scores is None
        and broken.attempts == 2
        and broken.error is not None
    )
    assert JudgeScores(helpfulness=5, grounding=3, tone=1).mean == pytest.approx(3.0)


def test_judge_schema_and_call_failures() -> None:
    class Weird:
        name = "weird"

        def chat(self, messages, *, max_tokens=400, temperature=0.0):  # type: ignore[no-untyped-def]  # noqa: ARG002
            from opsloop.llm import ChatResponse

            return ChatResponse(text='{"helpfulness": 9, "grounding": 1, "tone": 1}', model="weird")

    r = judge_answer(Weird(), trace_id="x", question="q", answer="a", tool_outputs={})
    assert r.missing and r.error is not None and r.error.startswith("schema")

    class Broken:
        name = "broken"

        def chat(self, messages, *, max_tokens=400, temperature=0.0):  # type: ignore[no-untyped-def]  # noqa: ARG002
            raise RuntimeError("offline")

    r2 = judge_answer(
        Broken(), trace_id="x", question="q", answer="a", tool_outputs={}, max_attempts=1
    )
    assert r2.missing and "offline" in (r2.error or "")


def test_judge_and_store_and_summary(make_trace) -> None:  # type: ignore[no-untyped-def]
    store = TraceStore(":memory:")
    store.insert_trace(make_trace("a"))
    store.insert_trace(make_trace("b", status="error"))
    store.insert_trace(make_trace("c", output="I cannot answer this."))
    results = judge_and_store(store, FakeJudgeModel(), ["a", "b", "c", "missing"], ts=1.0)
    assert [r.trace_id for r in results] == ["a", "c"]
    assert (
        store.rows(session_id="s1")[0].judge == 5.0
        and store.scores_for("a")[0]["scorer"] == "judge"
    )
    summary = judge_summary(results)
    assert (
        summary["judged"] == 2 and summary["missing"] == 0 and summary["overall_mean"] is not None
    )
    assert judge_summary([])["overall_mean"] is None
    store2 = TraceStore(":memory:")
    store2.insert_trace(make_trace("d"))
    judge_and_store(store2, FakeJudgeModel(), ["d"], ts=1.0, slo_eligible=False)
    assert store2.rows()[0].judge is None and store2.scores_for("d")


def test_feedback_signals_and_promotion(make_trace) -> None:  # type: ignore[no-untyped-def]
    fb = build_feedback("t", ts=1.0, thumbs="down", wrong_part="numbers", comment="wrong fee")
    assert fb.negative and fb.reasons == ["thumbs_down"]
    assert build_feedback("t", ts=1.0, thumbs="up").negative is False
    assert build_feedback("t", ts=1.0, regenerated=True).reasons == ["regenerated"]
    tagged = build_feedback("t", ts=1.0, wrong_part="tone")
    assert tagged.reasons == ["wrong_part=tone"] and tagged.negative
    small = build_feedback(
        "t", ts=1.0, original_text="The balance is $100.", edited_text="The balance is $101."
    )
    assert small.edit_ratio is not None and small.edit_ratio < 0.3 and not small.negative
    big = build_feedback(
        "t",
        ts=1.0,
        original_text="The balance is $100.",
        edited_text="Completely rewritten answer about something else entirely.",
    )
    assert big.negative and big.reasons[0].startswith("edited(")
    assert edit_ratio("", "") == 0.0 and edit_ratio("abc", "abd") == pytest.approx(1 / 3)
    store = TraceStore(":memory:")
    tracer = Tracer(StoreExporter(store), sample_rate=0.0)
    with tracer.trace("r", "s", trace_id="sampled-out"):
        pass
    assert store.count() == 0
    add_feedback(store, build_feedback("sampled-out", ts=2.0, thumbs="down"), tracer=tracer)
    assert store.count() == 1 and store.rows()[0].negative_feedback is True
    add_feedback(store, build_feedback("sampled-out", ts=3.0, thumbs="up"), tracer=tracer)
    assert len(store.feedback_for("sampled-out")) == 2
