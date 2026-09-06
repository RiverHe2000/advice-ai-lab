"""Offline fixtures: the project's prompt registry and SLO config, a seeded client book, a tiny
scenario with one planted incident, traces built directly, and a session-scoped store with 60
simulated minutes of traffic. Nothing sleeps, nothing downloads."""

from __future__ import annotations

import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from opsloop.demo.book import ClientBook
from opsloop.demo.scenario import Incident, Scenario, TrafficSpec
from opsloop.demo.traffic import run_traffic
from opsloop.monitor.config import MonitorConfig
from opsloop.prompts.registry import PromptRegistry
from opsloop.sdk.models import Span, Trace
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH

PROJECT = Path(__file__).resolve().parents[1]
PROMPTS_DIR = PROJECT / "prompts"
SLO_PATH = PROJECT / "slos" / "default.yaml"
SCENARIOS_DIR = PROJECT / "scenarios"


@pytest.fixture(scope="session")
def registry() -> PromptRegistry:
    return PromptRegistry(PROMPTS_DIR)


@pytest.fixture(scope="session")
def config() -> MonitorConfig:
    return MonitorConfig.load(SLO_PATH)


@pytest.fixture(scope="session")
def book() -> ClientBook:
    return ClientBook.generate(seed=7, n_clients=60)


@pytest.fixture
def rng() -> random.Random:
    return random.Random(11)


def tiny_scenario(**overrides: Any) -> Scenario:
    base: dict[str, Any] = {
        "name": "tiny",
        "traffic": TrafficSpec(rate_per_minute=6, sessions=20, clients=60, book_seed=7),
        "incidents": [
            Incident(kind="error_burst", start_minute=40, end_minute=60, params={"error_rate": 0.4})
        ],
    }
    base.update(overrides)
    return Scenario(**base)


@pytest.fixture
def scenario() -> Scenario:
    return tiny_scenario()


@pytest.fixture(scope="session")
def traffic_store(registry: PromptRegistry) -> TraceStore:
    """60 simulated minutes of the tiny scenario (error burst from minute 40), in memory."""
    store = TraceStore(":memory:")
    run_traffic(tiny_scenario(), seed=1, minutes=60, store=store, registry=registry)
    return store


TraceFactory = Callable[..., Trace]


@pytest.fixture
def make_trace() -> TraceFactory:
    def factory(
        trace_id: str = "t1",
        *,
        start: float = DEMO_EPOCH,
        latency_ms: float = 900.0,
        status: str = "ok",
        error_class: str | None = None,
        output: str = "Amelia Abbott's total balance is $123,456.78 across 2 accounts. Let me know if you need more.",
        question: str = "What is Amelia Abbott's total balance across all accounts?",
        tool_output: dict[str, Any] | None = None,
        prompt_version: str = "v1",
        session_id: str = "s1",
        json_expected: bool = False,
        cost_usd: float | None = 0.0003,
        attributes: dict[str, Any] | None = None,
        model: str = "northshore-assistant-4b",
    ) -> Trace:
        tools = (
            tool_output
            if tool_output is not None
            else {"total_balance": 123456.78, "n_accounts": 2}
        )
        end = start + latency_ms / 1000.0
        spans = [
            Span(
                span_id=f"{trace_id}-tool",
                trace_id=trace_id,
                kind="tool",
                name="get_holdings",
                start_ts=start,
                end_ts=start + 0.05,
                latency_ms=50.0,
                attributes={"tool.output": tools},
            ),
            Span(
                span_id=f"{trace_id}-llm",
                trace_id=trace_id,
                kind="llm",
                name="chat",
                start_ts=start + 0.05,
                end_ts=end,
                latency_ms=latency_ms - 50.0,
                status="error" if status == "error" else "ok",
                error_class=error_class,
                model=model,
                prompt_tokens=500,
                completion_tokens=60,
                cost_usd=cost_usd,
                cost_missing=cost_usd is None,
            ),
        ]
        return Trace(
            trace_id=trace_id,
            request_id=f"req-{trace_id}",
            session_id=session_id,
            app_version="1.4.0",
            prompt_name="adviser_assistant",
            prompt_version=prompt_version,
            start_ts=start,
            end_ts=end,
            latency_ms=latency_ms,
            status="error" if status == "error" else "ok",
            error_class=error_class,
            input_text=question,
            output_text="" if status == "error" else output,
            prompt_tokens=500,
            completion_tokens=60,
            cost_usd=cost_usd,
            cost_missing=cost_usd is None,
            json_expected=json_expected,
            attributes=attributes
            or {
                "app.intent": "total_balance",
                "app.category": "balances",
                "prompt.variables": {
                    "adviser_name": "Priya Raman",
                    "today": "2026-09-01",
                    "client_name": "Amelia Abbott",
                    "risk_profile": "Balanced",
                },
                "prompt.hash": "238432dcc901",
            },
            spans=spans,
        )

    return factory
