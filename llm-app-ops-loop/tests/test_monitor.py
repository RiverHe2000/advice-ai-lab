"""SLO window mathematics against hand-computed values, burn-rate alerts that need both
windows, floors, escalation, the full-window rule, topic drift on a synthetic shift, the
monitor end to end, the self-evaluation on a tiny scenario, and the Prometheus exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from opsloop.monitor.alerts import burn_rate_alert, floor_alert
from opsloop.monitor.config import BurnWindow, DriftConfig, MonitorConfig, SloSpec
from opsloop.monitor.core import Evaluation, Monitor, MonitorState, alerts_table
from opsloop.monitor.drift import (
    HashingEmbedder,
    TopicModel,
    bootstrap_js_threshold,
    build_embedder,
    drift_test,
    tokens,
)
from opsloop.monitor.evaluate import evaluate_monitor, render_markdown, score_run, summarise
from opsloop.monitor.exporter import build_metrics, metrics_app, refresh
from opsloop.monitor.slo import RowWindow, eligible_and_bad, evaluate_slo, window_summary
from opsloop.prompts.registry import PromptRegistry
from opsloop.store import TraceRow, TraceStore
from opsloop.timeutil import DEMO_EPOCH
from tests.conftest import SLO_PATH, tiny_scenario


def row(i: int, **overrides: object) -> TraceRow:
    base = {
        "trace_id": f"t{i}",
        "session_id": "s",
        "prompt_version": "v1",
        "start_ts": DEMO_EPOCH + i * 10.0,
        "end_ts": DEMO_EPOCH + i * 10.0 + 1.0,
        "latency_ms": 1000.0,
        "status": "ok",
        "error_class": None,
        "input_text": f"What is client {i}'s total balance across all accounts?",
        "output_text": "answer",
        "prompt_tokens": 500,
        "completion_tokens": 50,
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
    base.update(overrides)
    return TraceRow(**base)  # type: ignore[arg-type]


def test_indicators_eligibility_and_badness() -> None:
    lat = SloSpec(name="l", indicator="latency", threshold=2500, budget=0.05)
    assert eligible_and_bad(lat, row(0, latency_ms=3000)) == (True, True)
    assert eligible_and_bad(lat, row(0, latency_ms=100)) == (True, False)
    assert eligible_and_bad(lat, row(0, status="error", latency_ms=30_000)) == (False, False)
    err = SloSpec(name="e", indicator="error", budget=0.01)
    assert eligible_and_bad(err, row(0, status="error")) == (True, True)
    cost = SloSpec(name="c", indicator="cost", threshold=0.0005, budget=0.1)
    assert eligible_and_bad(cost, row(0, cost_usd=None)) == (False, False)
    assert eligible_and_bad(cost, row(0, cost_usd=0.001)) == (True, True)
    quality = SloSpec(name="q", indicator="quality", threshold=0.75, budget=0.1)
    assert eligible_and_bad(quality, row(0, quality=None)) == (False, False)
    assert eligible_and_bad(quality, row(0, quality=0.5)) == (True, True)
    judge = SloSpec(name="j", indicator="judge", threshold=3.5, budget=0.1)
    assert eligible_and_bad(judge, row(0)) == (False, False) and eligible_and_bad(
        judge, row(0, judge=2.0)
    ) == (True, True)
    refusal = SloSpec(name="r", indicator="refusal", budget=0.06)
    assert eligible_and_bad(refusal, row(0, refusal=True)) == (True, True) and eligible_and_bad(
        refusal, row(0, status="error")
    ) == (False, False)
    nf = SloSpec(name="n", indicator="negative_feedback", budget=0.1)
    assert eligible_and_bad(nf, row(0, negative_feedback=True)) == (True, True)
    js = SloSpec(name="js", indicator="invalid_json", budget=0.05)
    assert eligible_and_bad(js, row(0)) == (False, False) and eligible_and_bad(
        js, row(0, json_expected=True, json_valid=False)
    ) == (True, True)
    pii = SloSpec(name="p", indicator="pii_leak", budget=0.005)
    assert eligible_and_bad(pii, row(0, pii_leak=True)) == (True, True) and eligible_and_bad(
        pii, row(0, pii_leak=None)
    ) == (False, False)
    gr = SloSpec(name="g", indicator="grounding", budget=0.1)
    assert eligible_and_bad(gr, row(0, grounded=False)) == (True, True) and eligible_and_bad(
        gr, row(0, grounded=None)
    ) == (False, False)


def test_evaluate_slo_hand_computed_and_window_slicing() -> None:
    rows = [row(i, status="error" if i % 5 == 0 else "ok") for i in range(20)]
    err = SloSpec(name="error_rate", indicator="error", budget=0.01)
    v = evaluate_slo(err, rows)
    assert v.n == 20 and v.bad == 4 and v.fraction == 0.2 and v.burn == pytest.approx(20.0)
    assert v.examples == ("t0", "t5", "t10", "t15") and v.as_dict()["burn"] == 20.0
    empty = evaluate_slo(err, [])
    assert not empty.evaluable and empty.as_dict()["fraction"] is None
    window = RowWindow(rows)
    assert len(window) == 20 and [
        r.trace_id for r in window.between(DEMO_EPOCH + 5, DEMO_EPOCH + 30)
    ] == ["t1", "t2", "t3"]
    summary = window_summary(rows)
    assert (
        summary["requests"] == 20
        and summary["error_rate"] == 0.2
        and summary["by_error_class"] == {"None": 4}
    )
    assert (
        summary["quality_mean"] == 0.95
        and summary["judged"] == 0
        and window_summary([])["error_rate"] is None
    )


def test_burn_rate_alert_requires_both_windows_and_min_bad_events() -> None:
    slo = SloSpec(name="error_rate", indicator="error", budget=0.01, min_requests=10)
    window = BurnWindow(
        name="fast",
        long_minutes=30,
        short_minutes=5,
        burn_rate=2.0,
        severity="critical",
        min_bad_events=3,
    )
    long_bad = [row(i, status="error" if i < 6 else "ok") for i in range(60)]
    short_bad = long_bad[:10]
    alert = burn_rate_alert(slo, window, long_bad, short_bad, as_of=1.0)
    assert alert is not None and alert.severity == "critical" and alert.value == pytest.approx(10.0)
    assert (
        alert.evidence["long"]["bad"] == 6
        and alert.evidence["short"]["bad"] == 6
        and "burn" in alert.message
    )
    short_quiet = long_bad[-10:]
    assert burn_rate_alert(slo, window, long_bad, short_quiet, as_of=1.0) is None
    assert (
        burn_rate_alert(slo, window, long_bad, short_bad[:2], as_of=1.0) is None
    )  # short window too thin
    assert (
        burn_rate_alert(slo, window, long_bad[:5], short_bad, as_of=1.0) is None
    )  # long window too thin
    two_bad = [row(i, status="error" if i < 2 else "ok") for i in range(60)]
    assert (
        burn_rate_alert(slo, window, two_bad, two_bad[:5], as_of=1.0) is None
    )  # burn high, but < min_bad_events


def test_floor_alert() -> None:
    slo = SloSpec(
        name="refusal_rate", indicator="refusal", budget=0.06, floor=0.01, min_requests=10
    )
    window = BurnWindow(name="slow", long_minutes=120, short_minutes=15, burn_rate=1.0)
    none_refused = [row(i) for i in range(50)]
    alert = floor_alert(slo, window, none_refused, as_of=2.0)
    assert alert is not None and alert.name == "refusal_rate_low" and alert.kind == "floor"
    assert floor_alert(slo, window, [row(i, refusal=i == 0) for i in range(50)], as_of=2.0) is None
    assert floor_alert(slo, window, none_refused[:5], as_of=2.0) is None
    assert (
        floor_alert(
            SloSpec(name="x", indicator="refusal", budget=0.1), window, none_refused, as_of=2.0
        )
        is None
    )


def _config(**drift: object) -> MonitorConfig:
    return MonitorConfig(
        step_minutes=5,
        baseline_minutes=20,
        escalation_consecutive=2,
        windows=[
            BurnWindow(
                name="page",
                long_minutes=10,
                short_minutes=2,
                burn_rate=3.0,
                severity="critical",
                min_bad_events=3,
            ),
            BurnWindow(
                name="slow",
                long_minutes=30,
                short_minutes=5,
                burn_rate=1.0,
                severity="warning",
                min_bad_events=3,
            ),
        ],
        drift=DriftConfig(
            **{"enabled": True, "window_minutes": 10, "min_requests": 20, "n_boot": 100, **drift}
        ),
        slos=[
            SloSpec(name="error_rate", indicator="error", budget=0.01, min_requests=10),
            SloSpec(
                name="refusal_rate", indicator="refusal", budget=0.06, floor=0.001, min_requests=10
            ),
        ],
    )


def test_monitor_full_window_rule_escalation_and_state(tmp_path: Path) -> None:
    rows = [
        row(i, status="error" if (i * 10.0) >= 1500 else "ok", refusal=i % 20 == 0)
        for i in range(240)
    ]  # errors from minute 25
    cfg = _config(enabled=False)
    monitor = Monitor(
        cfg, lambda t0, t1: [r for r in rows if t0 < r.start_ts <= t1], start_ts=DEMO_EPOCH
    )
    early = monitor.evaluate(DEMO_EPOCH + 5 * 60)  # no window is full yet
    assert early.alerts == [] and early.n_requests == 31 and "error_rate" in early.indicators
    evs = monitor.run(DEMO_EPOCH, DEMO_EPOCH + 40 * 60)
    assert [round((e.as_of - DEMO_EPOCH) / 60) for e in evs] == [5, 10, 15, 20, 25, 30, 35, 40]
    names = [sorted(e.alert_names) for e in evs]
    assert names[:5] == [[], [], [], [], []]
    assert "error_rate" in names[5] and "error_rate" in names[7]
    first = next(a for a in evs[5].alerts if a.name == "error_rate")
    later = next(a for a in evs[7].alerts if a.name == "error_rate")
    assert first.consecutive == 1 and later.consecutive == 3 and later.severity == "critical"
    warn_slo = MonitorConfig(
        **{
            **cfg.model_dump(),
            "windows": [
                BurnWindow(
                    name="w", long_minutes=10, short_minutes=2, burn_rate=1.0, severity="warning"
                )
            ],
        }
    )
    m2 = Monitor(
        warn_slo, lambda t0, t1: [r for r in rows if t0 < r.start_ts <= t1], start_ts=DEMO_EPOCH
    )
    a1 = m2.evaluate(DEMO_EPOCH + 35 * 60).alerts[0]
    a2 = m2.evaluate(DEMO_EPOCH + 40 * 60).alerts[0]
    assert a1.severity == "warning" and a2.severity == "critical" and a2.consecutive == 2
    m2.state.save(tmp_path / "state.json")
    loaded = MonitorState.load(tmp_path / "state.json")
    assert loaded.consecutive["error_rate"] == 2 and loaded.last_as_of == a2.as_of
    assert MonitorState.load(tmp_path / "nope.json").consecutive == {}
    table = alerts_table(evs, DEMO_EPOCH)
    assert "| 30 | error_rate (critical, page) |" in table and "| 5 | - |" in table
    assert isinstance(evs[0], Evaluation)


def test_monitor_floor_uses_slowest_window_only() -> None:
    rows = [row(i) for i in range(240)]  # nobody refuses
    cfg = _config(enabled=False)
    monitor = Monitor(
        cfg, lambda t0, t1: [r for r in rows if t0 < r.start_ts <= t1], start_ts=DEMO_EPOCH
    )
    assert monitor.evaluate(DEMO_EPOCH + 15 * 60).alerts == []  # slow window not full yet
    low = monitor.evaluate(DEMO_EPOCH + 35 * 60).alerts
    assert [a.name for a in low] == ["refusal_rate_low"]


FIRST = ["Amelia", "Ben", "Chloe", "Dev", "Ella", "Finn", "Grace", "Hugo", "Isla", "Jack", "Kai"]
LAST = ["Abbott", "Barlow", "Chen", "Dubois", "Evans", "Fitz", "Gomez"]


def _texts(offset: str, n: int) -> list[str]:
    """Questions from four templates with names drawn from the same small pools (``offset``
    only shifts which names go with which template, so both sets share one distribution)."""
    kinds = [
        "What is {c}'s total balance across all accounts?",
        "What are the total annual fees on {c}'s accounts?",
        "When is {c}'s next review due?",
        "How much concessional contribution room does {c} have this financial year?",
    ]
    shift = len(offset)
    return [
        kinds[i % 4].format(
            c=f"{FIRST[(i + shift) % len(FIRST)]} {LAST[(i // 3 + shift) % len(LAST)]}"
        )
        for i in range(n)
    ]


def test_hashing_embedder_and_topic_model() -> None:
    emb = HashingEmbedder(64)
    x = emb.embed(["total balance across accounts", "total balance across accounts", "fees"])
    assert (
        x.shape == (3, 64) and abs(float((x[0] * x[0]).sum()) - 1.0) < 1e-9 and (x[0] == x[1]).all()
    )
    assert tokens("What is the client's TOTAL balance?") == ["client's", "total", "balance"]
    assert emb.embed([], vocab=None).shape == (0, 64) and isinstance(
        build_embedder("hashing"), HashingEmbedder
    )
    model = TopicModel(emb, k=4, seed=0, min_df=2).fit(_texts("base", 80))
    assert model.n_topics == 5 and model.novel_index == 4 and model.vocab is not None
    labels = model.assign(_texts("base", 8))
    assert labels.shape == (8,) and len(model.top_terms(_texts("base", 8), labels)) == 5
    assert model.assign([]).shape == (0,)
    with pytest.raises(RuntimeError):
        TopicModel(emb, k=2).assign(["x"])
    with pytest.raises(RuntimeError):
        drift_test(TopicModel(emb, k=2), ["x"])
    assert bootstrap_js_threshold([0, 0], 10, n_boot=10, quantile=0.9, seed=0) == float("inf")


def test_drift_detects_synthetic_shift_and_not_noise() -> None:
    model = TopicModel(HashingEmbedder(), k=4, seed=0).fit(_texts("base", 200))
    same = drift_test(model, _texts("other", 100), n_boot=100, seed=1)
    assert not same.drifted and same.n_current == 100
    novel = [
        f"What Centrelink Age Pension would Novel Person{i} be entitled to under the assets test?"
        for i in range(60)
    ]
    shifted = drift_test(model, _texts("other", 40) + novel, n_boot=100, seed=1)
    assert shifted.drifted and shifted.js > shifted.threshold and shifted.p_value < 0.01
    assert shifted.grown and shifted.grown[0].novel and "centrelink" in shifted.grown[0].terms
    assert drift_test(model, [], n_boot=10).grown == []


def test_monitor_topic_drift_alert(registry: PromptRegistry) -> None:
    from opsloop.demo.scenario import Incident
    from opsloop.demo.traffic import run_traffic

    store = TraceStore(":memory:")
    sc = tiny_scenario(
        incidents=[
            Incident(kind="topic_shift", start_minute=30, end_minute=70, params={"share": 0.7})
        ]
    )
    run_traffic(sc, seed=4, minutes=70, store=store, registry=registry)
    monitor = Monitor(_config(), store.rows, start_ts=DEMO_EPOCH)
    assert monitor.baseline == (DEMO_EPOCH, DEMO_EPOCH + 20 * 60)
    evs = monitor.run(DEMO_EPOCH, DEMO_EPOCH + 70 * 60)
    drift_ticks = [
        round((e.as_of - DEMO_EPOCH) / 60) for e in evs if "topic_drift" in e.alert_names
    ]
    assert drift_ticks and min(drift_ticks) >= 35 and min(drift_ticks) <= 50
    alert = next(a for e in evs for a in e.alerts if a.name == "topic_drift")
    assert alert.kind == "drift" and alert.evidence["grown"] and "grown:" in alert.message
    assert evs[3].drift is None  # 20 min: current window overlaps the baseline
    thin = Monitor(_config(min_requests=10_000), store.rows, start_ts=DEMO_EPOCH)
    assert thin.evaluate(DEMO_EPOCH + 60 * 60).drift is None
    no_baseline = Monitor(_config(), store.rows)
    assert no_baseline.baseline is None and no_baseline.evaluate(DEMO_EPOCH + 60 * 60).drift is None


def test_self_evaluation_on_tiny_scenario(registry: PromptRegistry) -> None:
    cfg = _config(enabled=False)
    report = evaluate_monitor(
        [tiny_scenario(), tiny_scenario(name="quiet", incidents=[])],
        seeds=[1],
        minutes=60,
        config=cfg,
        registry=registry,
        n_boot=50,
    )
    kind = report.kinds[0]
    assert (
        kind.kind == "error_burst"
        and kind.detected == 1
        and kind.ttd_mean is not None
        and kind.ttd_mean <= 10
    )
    assert (
        report.quiet_ticks > 0
        and report.false_alarm_rate <= 0.2
        and report.gate["passed"] is (report.false_alarm_rate <= 0.05)
    )
    md = render_markdown(report)
    assert "| error_burst | 1 | 1 |" in md and "Quiet ticks per run" in md
    run = report.runs[0]
    assert run.incidents[0].first_alert == "error_rate" and run.quiet_ticks == sum(
        1 for t in run.alert_timeline if not t["incident_active"] and 10 <= t["minute"] < 40
    )
    missed = summarise(
        [
            run.model_copy(
                update={
                    "incidents": [
                        run.incidents[0].model_copy(
                            update={"detected": False, "time_to_detect_minutes": None}
                        )
                    ]
                }
            )
        ],
        minutes=60,
        seeds=[1],
        scenarios=["tiny"],
        min_detection=0.9,
        max_false_alarm=0.05,
        n_boot=20,
    )
    assert (
        missed.kinds[0].ttd_mean is None
        and missed.gate["passed"] is False
        and "| - |" in render_markdown(missed)
    )


def test_score_run_shadow_and_warmup(registry: PromptRegistry) -> None:
    from opsloop.demo.traffic import TrafficSummary

    sc = tiny_scenario()
    evs = [
        Evaluation(as_of=DEMO_EPOCH + m * 60, n_requests=1, indicators={}, alerts=[])
        for m in range(5, 65, 5)
    ]
    fake_alert = __import__("opsloop.monitor.alerts", fromlist=["Alert"]).Alert(
        name="error_rate",
        severity="critical",
        kind="burn_rate",
        window="page",
        value=5.0,
        threshold=3.0,
        as_of=DEMO_EPOCH + 20 * 60,
    )
    evs[3] = evs[3].model_copy(update={"alerts": [fake_alert]})  # minute 20: a false alarm
    out = score_run(
        sc,
        1,
        evs,
        start_ts=DEMO_EPOCH,
        shadow_minutes=30,
        summary=TrafficSummary("tiny", 1, DEMO_EPOCH, DEMO_EPOCH + 3600, 60, n_requests=10),
        warmup_minutes=10,
    )
    assert (
        out.quiet_ticks == 6
        and out.quiet_ticks_with_alert == 1
        and out.false_alarms_by_name == {"error_rate": 1}
    )
    assert out.incidents[0].detected is False


def test_exporter_refresh_and_metrics_app(traffic_store: TraceStore, config: MonitorConfig) -> None:
    metrics = build_metrics()
    assert refresh(metrics, TraceStore(":memory:"), config) is None
    ev = refresh(metrics, traffic_store, config)
    assert ev is not None and ev.n_requests > 0
    app = metrics_app(traffic_store, config, metrics=metrics)
    client = TestClient(app)
    text = client.get("/metrics").text
    assert (
        'opsloop_slo_burn_rate{slo="error_rate"}' in text
        and 'opsloop_alert_active{name="error_rate",severity="critical"}' in text
    )
    assert "opsloop_latency_p95_ms" in text and "opsloop_topic_drift_js" in text
    assert client.get("/health").json()["traces"] == traffic_store.count()


def test_config_loads_and_lookup() -> None:
    cfg = MonitorConfig.load(SLO_PATH)
    assert cfg.slo("error_rate").budget == 0.01 and cfg.max_window_minutes == 120
    assert cfg.slo("json_validity").short_min == 2 and cfg.slo("error_rate").short_min == 5
    with pytest.raises(KeyError):
        cfg.slo("nope")
    assert MonitorConfig().windows[0].name == "page"
    data = json.loads(json.dumps(cfg.model_dump(mode="json")))
    assert data["drift"]["novelty_quantile"] == 0.95
