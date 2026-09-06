"""The demo application: seeded client book, tools, question templates, the fake tool-using
model and its directives / corruption, the instrumented app with failure injection, and the
deterministic traffic generator."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

import pytest

from opsloop.demo.app import (
    BLOCKED_TEXT,
    UNAVAILABLE_TEXT,
    AdviserAssistant,
    Faults,
    build_messages,
)
from opsloop.demo.book import ClientBook
from opsloop.demo.model import (
    OUT_OF_SCOPE,
    STALE_REFUSAL,
    Corruption,
    DemoFakeModel,
    Directives,
    parse_user_message,
)
from opsloop.demo.questions import (
    BY_NAME,
    QUESTION_TYPES,
    Question,
    QuestionSampler,
    classify,
    render_question,
)
from opsloop.demo.scenario import EXPECTED_ALERTS, Incident, TrafficSpec, load_scenario
from opsloop.demo.tools import TOOL_NAMES, Tools
from opsloop.demo.traffic import faults_from, prompt_version_for, run_traffic
from opsloop.llm import ChatMessage
from opsloop.prompts.registry import PromptRegistry
from opsloop.quality.scorers import score_answer
from opsloop.release.canary import CanaryState, PromptRelease
from opsloop.sdk.models import Trace
from opsloop.sdk.tracing import Tracer
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH, SimClock
from tests.conftest import SCENARIOS_DIR, tiny_scenario


def test_book_is_seeded_and_plausible(book: ClientBook) -> None:
    again = ClientBook.generate(seed=7, n_clients=60)
    assert again.model_dump() == book.model_dump()
    assert ClientBook.generate(seed=8, n_clients=60).clients[0].name != book.clients[0].name
    c = book.get("C0001")
    assert c.accounts and all(
        abs(sum(h.weight for h in a.holdings) - 1.0) < 1e-6 for a in c.accounts
    )
    assert any(cl.stale_valuation for cl in book.clients) and any(
        cl.has("pension") for cl in book.clients
    )
    with pytest.raises(KeyError):
        book.get("C9999")


def test_tools_return_grounded_derived_numbers(book: ClientBook) -> None:
    tools = Tools(book)
    client = next(c for c in book.clients if c.has("pension"))
    h = tools.call("get_holdings", client.client_id)
    assert h["growth_pct"] + h["defensive_pct"] == pytest.approx(100.0)
    assert h["within_range"] == (h["deviation_points"] == 0.0)
    assert h["pension"] is not None and h["pension"]["min_annual_payment"] == pytest.approx(
        h["pension"]["balance"] * h["pension"]["min_drawdown_pct"] / 100, abs=0.02
    )
    assert "tfn" not in h and "tfn" in Tools(book, leak_tfn=True).call(
        "get_holdings", client.client_id
    )
    f = tools.call("fee_schedule", client.client_id)
    assert f["total_annual_fee"] == pytest.approx(
        f["total_admin_fee"] + f["total_investment_fee"] + f["total_adviser_fee"], abs=0.02
    )
    c = tools.call("contribution_room", client.client_id)
    assert c["concessional_room"] == pytest.approx(
        max(c["concessional_cap"] - c["concessional_ytd"], 0.0)
    )
    r = tools.call("review_schedule", client.client_id)
    assert r["overdue"] == (r["days_until_next_review"] < 0)
    insured = next(c for c in book.clients if c.insurance is not None)
    assert tools.call("insurance_cover", insured.client_id)["has_cover"] is True
    uninsured = next(c for c in book.clients if c.insurance is None)
    assert tools.call("insurance_cover", uninsured.client_id)["has_cover"] is False
    with pytest.raises(KeyError):
        tools.call("not_a_tool", client.client_id)
    assert len(TOOL_NAMES) == 5


def test_question_templates_classify_and_sample(book: ClientBook, rng: random.Random) -> None:
    assert (
        len([q for q in QUESTION_TYPES if q.in_scope]) == 42
        and len([q for q in QUESTION_TYPES if not q.in_scope]) == 6
    )
    client = book.clients[0]
    for qt in QUESTION_TYPES:
        text = render_question(qt, client)
        assert classify(text) is qt, qt.name
    assert classify("Something else entirely") is None
    sampler = QuestionSampler(book, rng)
    questions = [sampler.sample(out_of_scope_share=0.0) for _ in range(200)]
    assert all(q.type.in_scope for q in questions)
    assert all(q.type.requires is None or q.type.requires(book.get(q.client_id)) for q in questions)
    shifted = [sampler.sample(out_of_scope_share=1.0) for _ in range(10)]
    assert all(not q.type.in_scope for q in shifted)
    fixed = sampler.sample(client=client)
    assert fixed.client_id == client.client_id


def test_directives_from_prompts(registry: PromptRegistry) -> None:
    variables = {
        "adviser_name": "A",
        "today": "2026-09-01",
        "client_name": "C",
        "risk_profile": "Balanced",
    }
    v1 = Directives.from_system_prompt(registry.render("adviser_assistant@v1", variables))
    v2 = Directives.from_system_prompt(registry.render("adviser_assistant@v2", variables))
    bad = Directives.from_system_prompt(
        registry.render("adviser_assistant@v2-regressed", variables)
    )
    assert not v1.exact_figures and v1.offer_help and not v1.terse_reviews
    assert v2.exact_figures and v2.deviation_points and v2.terse_reviews and v2.offer_help
    assert bad.round_figures and bad.word_cap == 40 and bad.decline_stale and not bad.offer_help


def _messages(
    registry: PromptRegistry,
    book: ClientBook,
    version: str,
    qname: str,
    *,
    leak: bool = False,
    client_id: str | None = None,
) -> tuple[list[ChatMessage], dict[str, Any], str]:
    qt = BY_NAME[qname]
    client = (
        book.get(client_id)
        if client_id
        else next(c for c in book.clients if qt.requires is None or qt.requires(c))
    )
    tools = Tools(book, leak_tfn=leak)
    outputs = {name: tools.call(name, client.client_id) for name in qt.tools}
    spec = registry.get(f"adviser_assistant@{version}")
    variables = {
        "adviser_name": client.adviser_name,
        "today": book.today,
        "client_name": client.name,
        "risk_profile": client.risk_profile,
    }
    question = render_question(qt, client)
    return build_messages(spec, variables, question, outputs), outputs, question


def test_fake_model_v1_rounds_fee_percentage_and_v2_quotes_exactly(
    registry: PromptRegistry, book: ClientBook
) -> None:
    model = DemoFakeModel()
    msgs1, outputs, question = _messages(registry, book, "v1", "fee_pct")
    a1 = model.chat(msgs1).text
    assert "about" in a1 and a1.endswith("full breakdown.")
    s1 = score_answer(a1, tool_outputs=outputs, question=question)
    assert not s1.grounded and s1.ungrounded_numbers
    msgs2, _, _ = _messages(registry, book, "v2", "fee_pct")
    a2 = model.chat(msgs2).text
    assert score_answer(a2, tool_outputs=outputs, question=question).grounded and "about" not in a2
    assert model.calls == 2 and model.name == "northshore-assistant-4b"


def test_fake_model_regressed_prompt_rounds_truncates_and_refuses(
    registry: PromptRegistry, book: ClientBook
) -> None:
    model = DemoFakeModel()
    stale = next(c for c in book.clients if c.stale_valuation)
    fresh = next(c for c in book.clients if not c.stale_valuation)
    msgs, _, _ = _messages(
        registry, book, "v2-regressed", "total_balance", client_id=stale.client_id
    )
    assert model.chat(msgs).text == STALE_REFUSAL.format(client=stale.name)
    msgs, outputs, question = _messages(
        registry, book, "v2-regressed", "total_balance", client_id=fresh.client_id
    )
    text = model.chat(msgs).text
    assert (
        len(text.split()) <= 41
        and not score_answer(text, tool_outputs=outputs, question=question).grounded
    )
    msgs, _, _ = _messages(registry, book, "v2-regressed", "fees_json", client_id=fresh.client_id)
    json_text = model.chat(msgs).text
    with pytest.raises(json.JSONDecodeError):
        json.loads(json_text)
    msgs, _, _ = _messages(registry, book, "v1", "fees_json", client_id=fresh.client_id)
    assert json.loads(model.chat(msgs).text)["client_id"] == fresh.client_id


def test_fake_model_out_of_scope_terse_reviews_and_tfn_echo(
    registry: PromptRegistry, book: ClientBook
) -> None:
    model = DemoFakeModel()
    msgs, _, _ = _messages(registry, book, "v1", "age_pension_estimate")
    assert model.chat(msgs).text.startswith("I can only help")
    msgs, _, _ = _messages(registry, book, "v2", "next_review")
    terse = model.chat(msgs).text
    assert "days." in terse and "full breakdown" not in terse
    msgs, _, _ = _messages(registry, book, "v1", "next_review")
    assert "full breakdown" in model.chat(msgs).text
    msgs, outputs, _ = _messages(registry, book, "v1", "total_balance", leak=True)
    assert str(outputs["get_holdings"]["tfn"]) in model.chat(msgs).text
    assert model.answer("", "Question: ???\n") == OUT_OF_SCOPE.format(client="the client")


def test_fake_model_corruption_is_seeded(registry: PromptRegistry, book: ClientBook) -> None:
    msgs, outputs, question = _messages(registry, book, "v1", "total_balance")
    clean = DemoFakeModel().chat(msgs).text
    corrupt = DemoFakeModel(corruption=Corruption(ungrounded_rate=1.0), seed=3)
    text = corrupt.chat(msgs).text
    assert (
        text != clean and not score_answer(text, tool_outputs=outputs, question=question).grounded
    )
    assert corrupt.chat(msgs).text == text
    refuser = DemoFakeModel(corruption=Corruption(refusal_rate=1.0))
    assert refuser.chat(msgs).text.startswith("I cannot answer")
    verbose = DemoFakeModel(corruption=Corruption(verbosity=5.0)).chat(msgs).text
    assert len(verbose) > len(clean) + 300 and Corruption().active() is False
    jm, _, _ = _messages(registry, book, "v1", "allocation_json")
    broken = DemoFakeModel(corruption=Corruption(invalid_json_rate=1.0)).chat(jm).text
    assert not broken.endswith("}")
    question_text, tools = parse_user_message(msgs[-1].content)
    assert question_text == question and "get_holdings" in tools
    assert parse_user_message("just text") == ("just text", {})


def test_app_handle_ok_blocked_error_and_tool_error(
    book: ClientBook, registry: PromptRegistry, rng: random.Random
) -> None:
    traces: list[Trace] = []
    clock = SimClock(DEMO_EPOCH)
    tracer = Tracer(traces.append, clock=clock.now)
    app = AdviserAssistant(book, registry, tracer, clock)
    client = book.clients[0]
    q = Question(
        BY_NAME["total_balance"],
        client.client_id,
        render_question(BY_NAME["total_balance"], client),
    )
    ok = app.handle(
        q, session_id="s", request_id="r1", prompt_version="v1", rng=rng, trace_id="ok1"
    )
    assert ok.status == "ok" and ok.trace_id == "ok1" and client.name in ok.answer
    trace = traces[-1]
    assert [s.kind for s in trace.spans] == ["guardrail", "tool", "llm"]
    assert (
        trace.attributes["prompt.variables"]["client_name"] == client.name
        and trace.attributes["app.intent"] == "total_balance"
    )
    assert (
        trace.spans[2].model == "northshore-assistant-4b"
        and trace.cost_usd is not None
        and trace.latency_ms > 0
    )
    blocked = app.handle(
        Question(q.type, q.client_id, f"{q.text} (TFN {client.tfn})"),
        session_id="s",
        request_id="r2",
        prompt_version="v1",
        rng=rng,
    )
    assert (
        blocked.answer == BLOCKED_TEXT
        and traces[-1].attributes["guardrail.blocked"] is True
        and len(traces[-1].spans) == 1
    )
    err = app.handle(
        q,
        session_id="s",
        request_id="r3",
        prompt_version="v1",
        rng=rng,
        faults=Faults(error_rate=1.0, error_kinds=("timeout",)),
    )
    assert err.status == "error" and err.error_class == "timeout" and err.answer == UNAVAILABLE_TEXT
    assert (
        traces[-1].status == "error"
        and traces[-1].spans[-1].error_class == "timeout"
        and traces[-1].latency_ms >= 30_000
    )
    provider = app.handle(
        q,
        session_id="s",
        request_id="r4",
        prompt_version="v1",
        rng=rng,
        faults=Faults(error_rate=1.0, error_kinds=("provider_error",)),
    )
    assert provider.error_class == "provider_error"
    tool_err = app.handle(
        q,
        session_id="s",
        request_id="r5",
        prompt_version="v1",
        rng=rng,
        faults=Faults(tool_error_rate=1.0),
    )
    assert tool_err.error_class == "tool_error" and traces[-1].spans[1].status == "error"
    assert app.spec("v1") is app.spec("v1")


def test_faults_and_prompt_version_resolution() -> None:
    incidents = [
        Incident(kind="latency_spike", start_minute=0, end_minute=10, params={"multiplier": 3.0}),
        Incident(
            kind="error_burst",
            start_minute=0,
            end_minute=10,
            params={"error_rate": 0.5, "kinds": ["timeout"], "tool_error_rate": 0.1},
        ),
        Incident(kind="cost_creep", start_minute=0, end_minute=10),
        Incident(
            kind="pii_leak",
            start_minute=0,
            end_minute=10,
            params={"ungrounded_rate": 0.2, "refusal_rate": 0.1, "invalid_json_rate": 0.3},
        ),
    ]
    f = faults_from(incidents)
    assert (
        f.llm_latency_multiplier == 3.0
        and f.error_rate == 0.5
        and f.error_kinds == ("timeout",)
        and f.tool_error_rate == 0.1
    )
    assert f.leak_tfn and f.corruption.verbosity == 5.0 and f.corruption.ungrounded_rate == 0.2
    assert f.corruption.refusal_rate == 0.1 and f.corruption.invalid_json_rate == 0.3
    assert faults_from([]).corruption.active() is False
    sc = tiny_scenario(canary=None)
    regressed = Incident(kind="regressed_prompt", start_minute=0, end_minute=5)
    assert prompt_version_for(sc, [regressed], "s", None) == "v2-regressed"
    assert prompt_version_for(sc, [], "s", None) == "v1"
    release = PromptRelease(active="v1", canary=CanaryState(version="v2", stage=100))
    assert prompt_version_for(sc, [], "s", release) == "v2"
    sc2 = tiny_scenario(canary={"version": "v2", "stage": 100})
    assert prompt_version_for(sc2, [], "any", None) == "v2"
    assert (
        EXPECTED_ALERTS["topic_shift"] == ["topic_drift"]
        and regressed.expected_alerts == EXPECTED_ALERTS["regressed_prompt"]
    )
    with pytest.raises(ValueError):
        Incident(kind="error_burst", start_minute=10, end_minute=5)


def test_scenario_files_load_and_are_consistent() -> None:
    names = {p.stem for p in SCENARIOS_DIR.glob("*.yaml")}
    assert {
        "steady",
        "latency_spike",
        "error_burst",
        "regressed_prompt",
        "topic_shift",
        "cost_creep",
        "pii_leak",
        "canary_good",
        "canary_bad",
    } <= names
    sc = load_scenario(SCENARIOS_DIR / "error_burst.yaml")
    assert (
        sc.incidents[0].params["error_rate"] == 0.25
        and sc.incident_active(110)
        and not sc.incident_active(10)
    )
    assert sc.active_incidents(105)[0].kind == "error_burst"
    assert load_scenario(SCENARIOS_DIR / "canary_bad.yaml").canary is not None


def test_traffic_is_deterministic_and_summarised(registry: PromptRegistry, tmp_path: Path) -> None:
    exports = []
    for k in range(2):
        store = TraceStore(":memory:")
        summary = run_traffic(tiny_scenario(), seed=5, minutes=30, store=store, registry=registry)
        assert summary.n_requests > 100 and summary.by_prompt_version == {"v1": summary.n_requests}
        assert summary.n_feedback > 0 and summary.tracer_stats["exported"] == summary.n_requests
        path = tmp_path / f"run{k}.jsonl"
        store.export_jsonl(path)
        exports.append(path.read_bytes())
        store.close()
    assert exports[0] == exports[1]
    other = TraceStore(":memory:")
    run_traffic(tiny_scenario(), seed=6, minutes=30, store=other, registry=registry)
    (tmp_path / "other.jsonl").write_bytes(b"")
    other.export_jsonl(tmp_path / "other.jsonl")
    assert (tmp_path / "other.jsonl").read_bytes() != exports[0]


def test_traffic_sampling_and_incidents(registry: PromptRegistry) -> None:
    store = TraceStore(":memory:")
    sc = tiny_scenario(
        incidents=[Incident(kind="pii_leak", start_minute=0, end_minute=20)],
        traffic=TrafficSpec(),
    )
    summary = run_traffic(sc, seed=2, minutes=20, store=store, registry=registry, sample_rate=0.3)
    assert (
        summary.tracer_stats["sampled_out"] > 0
        and summary.by_incident["pii_leak"] == summary.n_requests
    )
    rows = store.rows()
    assert 0 < len(rows) < summary.n_requests
    assert any(r.pii_leak for r in rows if r.status == "ok")
    assert any(r.negative_feedback for r in rows)
