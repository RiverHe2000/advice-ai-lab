"""``opsloop`` command line: demo traffic, collector, monitor, sampling and judging, feedback,
curation, datasets, prompts, the regression gate, releases, replay, incident reports, store
maintenance. JSON to stdout, reports to ``--out``; exit codes carry gate decisions."""

from __future__ import annotations

import argparse
import contextlib
import dataclasses
import json
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from opsloop import __version__
from opsloop.config import Settings
from opsloop.dataset.curate import build_review_queue, read_review_queue, write_review_queue
from opsloop.dataset.versioning import DatasetStore
from opsloop.demo.model import DemoFakeModel
from opsloop.demo.scenario import load_scenario, load_scenarios
from opsloop.demo.traffic import run_traffic
from opsloop.feedback import add_feedback, build_feedback
from opsloop.incident import build_incident_report
from opsloop.incident import render_markdown as render_incident
from opsloop.llm import ChatModel, build_model
from opsloop.monitor.config import MonitorConfig
from opsloop.monitor.core import Monitor, MonitorState, alerts_table
from opsloop.monitor.evaluate import evaluate_monitor
from opsloop.monitor.evaluate import render_markdown as render_evaluation
from opsloop.prompts.registry import PromptRegistry, parse_ref
from opsloop.quality.judge import FakeJudgeModel, judge_and_store, judge_summary
from opsloop.quality.sampling import sample_traces
from opsloop.regression.gate import GateConfig, run_gate
from opsloop.regression.gate import render_markdown as render_gate
from opsloop.release.canary import (
    ReleaseFile,
    advance,
    apply_decision,
    evaluate_canary,
    rollback,
    start_canary,
)
from opsloop.replay import render_markdown as render_replay
from opsloop.replay import replay_trace
from opsloop.sdk.pricing import PriceTable
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH, from_iso, iso, parse_duration


def _configure_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(errors="replace")


def _print(payload: Any) -> None:
    sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")


def _write(path: Path | None, text: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _settings(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    for key in (
        "store_path",
        "prompts_dir",
        "releases_path",
        "slo_path",
        "datasets_dir",
        "environment",
    ):
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    return Settings(**overrides)


def _store(args: argparse.Namespace, *, reset: bool = False) -> TraceStore:
    path = _settings(args).store_path
    if reset and str(path) != ":memory:" and Path(path).exists():
        Path(path).unlink()
    return TraceStore(path)


def _registry(args: argparse.Namespace) -> PromptRegistry:
    return PromptRegistry(_settings(args).prompts_dir)


def _config(args: argparse.Namespace) -> MonitorConfig:
    return MonitorConfig.load(_settings(args).slo_path)


def _prices(args: argparse.Namespace) -> PriceTable:
    path = _settings(args).pricing_path
    return PriceTable.from_yaml(path) if path else PriceTable()


def _model(args: argparse.Namespace, *, judge: bool = False) -> ChatModel:
    kind = getattr(args, "model", None) or "fake"
    fake: ChatModel
    if judge:
        fake = FakeJudgeModel(
            invalid_rate=float(getattr(args, "judge_invalid_rate", 0.0) or 0.0),
            seed=int(getattr(args, "seed", 0) or 0),
        )
    else:
        fake = DemoFakeModel(seed=int(getattr(args, "seed", 0) or 0))
    model = build_model(
        kind,
        model_name=getattr(args, "model_name", None),
        base_url=getattr(args, "base_url", None),
        api_key=getattr(args, "api_key", None),
        fake=fake,
    )
    cache = getattr(args, "cache", None)
    if cache is not None and kind != "fake":
        from opsloop.cache import CachedChatModel

        return CachedChatModel(model, cache)
    return model


def _anchor(store: TraceStore, args: argparse.Namespace) -> tuple[float, float]:
    """(since, until) from --since/--until ISO or --window relative to the newest trace."""
    rng = store.time_range()
    until_arg = getattr(args, "until", None)
    since_arg = getattr(args, "since", None)
    until = from_iso(until_arg) if until_arg else (rng[1] + 1e-6 if rng else time.time())
    if since_arg:
        return from_iso(since_arg), until
    window = parse_duration(getattr(args, "window", None) or "4h")
    return until - window, until


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", choices=["fake", "openai", "hf"], default="fake")
    parser.add_argument("--model-name", dest="model_name", default=None)
    parser.add_argument("--base-url", dest="base_url", default=None)
    parser.add_argument("--api-key", dest="api_key", default=None)
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="SQLite response cache for real models; identical greedy requests are served from it",
    )
    parser.add_argument("--seed", type=int, default=0)


# ----- commands -----------------------------------------------------------------------------


def cmd_demo_traffic(args: argparse.Namespace) -> int:
    scenario = load_scenario(args.scenario)
    store = _store(args, reset=args.reset)
    registry = _registry(args)
    release = None
    if args.use_release:
        release = ReleaseFile.load(_settings(args).releases_path).get(
            _settings(args).environment, "adviser_assistant"
        )
    started = time.perf_counter()
    summary = run_traffic(
        scenario,
        seed=args.seed,
        minutes=args.minutes,
        store=store,
        registry=registry,
        start_ts=from_iso(args.start) if args.start else DEMO_EPOCH,
        release=release,
    )
    payload = {
        **summary.as_dict(),
        "wall_seconds": round(time.perf_counter() - started, 2),
        "store": str(_settings(args).store_path),
    }
    if args.collector_url:
        from opsloop.sdk.exporters import HttpExporter

        exporter = HttpExporter(args.collector_url)
        sent = 0
        for trace in store.query(limit=10_000_000):
            exporter(trace)
            sent += 1
        payload["posted_to_collector"] = sent
    _print(payload)
    if args.summary_out:
        _write(args.summary_out, json.dumps(payload, indent=2, default=str))
    store.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from opsloop.collector.api import create_app

    app = create_app(_store(args), config=_config(args))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_monitor_evaluate(args: argparse.Namespace) -> int:
    scenarios = load_scenarios(args.scenarios)
    report = evaluate_monitor(
        scenarios,
        seeds=args.seeds,
        minutes=args.minutes,
        config=_config(args),
        registry=_registry(args),
        min_detection=args.min_detection,
        max_false_alarm=args.max_false_alarm,
    )
    out = Path(args.out)
    _write(out / "monitor_evaluation.md", render_evaluation(report))
    _write(out / "monitor_evaluation.json", json.dumps(report.model_dump(mode="json"), indent=2))
    _print(
        {
            "kinds": [k.model_dump(exclude={"ttd_values"}) for k in report.kinds],
            "false_alarm_rate": report.false_alarm_rate,
            "false_alarm_ci": report.false_alarm_ci,
            "quiet_ticks": report.quiet_ticks,
            "gate": report.gate,
            "out": str(out),
        }
    )
    return 0 if (not args.gate or report.gate["passed"]) else 1


def cmd_monitor_run(args: argparse.Namespace) -> int:
    store = _store(args)
    rng = store.time_range()
    if rng is None:
        _print({"error": "store is empty"})
        return 2
    config = _config(args)
    state = MonitorState.load(args.state) if args.state else MonitorState()
    monitor = Monitor(config, store.rows, start_ts=rng[0], state=state)
    if args.as_of:
        evaluations = [monitor.evaluate(from_iso(args.as_of))]
    else:
        evaluations = monitor.run(rng[0], rng[1])
    if args.state:
        state.save(args.state)
    out = Path(args.out) if args.out else None
    if out is not None:
        _write(
            out / "evaluations.json",
            json.dumps([e.model_dump(mode="json") for e in evaluations], indent=2),
        )
        _write(out / "alerts.md", "# Alerts\n\n" + alerts_table(evaluations, rng[0]) + "\n")
    last = evaluations[-1]
    _print(
        {
            "ticks": len(evaluations),
            "as_of": iso(last.as_of),
            "alerts": [a.model_dump(exclude={"evidence"}) for a in last.alerts],
            "summary": last.summary,
            "drift": None if last.drift is None else last.drift.model_dump(exclude={"grown"}),
            "ticks_with_alerts": sum(1 for e in evaluations if e.alerts),
        }
    )
    return 3 if any(a.severity == "critical" for a in last.alerts) else (2 if last.alerts else 0)


def cmd_monitor_export(args: argparse.Namespace) -> int:
    import uvicorn

    from opsloop.monitor.exporter import metrics_app

    app = metrics_app(_store(args), _config(args))
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    store = _store(args)
    since, until = _anchor(store, args)
    rows = store.rows(since, until)
    sample = sample_traces(
        rows,
        budget=args.budget,
        seed=args.seed,
        exclude=store.judged_ids() if args.skip_judged else None,
        strategy=args.strategy,
    )
    payload = sample.as_dict()
    _print({k: v for k, v in payload.items() if k != "trace_ids"} | {"n": len(sample.trace_ids)})
    if args.out:
        _write(args.out, json.dumps(payload, indent=2))
    return 0


def cmd_judge(args: argparse.Namespace) -> int:
    store = _store(args)
    ids: list[str] = list(args.trace_ids or [])
    slo_eligible = bool(args.slo_eligible)
    if args.sample:
        sample = json.loads(Path(args.sample).read_text(encoding="utf-8"))
        ids += list(sample["trace_ids"])
        # Scores from a failure-targeted sample are stored for review but must not feed the
        # judged-quality SLO (selection bias); a uniform sample is representative.
        slo_eligible = slo_eligible or sample.get("strategy") == "uniform"
    if not ids:
        _print({"error": "no trace ids (use --sample or --trace-ids)"})
        return 2
    model = _model(args, judge=True)
    results = judge_and_store(store, model, ids, ts=time.time(), slo_eligible=slo_eligible)
    summary = {"model": model.name, "slo_eligible": slo_eligible, **judge_summary(results)}
    _print(summary)
    if args.out:
        _write(
            args.out,
            json.dumps({"summary": summary, "results": [r.as_dict() for r in results]}, indent=2),
        )
    return 0


def cmd_feedback_add(args: argparse.Namespace) -> int:
    store = _store(args)
    trace = store.get_trace(args.trace_id)
    if trace is None:
        _print({"error": f"trace {args.trace_id} not found"})
        return 2
    fb = build_feedback(
        args.trace_id,
        ts=time.time(),
        thumbs=args.thumbs,
        comment=args.comment,
        wrong_part=args.wrong_part,
        regenerated=args.regenerated,
        original_text=trace.output_text if args.edited_text else None,
        edited_text=args.edited_text,
    )
    row_id = add_feedback(store, fb)
    _print({"id": row_id, **fb.model_dump(mode="json")})
    return 0


def cmd_curate(args: argparse.Namespace) -> int:
    store = _store(args)
    ids = (
        list(json.loads(Path(args.sample).read_text(encoding="utf-8"))["trace_ids"])
        if args.sample
        else list(args.trace_ids or [])
    )
    items = build_review_queue(store, ids, reviewer=args.reviewer, now=time.time())
    if args.accept_all:
        for item in items:
            item.status = "accepted"
    n = write_review_queue(items, args.out)
    _print(
        {
            "queued": n,
            "out": str(args.out),
            "accepted": sum(1 for i in items if i.status == "accepted"),
        }
    )
    return 0


def cmd_dataset_build(args: argparse.Namespace) -> int:
    items = read_review_queue(args.from_review)
    cases = [i.case for i in items if i.status == "accepted" or args.accept_pending]
    ds = DatasetStore(_settings(args).datasets_dir)
    dataset = ds.build(
        args.name,
        cases,
        version=args.version,
        now=iso(time.time()),
        changelog=args.changelog or "",
        extend_previous=not args.fresh,
    )
    _print(dataset.manifest.model_dump(mode="json"))
    return 0


def cmd_dataset_list(args: argparse.Namespace) -> int:
    ds = DatasetStore(_settings(args).datasets_dir)
    out = []
    for name in ds.names():
        for v in ds.versions(name):
            m = ds.load(name, v).manifest
            out.append(
                {
                    "name": name,
                    "version": v,
                    "hash": m.content_hash,
                    "cases": m.n_cases,
                    "created": m.created,
                    "slices": m.slices,
                }
            )
    _print(out)
    return 0


def cmd_dataset_diff(args: argparse.Namespace) -> int:
    ds = DatasetStore(_settings(args).datasets_dir)
    _print(ds.diff(args.name, args.from_version, args.to_version))
    return 0


def cmd_prompt_register(args: argparse.Namespace) -> int:
    reg = _registry(args)
    spec = reg.register_file(Path(args.path), overwrite=args.overwrite)
    _print(
        {
            "ref": spec.ref,
            "content_hash": spec.content_hash,
            "path": str(reg.root / spec.name / f"{spec.version}.yaml"),
        }
    )
    return 0


def cmd_prompt_list(args: argparse.Namespace) -> int:
    reg = _registry(args)
    _print(
        [
            {"ref": s.ref, "hash": s.content_hash, "description": s.description, "inputs": s.inputs}
            for s in reg.list_prompts(args.name)
        ]
    )
    return 0


def cmd_prompt_diff(args: argparse.Namespace) -> int:
    sys.stdout.write(_registry(args).diff(args.ref_a, args.ref_b) + "\n")
    return 0


def cmd_prompt_render(args: argparse.Namespace) -> int:
    variables: dict[str, Any] = {}
    for item in args.var or []:
        key, _, value = item.partition("=")
        variables[key] = value
    spec = _registry(args).get(args.ref)
    for name in spec.inputs:
        variables.setdefault(name, f"<{name}>")
    sys.stdout.write(spec.render(variables) + "\n")
    return 0


def cmd_prompt_lint(args: argparse.Namespace) -> int:
    reg = _registry(args)
    refs = [args.ref] if args.ref else [s.ref for s in reg.list_prompts()]
    results = {ref: [dataclasses.asdict(f) for f in reg.lint(ref)] for ref in refs}
    _print(results)
    errors = sum(1 for fs in results.values() for f in fs if f["level"] == "error")
    return 1 if (args.gate and errors) else 0


def cmd_regress(args: argparse.Namespace) -> int:
    ds = DatasetStore(_settings(args).datasets_dir)
    ref = parse_ref(args.dataset)
    dataset = ds.load(ref.name, int(ref.version.lstrip("v")) if ref.version else None)
    limit = getattr(args, "limit", None)
    if limit:
        # The first N cases in dataset order (deterministic); used to fit a real-model run
        # into a GPU budget. The report records the number of cases actually compared.
        dataset = dataset.model_copy(update={"cases": dataset.cases[:limit]})
    cfg = GateConfig(
        margin=args.margin,
        slice_margin=args.slice_margin,
        json_validity_floor=args.json_floor,
        cost_budget_ratio=args.cost_budget,
        latency_p95_budget_ms=args.latency_budget_ms,
        min_cases=args.min_cases,
        seed=args.seed,
        use_judge=args.use_judge,
    )
    candidate = (
        args.candidate
        if "@" in args.candidate and not args.candidate.startswith("@")
        else f"adviser_assistant{args.candidate}"
    )
    baseline = (
        args.baseline
        if "@" in args.baseline and not args.baseline.startswith("@")
        else f"adviser_assistant{args.baseline}"
    )
    report = run_gate(
        dataset,
        candidate=candidate,
        baseline=baseline,
        model=_model(args),
        registry=_registry(args),
        config=cfg,
        judge=_model(args, judge=True) if args.use_judge else None,
        prices=_prices(args),
    )
    out = Path(args.out)
    _write(out / "report.md", render_gate(report))
    _write(out / "report.json", json.dumps(report.model_dump(mode="json"), indent=2))
    _print(
        {
            "decision": report.decision,
            "reasons": report.reasons,
            "paired": report.paired,
            "mcnemar": report.mcnemar,
            "slices": [s.model_dump() for s in report.slices],
            "json_validity": report.json_validity,
            "cost": report.cost,
            "out": str(out),
        }
    )
    return 0 if (not args.gate or report.decision == "PASS") else 1


def _release_ctx(args: argparse.Namespace) -> tuple[ReleaseFile, str, str, Path]:
    settings = _settings(args)
    path = settings.releases_path
    rf = ReleaseFile.load(path)
    return rf, settings.environment, args.name, path


def cmd_release_status(args: argparse.Namespace) -> int:
    rf, env, name, _ = _release_ctx(args)
    rel = rf.get(env, name)
    _print(
        {
            "environment": env,
            "prompt": name,
            **rel.model_dump(mode="json"),
            "policy": rf.policy.model_dump(),
        }
    )
    return 0


def cmd_release_start(args: argparse.Namespace) -> int:
    rf, env, name, path = _release_ctx(args)
    rel = rf.get(env, name)
    _registry(args).get(f"{name}@{args.version}")
    start_canary(rel, args.version, now=time.time(), stage=args.stage)
    rf.save(path)
    _print(rel.model_dump(mode="json"))
    return 0


def cmd_release_advance(args: argparse.Namespace) -> int:
    rf, env, name, path = _release_ctx(args)
    rel = rf.get(env, name)
    stage = advance(rel, now=time.time(), reason=args.reason)
    rf.save(path)
    _print({"stage": stage, **rel.model_dump(mode="json")})
    return 0


def cmd_release_rollback(args: argparse.Namespace) -> int:
    rf, env, name, path = _release_ctx(args)
    rel = rf.get(env, name)
    version = rollback(rel, now=time.time(), reason=args.reason)
    rf.save(path)
    _print({"rolled_back": version, **rel.model_dump(mode="json")})
    return 0


def cmd_release_auto(args: argparse.Namespace) -> int:
    rf, env, name, path = _release_ctx(args)
    rel = rf.get(env, name)
    store = _store(args)
    since, until = _anchor(store, args)
    rows = store.rows(since, until)
    control_rows = None
    in_window_control = [r for r in rows if r.prompt_version == rel.active]
    if rel.canary is not None and len(in_window_control) < rf.policy.min_samples:
        # Little or no concurrent control traffic (the 100 % stage): extend the control cohort
        # with the historical one - every earlier request served by the active version.
        control_rows = in_window_control + store.rows(None, since, prompt_version=rel.active)
    decision = evaluate_canary(rows, rel, rf.policy, seed=args.seed, control_rows=control_rows)
    if args.apply:
        apply_decision(rel, decision, now=time.time())
        rf.save(path)
    payload = {
        "environment": env,
        "prompt": name,
        **decision.model_dump(),
        "applied": args.apply,
        "release": rel.model_dump(mode="json"),
    }
    _print(payload)
    if args.out:
        _write(args.out, json.dumps(payload, indent=2))
    return {"advance": 0, "promote": 0, "hold": 2, "rollback": 3}[decision.action]


def cmd_replay(args: argparse.Namespace) -> int:
    store = _store(args)
    trace = store.get_trace(args.trace_id)
    if trace is None:
        _print({"error": f"trace {args.trace_id} not found"})
        return 2
    result = replay_trace(
        trace,
        _registry(args),
        _model(args),
        prices=_prices(args),
        prompt_version=args.prompt_version,
    )
    _print(result.model_dump(exclude={"diff", "recorded_answer", "new_answer"}))
    if args.out:
        _write(args.out, render_replay(result))
    return 0


def cmd_incident_report(args: argparse.Namespace) -> int:
    store = _store(args)
    since, until = _anchor(store, args)
    report = build_incident_report(
        store, since=since, until=until, bucket_minutes=args.bucket_minutes
    )
    _print(report.model_dump(exclude={"timeline", "by_topic"}))
    if args.out:
        _write(args.out, render_incident(report, title=args.title))
        _write(
            Path(str(args.out).rsplit(".", 1)[0] + ".json"),
            json.dumps(report.model_dump(mode="json"), indent=2),
        )
    return 0


def cmd_store_prune(args: argparse.Namespace) -> int:
    store = _store(args)
    now = from_iso(args.now) if args.now else time.time()
    cutoff = now - parse_duration(args.older_than)
    removed = store.prune(cutoff)
    _print({"removed": removed, "cutoff": iso(cutoff), "remaining": store.count()})
    return 0


def cmd_store_export(args: argparse.Namespace) -> int:
    store = _store(args)
    n = store.export_jsonl(args.out, since=from_iso(args.since) if args.since else None)
    _print({"exported": n, "out": str(args.out)})
    return 0


# ----- parser -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="opsloop", description=__doc__)
    p.add_argument("--version", action="version", version=f"opsloop {__version__}")
    p.add_argument("--store", dest="store_path", type=Path, default=None, help="SQLite trace store")
    p.add_argument("--prompts-dir", dest="prompts_dir", type=Path, default=None)
    p.add_argument("--releases", dest="releases_path", type=Path, default=None)
    p.add_argument("--slos", dest="slo_path", type=Path, default=None)
    p.add_argument("--datasets-dir", dest="datasets_dir", type=Path, default=None)
    p.add_argument("--environment", default=None)
    sub = p.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="scripted application traffic").add_subparsers(
        dest="sub", required=True
    )
    d = demo.add_parser("traffic", help="run a scenario in simulated time into the store")
    d.add_argument("--scenario", type=Path, required=True)
    d.add_argument("--minutes", type=float, default=240.0)
    d.add_argument("--seed", type=int, default=3)
    d.add_argument("--start", default=None, help="ISO start timestamp (default 2026-09-01T00:00Z)")
    d.add_argument("--reset", action="store_true", help="delete the store file first")
    d.add_argument(
        "--use-release",
        dest="use_release",
        action="store_true",
        help="assign prompt versions from releases.yaml",
    )
    d.add_argument(
        "--collector-url",
        dest="collector_url",
        default=None,
        help="also POST every trace to a collector",
    )
    d.add_argument("--summary-out", dest="summary_out", type=Path, default=None)
    d.set_defaults(func=cmd_demo_traffic)

    s = sub.add_parser("serve", help="run the collector API")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8090)
    s.set_defaults(func=cmd_serve)

    mon = sub.add_parser("monitor", help="SLOs, alerts, drift").add_subparsers(
        dest="sub", required=True
    )
    me = mon.add_parser("evaluate", help="measure the monitor against planted incidents")
    me.add_argument("--scenarios", type=Path, nargs="+", required=True)
    me.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    me.add_argument("--minutes", type=float, default=240.0)
    me.add_argument("--out", type=Path, default=Path("runs/monitor_evaluation"))
    me.add_argument("--gate", action="store_true")
    me.add_argument("--min-detection", dest="min_detection", type=float, default=0.9)
    me.add_argument("--max-false-alarm", dest="max_false_alarm", type=float, default=0.05)
    me.set_defaults(func=cmd_monitor_evaluate)
    mr = mon.add_parser("run", help="evaluate the SLOs over the store")
    mr.add_argument(
        "--as-of", dest="as_of", default=None, help="single evaluation at this ISO time"
    )
    mr.add_argument("--state", type=Path, default=None, help="consecutive-window state file")
    mr.add_argument("--out", type=Path, default=None)
    mr.set_defaults(func=cmd_monitor_run)
    mx = mon.add_parser("export", help="Prometheus exporter")
    mx.add_argument("--host", default="127.0.0.1")
    mx.add_argument("--port", type=int, default=9109)
    mx.set_defaults(func=cmd_monitor_export)

    sp = sub.add_parser("sample", help="stratified sample of recent traces for review / judging")
    sp.add_argument("--window", default="4h")
    sp.add_argument("--since", default=None)
    sp.add_argument("--until", default=None)
    sp.add_argument("--budget", type=int, default=40)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--skip-judged", dest="skip_judged", action="store_true")
    sp.add_argument("--strategy", choices=["stratified", "uniform"], default="stratified")
    sp.add_argument("--out", type=Path, default=None)
    sp.set_defaults(func=cmd_sample)

    j = sub.add_parser("judge", help="LLM rubric judge over sampled traces")
    j.add_argument("--sample", type=Path, default=None)
    j.add_argument("--trace-ids", dest="trace_ids", nargs="*", default=None)
    j.add_argument(
        "--judge-invalid-rate",
        dest="judge_invalid_rate",
        type=float,
        default=0.0,
        help="fake judge: share of broken JSON replies",
    )
    j.add_argument(
        "--slo-eligible",
        dest="slo_eligible",
        action="store_true",
        help="count these judge scores in the judged-quality SLO (default: only uniform samples)",
    )
    j.add_argument("--out", type=Path, default=None)
    _add_model_args(j)
    j.set_defaults(func=cmd_judge)

    fb = sub.add_parser("feedback", help="user feedback").add_subparsers(dest="sub", required=True)
    fa = fb.add_parser("add")
    fa.add_argument("--trace-id", dest="trace_id", required=True)
    fa.add_argument("--thumbs", choices=["up", "down"], default=None)
    fa.add_argument("--comment", default=None)
    fa.add_argument(
        "--wrong-part",
        dest="wrong_part",
        choices=["numbers", "answer", "tone", "refusal", "format", "other"],
        default=None,
    )
    fa.add_argument("--regenerated", action="store_true")
    fa.add_argument("--edited-text", dest="edited_text", default=None)
    fa.set_defaults(func=cmd_feedback_add)

    c = sub.add_parser("curate", help="build a review queue from sampled traces")
    c.add_argument("--sample", type=Path, default=None)
    c.add_argument("--trace-ids", dest="trace_ids", nargs="*", default=None)
    c.add_argument("--reviewer", default="reviewer")
    c.add_argument(
        "--accept-all",
        dest="accept_all",
        action="store_true",
        help="mark every proposed case accepted (demo)",
    )
    c.add_argument("--out", type=Path, required=True)
    c.set_defaults(func=cmd_curate)

    ds = sub.add_parser("dataset", help="versioned evaluation sets").add_subparsers(
        dest="sub", required=True
    )
    db = ds.add_parser("build")
    db.add_argument("--from-review", dest="from_review", type=Path, required=True)
    db.add_argument("--name", required=True)
    db.add_argument("--version", type=int, default=None)
    db.add_argument("--changelog", default=None)
    db.add_argument("--accept-pending", dest="accept_pending", action="store_true")
    db.add_argument(
        "--fresh", action="store_true", help="do not carry the previous version's cases"
    )
    db.set_defaults(func=cmd_dataset_build)
    ds.add_parser("list").set_defaults(func=cmd_dataset_list)
    dd = ds.add_parser("diff")
    dd.add_argument("--name", required=True)
    dd.add_argument("--from", dest="from_version", type=int, required=True)
    dd.add_argument("--to", dest="to_version", type=int, required=True)
    dd.set_defaults(func=cmd_dataset_diff)

    pr = sub.add_parser("prompt", help="prompt registry").add_subparsers(dest="sub", required=True)
    pg = pr.add_parser("register")
    pg.add_argument("path")
    pg.add_argument("--overwrite", action="store_true")
    pg.set_defaults(func=cmd_prompt_register)
    pl = pr.add_parser("list")
    pl.add_argument("--name", default=None)
    pl.set_defaults(func=cmd_prompt_list)
    pd = pr.add_parser("diff")
    pd.add_argument("ref_a")
    pd.add_argument("ref_b")
    pd.set_defaults(func=cmd_prompt_diff)
    pn = pr.add_parser("render")
    pn.add_argument("ref")
    pn.add_argument("--var", action="append", default=None, help="key=value")
    pn.set_defaults(func=cmd_prompt_render)
    pt = pr.add_parser("lint")
    pt.add_argument("ref", nargs="?", default=None)
    pt.add_argument("--gate", action="store_true")
    pt.set_defaults(func=cmd_prompt_lint)

    r = sub.add_parser("regress", help="prompt regression gate")
    r.add_argument("--dataset", required=True, help="name or name@vN")
    r.add_argument("--candidate", required=True, help="name@version or @version")
    r.add_argument("--baseline", required=True)
    r.add_argument("--out", type=Path, default=Path("runs/regress"))
    r.add_argument("--gate", action="store_true")
    r.add_argument("--use-judge", dest="use_judge", action="store_true")
    r.add_argument("--judge-invalid-rate", dest="judge_invalid_rate", type=float, default=0.0)
    r.add_argument("--margin", type=float, default=0.05)
    r.add_argument("--slice-margin", dest="slice_margin", type=float, default=0.15)
    r.add_argument("--json-floor", dest="json_floor", type=float, default=0.95)
    r.add_argument("--cost-budget", dest="cost_budget", type=float, default=1.5)
    r.add_argument("--latency-budget-ms", dest="latency_budget_ms", type=float, default=None)
    r.add_argument("--min-cases", dest="min_cases", type=int, default=20)
    r.add_argument(
        "--limit",
        type=int,
        default=None,
        help="compare only the first N cases of the dataset (deterministic; GPU budgets)",
    )
    _add_model_args(r)
    r.set_defaults(func=cmd_regress)

    rel = sub.add_parser("release", help="prompt canary").add_subparsers(dest="sub", required=True)
    simple = (
        ("status", cmd_release_status),
        ("advance", cmd_release_advance),
        ("rollback", cmd_release_rollback),
    )
    for name_, fn in simple:
        rp = rel.add_parser(name_)
        rp.add_argument("--name", default="adviser_assistant")
        rp.add_argument("--reason", default="manual")
        rp.set_defaults(func=fn)
    rs = rel.add_parser("start")
    rs.add_argument("--name", default="adviser_assistant")
    rs.add_argument("--version", required=True)
    rs.add_argument("--stage", type=int, default=None)
    rs.set_defaults(func=cmd_release_start)
    ra = rel.add_parser("auto", help="evaluate the canary cohort and advance / roll back")
    ra.add_argument("--name", default="adviser_assistant")
    ra.add_argument("--window", default="4h")
    ra.add_argument("--since", default=None)
    ra.add_argument("--until", default=None)
    ra.add_argument("--seed", type=int, default=0)
    ra.add_argument("--apply", action="store_true", help="write the decision to releases.yaml")
    ra.add_argument("--out", type=Path, default=None)
    ra.set_defaults(func=cmd_release_auto)

    rp2 = sub.add_parser("replay", help="re-run a recorded trace")
    rp2.add_argument("trace_id")
    rp2.add_argument("--prompt-version", dest="prompt_version", default=None)
    rp2.add_argument("--out", type=Path, default=None)
    _add_model_args(rp2)
    rp2.set_defaults(func=cmd_replay)

    inc = sub.add_parser("incident", help="incident analysis").add_subparsers(
        dest="sub", required=True
    )
    ir = inc.add_parser("report")
    ir.add_argument("--window", default="4h")
    ir.add_argument("--since", default=None)
    ir.add_argument("--until", default=None)
    ir.add_argument("--bucket-minutes", dest="bucket_minutes", type=float, default=10.0)
    ir.add_argument("--title", default="Incident report (draft)")
    ir.add_argument("--out", type=Path, default=None)
    ir.set_defaults(func=cmd_incident_report)

    st = sub.add_parser("store", help="store maintenance").add_subparsers(dest="sub", required=True)
    spn = st.add_parser("prune")
    spn.add_argument("--older-than", dest="older_than", default="30d")
    spn.add_argument("--now", default=None, help="ISO reference time (default: wall clock)")
    spn.set_defaults(func=cmd_store_prune)
    sx = st.add_parser("export")
    sx.add_argument("--out", type=Path, required=True)
    sx.add_argument("--since", default=None)
    sx.set_defaults(func=cmd_store_export)
    return p


def main(argv: Sequence[str] | None = None) -> int:
    _configure_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (FileNotFoundError, KeyError, ValueError, FileExistsError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
