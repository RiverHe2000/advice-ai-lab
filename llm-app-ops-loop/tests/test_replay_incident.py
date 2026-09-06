"""Replay reproduces recorded answers with the fake model and diffs a changed prompt; incident
classification, change point and report rendering."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from opsloop.demo.model import DemoFakeModel
from opsloop.incident import (
    analyse,
    build_incident_report,
    change_point,
    classify_failures,
    elevated_segment,
    render_markdown,
)
from opsloop.llm import ChatMessage, ChatResponse, ModelError
from opsloop.prompts.registry import PromptRegistry
from opsloop.replay import render_markdown as render_replay
from opsloop.replay import replay_trace
from opsloop.store import SpanErrorRow, TraceRow, TraceStore
from opsloop.timeutil import DEMO_EPOCH


def test_replay_reproduces_recorded_answer(
    traffic_store: TraceStore, registry: PromptRegistry
) -> None:
    traces = [
        t
        for t in traffic_store.query(status="ok", limit=50)
        if not t.attributes.get("guardrail.blocked")
    ]
    for trace in traces[:10]:
        result = replay_trace(trace, registry, DemoFakeModel(seed=1))
        assert (
            result.identical
            and result.similarity == 1.0
            and result.diff == ""
            and not result.prompt_changed_since_recording
        )
        assert (
            result.new_scores["quality"] == result.recorded_scores["quality"]
            and result.cost_usd is not None
        )
        assert result.recorded_model == "northshore-assistant-4b"
    md = render_replay(replay_trace(traces[0], registry, DemoFakeModel(seed=1)))
    assert "identical answer: **yes**" in md and "## Diff" not in md


def test_replay_with_other_prompt_version_shows_diff(
    traffic_store: TraceStore, registry: PromptRegistry
) -> None:
    trace = next(
        t
        for t in traffic_store.query(status="ok", limit=200)
        if t.attributes.get("app.intent") == "fee_pct"
    )
    result = replay_trace(trace, registry, DemoFakeModel(seed=1), prompt_version="v2")
    assert (
        not result.identical
        and result.prompt_changed_since_recording
        and result.prompt_ref == "adviser_assistant@v2"
    )
    assert result.recorded_scores["grounded"] is False and result.new_scores["grounded"] is True
    assert "## Diff" in render_replay(result) and result.similarity < 1.0


def test_replay_records_model_error(traffic_store: TraceStore, registry: PromptRegistry) -> None:
    class Failing:
        name = "failing"

        def chat(
            self,
            messages: Sequence[ChatMessage],  # noqa: ARG002 - protocol signature
            *,
            max_tokens: int = 400,  # noqa: ARG002
            temperature: float = 0.0,  # noqa: ARG002
        ) -> ChatResponse:
            raise ModelError("offline", kind="provider")

    trace = traffic_store.query(status="ok", limit=1)[0]
    result = replay_trace(trace, registry, Failing())
    assert result.error == "offline" and result.new_answer == "" and result.cost_missing
    assert "error: offline" in render_replay(result)


def _row(i: int, **kw: object) -> TraceRow:
    base: dict[str, object] = {
        "trace_id": f"r{i}",
        "session_id": "s",
        "prompt_version": "v1",
        "start_ts": DEMO_EPOCH + i * 60.0,
        "end_ts": DEMO_EPOCH + i * 60.0 + 1,
        "latency_ms": 1000.0,
        "status": "ok",
        "error_class": None,
        "input_text": f"What is client {i}'s total balance across all accounts?",
        "output_text": "a",
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "cost_usd": 0.0003,
        "cost_missing": False,
        "json_expected": False,
        "quality": 0.95,
        "judge": None,
        "refusal": False,
        "json_valid": None,
        "pii_leak": False,
        "grounded": True,
        "negative_feedback": False,
        "attributes": {},
    }
    base.update(kw)
    return TraceRow(**base)  # type: ignore[arg-type]


def test_classify_failures_all_kinds() -> None:
    assert classify_failures(_row(0)) == []
    assert classify_failures(_row(0, status="error", error_class="timeout")) == ["timeout"]
    assert classify_failures(_row(0, status="error", error_class="tool_error")) == ["tool_error"]
    assert classify_failures(_row(0, status="error", error_class="provider_error")) == [
        "provider_error"
    ]
    kinds = classify_failures(
        _row(
            0,
            json_expected=True,
            json_valid=False,
            pii_leak=True,
            grounded=False,
            refusal=True,
            judge=2.0,
            negative_feedback=True,
        )
    )
    assert kinds == [
        "invalid_json",
        "pii_leak",
        "ungrounded",
        "refusal",
        "low_judge_score",
        "negative_feedback",
    ]
    assert classify_failures(_row(0, refusal=True, attributes={"guardrail.blocked": True})) == [
        "guardrail_block"
    ]


def test_change_point_finds_the_step() -> None:
    series = [0.02, 0.01, 0.03, 0.02, 0.30, 0.35, 0.28, 0.33]
    cp = change_point(series, [50] * 8)
    assert (
        cp is not None
        and cp.bucket_index == 4
        and cp.before_rate < 0.05
        and cp.after_rate > 0.25
        and cp.statistic > 3
    )
    assert change_point([0.1, 0.1], [10, 10]) is None
    assert change_point([0.1, 0.1, 0.1, 0.1], [0, 0, 0, 0]) is None
    assert elevated_segment(series, [50] * 8) == (4, 7)
    assert elevated_segment([0.1, 0.1, 0.1], [10, 10, 10]) is None
    assert elevated_segment([], []) is None and elevated_segment([0.5], [0]) is None


def test_analyse_and_render_incident(traffic_store: TraceStore) -> None:
    rows = traffic_store.rows()
    rng = traffic_store.time_range()
    assert rng is not None
    report = build_incident_report(traffic_store, since=rng[0], until=rng[1] + 1, bucket_minutes=10)
    assert (
        report.n_requests == len(rows)
        and report.by_kind.get("timeout", 0) + report.by_kind.get("provider_error", 0) > 0
    )
    assert (
        report.change_point is not None
        and report.change_point.after_rate > report.change_point.before_rate
        and report.change_point.end_ts is not None
    )
    assert (
        "model provider availability" in report.suspected_cause
        and report.by_topic
        and report.follow_ups
    )
    md = render_markdown(report, title="Error burst")
    assert (
        md.startswith("# Error burst")
        and "## Timeline" in md
        and "Elevated period" in md
        and "- [ ]" in md
    )
    quiet = analyse([_row(i) for i in range(30)], [], since=DEMO_EPOCH, until=DEMO_EPOCH + 1800)
    assert (
        quiet.n_failed == 0
        and quiet.suspected_cause == "no failures in the window"
        and quiet.change_point is None
    )
    versions = [_row(i, prompt_version="v2", grounded=False) for i in range(15)] + [
        _row(100 + i) for i in range(15)
    ]
    span_errors = [SpanErrorRow("r0", "tool", "fee_schedule", DEMO_EPOCH, "tool_error")]
    mixed = analyse(versions, span_errors, since=DEMO_EPOCH, until=DEMO_EPOCH + 8000)
    assert "prompt version v2" in mixed.suspected_cause and mixed.by_tool == {
        "fee_schedule:tool_error": 1
    }
    assert any("prompt v2: 15/15 failed" in e for e in mixed.evidence)
    md2 = render_markdown(mixed)
    assert "| Tool span error | Count |" in md2 and "| v2 | 15 | 15 |" in md2
    few = analyse(
        [_row(i, negative_feedback=True) for i in range(5)],
        [],
        since=DEMO_EPOCH,
        until=DEMO_EPOCH + 600,
    )
    assert few.by_topic == [] and "user-visible answer quality" in few.suspected_cause
    pii = analyse(
        [_row(i, pii_leak=True) for i in range(3)], [], since=DEMO_EPOCH, until=DEMO_EPOCH + 600
    )
    assert "identifiers" in pii.suspected_cause and any(
        "redaction test" in f for f in pii.follow_ups
    )
    assert pytest.approx(pii.failure_rate) == 1.0
