"""Monitor self-evaluation: run demo traffic with planted incidents, run the monitor over it,
and score the monitor against the ground truth — time-to-detect, detection rate and
false-alarm rate per incident kind, with bootstrap intervals across seeds / quiet ticks."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from opsloop.demo.scenario import Scenario
from opsloop.demo.traffic import TrafficSummary, run_traffic
from opsloop.monitor.config import MonitorConfig
from opsloop.monitor.core import Evaluation, Monitor
from opsloop.prompts.registry import PromptRegistry
from opsloop.stats import bootstrap_mean_ci
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH


class IncidentOutcome(BaseModel):
    scenario: str
    seed: int
    kind: str
    start_minute: float
    end_minute: float
    expected_alerts: list[str]
    detected: bool
    time_to_detect_minutes: float | None
    first_alert: str | None
    alerts_during: dict[str, int] = Field(default_factory=dict)


class RunOutcome(BaseModel):
    scenario: str
    seed: int
    n_requests: int
    n_ticks: int
    quiet_ticks: int
    quiet_ticks_with_alert: int
    false_alarms_by_name: dict[str, int] = Field(default_factory=dict)
    incidents: list[IncidentOutcome] = Field(default_factory=list)
    alert_timeline: list[dict[str, Any]] = Field(default_factory=list)


class KindSummary(BaseModel):
    kind: str
    n: int
    detected: int
    detection_rate: float
    detection_ci: list[float]
    ttd_mean: float | None
    ttd_ci: list[float | None]
    ttd_values: list[float]


class EvaluationReport(BaseModel):
    minutes: float
    seeds: list[int]
    scenarios: list[str]
    kinds: list[KindSummary]
    quiet_ticks: int
    quiet_ticks_with_alert: int
    false_alarm_rate: float
    false_alarm_ci: list[float]
    false_alarms_by_name: dict[str, int]
    runs: list[RunOutcome]
    gate: dict[str, Any] = Field(default_factory=dict)


@dataclass
class _Acc:
    detected: list[int] = field(default_factory=list)
    ttd: list[float] = field(default_factory=list)


def score_run(
    scenario: Scenario,
    seed: int,
    evaluations: Sequence[Evaluation],
    *,
    start_ts: float,
    shadow_minutes: float,
    summary: TrafficSummary,
    warmup_minutes: float = 0.0,
) -> RunOutcome:
    """Compare alerts per tick with the incident windows. A tick is *quiet* when no incident
    is active and none ended within the last ``shadow_minutes`` (the long window still holds
    the incident's bad events); any alert on a quiet tick is a false alarm."""
    quiet = 0
    quiet_alerts = 0
    by_name: dict[str, int] = {}
    timeline: list[dict[str, Any]] = []
    for ev in evaluations:
        minute = (ev.as_of - start_ts) / 60.0
        active = scenario.incident_active(minute)
        shadow = any(
            i.end_minute <= minute < i.end_minute + shadow_minutes for i in scenario.incidents
        )
        names = sorted(ev.alert_names)
        timeline.append({"minute": round(minute, 1), "alerts": names, "incident_active": active})
        if active or shadow or minute < warmup_minutes:
            continue
        quiet += 1
        if names:
            quiet_alerts += 1
            for n in names:
                by_name[n] = by_name.get(n, 0) + 1
    incidents: list[IncidentOutcome] = []
    for inc in scenario.incidents:
        first_minute: float | None = None
        first_alert: str | None = None
        during: dict[str, int] = {}
        for ev in evaluations:
            minute = (ev.as_of - start_ts) / 60.0
            if minute < inc.start_minute or minute >= inc.end_minute + shadow_minutes:
                continue
            for a in ev.alerts:
                during[a.name] = during.get(a.name, 0) + 1
                if first_minute is None and a.name in inc.expected_alerts:
                    first_minute, first_alert = minute, a.name
        incidents.append(
            IncidentOutcome(
                scenario=scenario.name,
                seed=seed,
                kind=inc.kind,
                start_minute=inc.start_minute,
                end_minute=inc.end_minute,
                expected_alerts=inc.expected_alerts,
                detected=first_minute is not None,
                time_to_detect_minutes=None
                if first_minute is None
                else round(first_minute - inc.start_minute, 2),
                first_alert=first_alert,
                alerts_during=dict(sorted(during.items())),
            )
        )
    return RunOutcome(
        scenario=scenario.name,
        seed=seed,
        n_requests=summary.n_requests,
        n_ticks=len(evaluations),
        quiet_ticks=quiet,
        quiet_ticks_with_alert=quiet_alerts,
        false_alarms_by_name=dict(sorted(by_name.items())),
        incidents=incidents,
        alert_timeline=timeline,
    )


def evaluate_monitor(
    scenarios: Sequence[Scenario],
    *,
    seeds: Sequence[int],
    minutes: float,
    config: MonitorConfig,
    registry: PromptRegistry,
    start_ts: float = DEMO_EPOCH,
    min_detection: float = 0.9,
    max_false_alarm: float = 0.05,
    n_boot: int = 1000,
) -> EvaluationReport:
    runs: list[RunOutcome] = []
    shadow = config.max_window_minutes
    warmup = min((w.long_minutes for w in config.windows), default=0.0)
    for scenario in scenarios:
        for seed in seeds:
            store = TraceStore(":memory:")
            summary = run_traffic(
                scenario,
                seed=seed,
                minutes=minutes,
                store=store,
                registry=registry,
                start_ts=start_ts,
            )
            monitor = Monitor(config, store.rows, start_ts=start_ts)
            evaluations = monitor.run(start_ts, start_ts + minutes * 60.0)
            runs.append(
                score_run(
                    scenario,
                    seed,
                    evaluations,
                    start_ts=start_ts,
                    shadow_minutes=shadow,
                    summary=summary,
                    warmup_minutes=warmup,
                )
            )
            store.close()
    return summarise(
        runs,
        minutes=minutes,
        seeds=list(seeds),
        scenarios=[s.name for s in scenarios],
        min_detection=min_detection,
        max_false_alarm=max_false_alarm,
        n_boot=n_boot,
    )


def summarise(
    runs: Sequence[RunOutcome],
    *,
    minutes: float,
    seeds: list[int],
    scenarios: list[str],
    min_detection: float,
    max_false_alarm: float,
    n_boot: int = 1000,
) -> EvaluationReport:
    acc: dict[str, _Acc] = {}
    for run in runs:
        for inc in run.incidents:
            a = acc.setdefault(inc.kind, _Acc())
            a.detected.append(int(inc.detected))
            if inc.time_to_detect_minutes is not None:
                a.ttd.append(inc.time_to_detect_minutes)
    kinds: list[KindSummary] = []
    for kind, a in sorted(acc.items()):
        det = bootstrap_mean_ci([float(x) for x in a.detected], n_boot=n_boot, seed=1)
        ttd = bootstrap_mean_ci(a.ttd, n_boot=n_boot, seed=2) if a.ttd else None
        kinds.append(
            KindSummary(
                kind=kind,
                n=len(a.detected),
                detected=sum(a.detected),
                detection_rate=det.mean,
                detection_ci=[round(det.low, 3), round(det.high, 3)],
                ttd_mean=None if ttd is None else round(ttd.mean, 2),
                ttd_ci=[None, None] if ttd is None else [round(ttd.low, 2), round(ttd.high, 2)],
                ttd_values=list(a.ttd),
            )
        )
    quiet_flags: list[float] = []
    by_name: dict[str, int] = {}
    for run in runs:
        quiet_flags.extend([1.0] * run.quiet_ticks_with_alert)
        quiet_flags.extend([0.0] * (run.quiet_ticks - run.quiet_ticks_with_alert))
        for k, v in run.false_alarms_by_name.items():
            by_name[k] = by_name.get(k, 0) + v
    fa = bootstrap_mean_ci(quiet_flags, n_boot=n_boot, seed=3) if quiet_flags else None
    fa_rate = fa.mean if fa is not None else math.nan
    gate_ok = all(k.detection_rate >= min_detection for k in kinds) and (
        fa is None or fa_rate <= max_false_alarm
    )
    return EvaluationReport(
        minutes=minutes,
        seeds=seeds,
        scenarios=scenarios,
        kinds=kinds,
        quiet_ticks=len(quiet_flags),
        quiet_ticks_with_alert=int(sum(quiet_flags)),
        false_alarm_rate=round(fa_rate, 4) if fa is not None else math.nan,
        false_alarm_ci=[round(fa.low, 4), round(fa.high, 4)]
        if fa is not None
        else [math.nan, math.nan],
        false_alarms_by_name=dict(sorted(by_name.items())),
        runs=list(runs),
        gate={
            "min_detection": min_detection,
            "max_false_alarm": max_false_alarm,
            "passed": gate_ok,
        },
    )


def render_markdown(report: EvaluationReport) -> str:
    lines = [
        "# Monitor self-evaluation",
        "",
        f"Scenarios: {', '.join(report.scenarios)}; seeds: {report.seeds}; "
        f"{report.minutes:g} simulated minutes per run.",
        "",
        "| Incident kind | Runs | Detected | Detection rate [95% CI] | "
        "Time-to-detect (min) mean [95% CI] | TTD values |",
        "|---|---:|---:|---|---|---|",
    ]
    for k in report.kinds:
        ttd = "-" if k.ttd_mean is None else f"{k.ttd_mean:.1f} [{k.ttd_ci[0]}, {k.ttd_ci[1]}]"
        values = ", ".join(f"{v:g}" for v in k.ttd_values) or "-"
        lines.append(
            f"| {k.kind} | {k.n} | {k.detected} | {k.detection_rate:.2f} "
            f"[{k.detection_ci[0]}, {k.detection_ci[1]}] | {ttd} | {values} |"
        )
    lines += [
        "",
        f"False-alarm rate on quiet ticks: **{report.false_alarm_rate:.4f}** "
        f"[{report.false_alarm_ci[0]}, {report.false_alarm_ci[1]}] "
        f"({report.quiet_ticks_with_alert}/{report.quiet_ticks} ticks)",
        "",
    ]
    if report.false_alarms_by_name:
        lines.append(
            "False alarms by alert: "
            + ", ".join(f"{k}: {v}" for k, v in report.false_alarms_by_name.items())
        )
        lines.append("")
    lines.append(
        f"Gate: detection >= {report.gate['min_detection']} for every kind and false alarms <= "
        f"{report.gate['max_false_alarm']} -> **{'PASS' if report.gate['passed'] else 'FAIL'}**"
    )
    lines += [
        "",
        "## Per-run incidents",
        "",
        "| Scenario | Seed | Kind | Window (min) | Detected | TTD (min) | First alert | "
        "Alerts during incident |",
        "|---|---:|---|---|---|---:|---|---|",
    ]
    for run in report.runs:
        for inc in run.incidents:
            during = ", ".join(f"{k} x{v}" for k, v in inc.alerts_during.items()) or "-"
            ttd_text = (
                "-" if inc.time_to_detect_minutes is None else str(inc.time_to_detect_minutes)
            )
            lines.append(
                f"| {inc.scenario} | {inc.seed} | {inc.kind} | "
                f"{inc.start_minute:g}-{inc.end_minute:g} | {'yes' if inc.detected else 'no'} | "
                f"{ttd_text} | {inc.first_alert or '-'} | {during} |"
            )
    lines += [
        "",
        "## Quiet ticks per run",
        "",
        "| Scenario | Seed | Requests | Ticks | Quiet ticks | Quiet ticks with an alert |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for run in report.runs:
        lines.append(
            f"| {run.scenario} | {run.seed} | {run.n_requests} | {run.n_ticks} | "
            f"{run.quiet_ticks} | {run.quiet_ticks_with_alert} |"
        )
    return "\n".join(lines) + "\n"
