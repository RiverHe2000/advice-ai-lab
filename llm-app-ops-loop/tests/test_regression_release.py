"""Regression-gate decision logic (non-inferior, inferior, McNemar, slice regression, JSON floor,
cost / latency budgets, insufficient data), the gate end to end with the fake model, canary
assignment determinism, cohort comparison and rollback / advance / promote."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from opsloop.dataset.curate import curate_from_trace
from opsloop.dataset.versioning import Dataset, DatasetManifest, DatasetStore
from opsloop.demo.model import DemoFakeModel
from opsloop.demo.traffic import run_traffic
from opsloop.llm import ChatMessage, ChatResponse, ModelError
from opsloop.prompts.registry import PromptRegistry
from opsloop.quality.judge import FakeJudgeModel
from opsloop.regression.gate import CaseRun, GateConfig, decide, render_markdown, run_case, run_gate
from opsloop.release.canary import (
    CanaryPolicy,
    CanaryState,
    PromptRelease,
    ReleaseFile,
    advance,
    apply_decision,
    assign,
    bucket,
    cohort_metrics,
    evaluate_canary,
    resolve_version,
    rollback,
    start_canary,
)
from opsloop.store import TraceRow, TraceStore
from opsloop.timeutil import DEMO_EPOCH
from tests.conftest import PROMPTS_DIR, tiny_scenario


def runs(
    scores: list[float],
    *,
    passed: list[bool] | None = None,
    tags: list[list[str]] | None = None,
    json_valid: list[bool | None] | None = None,
    cost: float = 0.0003,
    latency: float = 10.0,
) -> list[CaseRun]:
    out = []
    for i, s in enumerate(scores):
        out.append(
            CaseRun(
                case_id=f"c{i}",
                tags=tags[i] if tags else ["all"],
                answer="a",
                quality=s,
                passed=passed[i] if passed else s >= 0.75,
                checks={"no_refusal": True},
                ungrounded_numbers=[] if s >= 0.75 else ["$1"],
                json_valid=json_valid[i] if json_valid else None,
                cost_usd=cost,
                latency_ms=latency,
                prompt_tokens=100,
                completion_tokens=50,
            )
        )
    return out


def dataset(n: int) -> Dataset:
    from opsloop.dataset.curate import CuratedCase, Provenance

    cases = [
        CuratedCase(
            id=f"c{i}",
            input=f"q{i}",
            provenance=Provenance(trace_id="t", reviewer="r", date="d", prompt_version="v1"),
        )
        for i in range(n)
    ]
    return Dataset(
        manifest=DatasetManifest(name="d", version=1, content_hash="h", n_cases=n, created="now"),
        cases=cases,
    )


@pytest.fixture(scope="module")
def specs(registry: PromptRegistry):  # type: ignore[no-untyped-def]
    return registry.get("adviser_assistant@v2"), registry.get("adviser_assistant@v1")


def _decide(cand: list[CaseRun], base: list[CaseRun], specs, **cfg: object):  # type: ignore[no-untyped-def]
    return decide(
        dataset(len(cand)),
        specs[0],
        specs[1],
        cand,
        base,
        model_name="fake",
        config=GateConfig(min_cases=5, n_boot=300, **cfg),
    )


def test_gate_non_inferior_pass_and_inferior_fail(specs) -> None:  # type: ignore[no-untyped-def]
    base = runs([0.9] * 10)
    same = _decide(runs([0.9] * 10), base, specs)
    assert (
        same.decision == "PASS"
        and same.paired["delta"] == 0.0
        and "non-inferior" in same.reasons[0]
    )
    better = _decide(runs([1.0] * 10), base, specs)
    assert (
        better.decision == "PASS"
        and better.paired["wins"] == 10
        and better.mcnemar["p_value"] == 1.0
    )
    worse = _decide(runs([0.6] * 10), base, specs)
    assert (
        worse.decision == "FAIL"
        and any("not non-inferior" in r for r in worse.reasons)
        and any("McNemar" in r for r in worse.reasons)
    )
    md = render_markdown(worse)
    assert (
        "## Decision: **FAIL**" in md
        and "| c0 |" in md
        and "base ungrounded" not in md
        and "cand ungrounded $1" in md
    )


def test_gate_mcnemar_slice_json_cost_latency_insufficient(specs) -> None:  # type: ignore[no-untyped-def]
    base = runs([0.9] * 12)
    flip = runs([0.9] * 12, passed=[False] * 8 + [True] * 4)
    mc = _decide(flip, base, specs, margin=1.0)
    assert (
        mc.decision == "FAIL"
        and mc.mcnemar["losses"] == 8
        and any("McNemar" in r for r in mc.reasons)
    )
    tags = [["fees"] if i < 6 else ["reviews"] for i in range(12)]
    cand = runs([1.0] * 6 + [0.7] * 6, tags=tags)
    sl = _decide(cand, runs([0.9] * 12, tags=tags), specs, margin=1.0, slice_margin=0.1)
    assert (
        sl.decision == "FAIL"
        and [s.tag for s in sl.slices if not s.ok] == ["reviews"]
        and sl.slices[0].delta == pytest.approx(0.1)
    )
    jv: list[bool | None] = [i >= 3 for i in range(12)]
    js = _decide(
        runs([0.9] * 12, json_valid=jv),
        runs([0.9] * 12, json_valid=[True] * 12),
        specs,
        margin=1.0,
    )
    assert (
        js.decision == "FAIL"
        and js.json_validity["candidate"] == 0.75
        and any("JSON validity" in r for r in js.reasons)
    )
    cost = _decide(runs([0.9] * 12, cost=0.001), runs([0.9] * 12, cost=0.0005), specs)
    assert (
        cost.decision == "FAIL"
        and cost.cost["ratio"] == 2.0
        and any("cost" in r for r in cost.reasons)
    )
    lat = _decide(
        runs([0.9] * 12, latency=500.0),
        runs([0.9] * 12, latency=100.0),
        specs,
        latency_p95_budget_ms=200.0,
    )
    assert lat.decision == "FAIL" and any("latency p95 500" in r for r in lat.reasons)
    ratio = _decide(
        runs([0.9] * 12, latency=500.0),
        runs([0.9] * 12, latency=100.0),
        specs,
        latency_budget_ratio=2.0,
    )
    assert ratio.decision == "FAIL" and any("x5.00" in r for r in ratio.reasons)
    few = decide(
        dataset(3),
        specs[0],
        specs[1],
        runs([0.9] * 3),
        runs([0.9] * 3),
        model_name="fake",
        config=GateConfig(min_cases=20),
    )
    assert few.decision == "INSUFFICIENT_DATA" and "only 3 paired cases" in few.reasons[0]
    judged = [r.model_copy(update={"judge_mean": 5.0}) for r in runs([0.9] * 12)]
    with_judge = decide(
        dataset(12),
        specs[0],
        specs[1],
        judged,
        runs([0.9] * 12),
        model_name="fake",
        config=GateConfig(min_cases=5, use_judge=True, n_boot=100),
    )
    assert with_judge.judge["used"] and with_judge.paired["mean_candidate"] == pytest.approx(
        0.5 * 0.9 + 0.5 * 1.0, abs=1e-3
    )
    assert "Judge:" in render_markdown(with_judge)


def _curated_dataset(
    registry: PromptRegistry, tmp_path: Path, *, seed: int = 1, minutes: int = 40
) -> Dataset:
    store = TraceStore(":memory:")
    run_traffic(
        tiny_scenario(incidents=[]), seed=seed, minutes=minutes, store=store, registry=registry
    )
    cases = [
        curate_from_trace(t, reviewer="r", now=1.0)
        for t in store.query(status="ok", limit=200)
        if not t.attributes.get("guardrail.blocked")
    ]
    return DatasetStore(tmp_path / "ds").build("adviser_assistant", cases[:80], now="now")


def test_run_gate_end_to_end_good_and_bad_candidate(
    registry: PromptRegistry, tmp_path: Path
) -> None:
    ds = _curated_dataset(registry, tmp_path)
    good = run_gate(
        ds,
        candidate="adviser_assistant@v2",
        baseline="adviser_assistant@v1",
        model=DemoFakeModel(),
        registry=registry,
        config=GateConfig(n_boot=300),
    )
    assert good.decision == "PASS" and good.paired["delta"] >= 0 and good.n_cases == len(ds.cases)
    fees = [s for s in good.slices if s.tag == "fees"]
    assert not fees or fees[0].delta >= 0
    bad = run_gate(
        ds,
        candidate="adviser_assistant@v2-regressed",
        baseline="adviser_assistant@v1",
        model=DemoFakeModel(),
        registry=registry,
        config=GateConfig(n_boot=300),
    )
    assert (
        bad.decision == "FAIL"
        and bad.paired["delta"] < 0
        and bad.mcnemar["losses"] > bad.mcnemar["wins"]
    )
    judged = run_gate(
        ds,
        candidate="adviser_assistant@v2",
        baseline="adviser_assistant@v1",
        model=DemoFakeModel(),
        registry=registry,
        config=GateConfig(n_boot=100, use_judge=True),
        judge=FakeJudgeModel(invalid_rate=0.2),
    )
    assert judged.judge["used"] and judged.judge["missing_candidate"] >= 0
    md = render_markdown(bad)
    assert "cand refused" in md or "cand ungrounded" in md


def test_run_case_handles_model_error(registry: PromptRegistry) -> None:
    class Failing:
        name = "failing"

        def chat(
            self,
            messages: Sequence[ChatMessage],  # noqa: ARG002 - protocol signature
            *,
            max_tokens: int = 400,  # noqa: ARG002
            temperature: float = 0.0,  # noqa: ARG002
        ) -> ChatResponse:
            raise ModelError("down", kind="provider")

    case = (
        dataset(1)
        .cases[0]
        .model_copy(
            update={
                "context": {
                    "prompt_variables": {
                        "adviser_name": "A",
                        "today": "2026-09-01",
                        "client_name": "C",
                        "risk_profile": "Balanced",
                    }
                }
            }
        )
    )
    from opsloop.sdk.pricing import PriceTable

    result = run_case(case, registry.get("adviser_assistant@v1"), Failing(), prices=PriceTable())
    assert result.error == "down" and result.quality == 0.0 and not result.passed


# ----- canary -------------------------------------------------------------------------------


def test_assignment_is_deterministic_and_roughly_uniform() -> None:
    assert assign("session-1", 10) == assign("session-1", 10) and 0 <= bucket("x") < 100
    canary = sum(1 for i in range(2000) if assign(f"s{i}", 10) == "canary")
    assert 150 < canary < 250
    release = PromptRelease(active="v1", canary=CanaryState(version="v2", stage=100))
    assert resolve_version(release, "any") == "v2"
    assert resolve_version(PromptRelease(active="v1"), "any") == "v1"
    assert (
        resolve_version(
            PromptRelease(active="v1", canary=CanaryState(version="v2", stage=0)), "any"
        )
        == "v1"
    )


def _rows(
    version: str, n: int, *, errors: int = 0, refusals: int = 0, quality: float = 0.95
) -> list[TraceRow]:
    out = []
    for i in range(n):
        err = i < errors
        out.append(
            TraceRow(
                trace_id=f"{version}-{i}",
                session_id="s",
                prompt_version=version,
                start_ts=DEMO_EPOCH + i,
                end_ts=DEMO_EPOCH + i + 1,
                latency_ms=1000.0,
                status="error" if err else "ok",
                error_class="timeout" if err else None,
                input_text="q",
                output_text="a",
                prompt_tokens=1,
                completion_tokens=1,
                cost_usd=0.0003,
                cost_missing=False,
                json_expected=False,
                quality=None if err else quality,
                judge=None,
                refusal=None if err else (errors <= i < errors + refusals),
                json_valid=None,
                pii_leak=False,
                grounded=True,
                negative_feedback=False,
                attributes={},
            )
        )
    return out


def test_evaluate_canary_hold_advance_rollback_promote() -> None:
    policy = CanaryPolicy(min_samples=50, n_boot=200)
    release = PromptRelease(active="v1", canary=CanaryState(version="v2", stage=10))
    hold = evaluate_canary(_rows("v2", 20) + _rows("v1", 200), release, policy)
    assert hold.action == "hold" and "insufficient" in hold.reasons[0]
    good = evaluate_canary(_rows("v2", 100) + _rows("v1", 300), release, policy)
    assert good.action == "advance" and good.to_stage == 50 and good.tests["error_rate"]["p"] > 0.05
    errors = evaluate_canary(
        _rows("v2", 100, errors=15) + _rows("v1", 300, errors=1), release, policy
    )
    assert (
        errors.action == "rollback" and "error rate" in errors.reasons[0] and errors.to_stage == 0
    )
    refusals = evaluate_canary(
        _rows("v2", 100, refusals=20) + _rows("v1", 300, refusals=3), release, policy
    )
    assert refusals.action == "rollback" and "refusal rate" in refusals.reasons[0]
    quality = evaluate_canary(
        _rows("v2", 100, quality=0.7) + _rows("v1", 300, quality=0.95), release, policy
    )
    assert (
        quality.action == "rollback"
        and "quality mean" in quality.reasons[0]
        and quality.tests["quality_mean"]["ci_high"] < -0.05
    )
    final = PromptRelease(
        active="v1", canary=CanaryState(version="v2", stage=100), stages=[10, 50, 100]
    )
    promote = evaluate_canary(_rows("v2", 100) + _rows("v1", 100), final, policy)
    assert promote.action == "promote" and promote.to_stage == 100
    historical = evaluate_canary(_rows("v2", 100), final, policy, control_rows=_rows("v1", 80))
    assert historical.action == "promote" and historical.control["n"] == 80
    assert evaluate_canary(_rows("v2", 100), final, policy).action == "hold"
    assert evaluate_canary([], PromptRelease(active="v1"), policy).action == "hold"
    metrics = cohort_metrics([], "v9")
    assert (
        metrics.n == 0
        and metrics.as_dict()["quality_mean"] is None
        and metrics.as_dict()["latency_p95_ms"] is None
    )


def test_release_lifecycle_and_file(tmp_path: Path) -> None:
    rf = ReleaseFile.load(PROMPTS_DIR / "releases.yaml")
    rel = rf.get("prod", "adviser_assistant")
    assert rel.active == "v1" and rel.model_dump()["canary"] is None
    assert rf.policy.min_samples == 100
    with pytest.raises(KeyError):
        rf.get("prod", "nope")
    with pytest.raises(ValueError):
        advance(rel, now=1.0)
    with pytest.raises(ValueError):
        rollback(rel, now=1.0)
    start_canary(rel, "v2", now=1.0)
    started = rel.canary
    assert started is not None and started.stage == 10 and rel.history[-1]["event"] == "start"
    assert advance(rel, now=2.0) == 50 and advance(rel, now=3.0) == 100
    assert (
        advance(rel, now=4.0) == 100
        and rel.active == "v2"
        and rel.model_dump()["canary"] is None
        and rel.history[-1]["event"] == "promote"
    )
    start_canary(rel, "v2-regressed", now=5.0, stage=50)
    assert (
        rollback(rel, now=6.0, reason="bad") == "v2-regressed"
        and rel.model_dump()["canary"] is None
        and rel.history[-1]["reason"] == "bad"
    )
    start_canary(rel, "v3", now=7.0)
    apply_decision(
        rel,
        evaluate_canary(
            _rows("v3", 100, errors=20) + _rows("v2", 300),
            PromptRelease(active="v2", canary=rel.canary),
            CanaryPolicy(min_samples=50),
        ),
        now=8.0,
    )
    assert rel.model_dump()["canary"] is None and rel.history[-1]["event"] == "rollback"
    start_canary(rel, "v3", now=9.0)
    apply_decision(
        rel,
        evaluate_canary(
            _rows("v3", 100) + _rows("v2", 300),
            PromptRelease(active="v2", canary=rel.canary),
            CanaryPolicy(min_samples=50),
        ),
        now=10.0,
    )
    advanced = rel.canary
    assert advanced is not None and advanced.stage == 50
    apply_decision(rel, evaluate_canary([], rel, CanaryPolicy()), now=11.0)  # hold: no change
    assert rel.model_dump()["canary"]["stage"] == 50
    out = tmp_path / "rel" / "releases.yaml"
    rf.save(out)
    assert ReleaseFile.load(out).get("prod", "adviser_assistant").canary is not None
