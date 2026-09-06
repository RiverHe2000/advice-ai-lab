"""Runs a drafting strategy over a corpus, evaluates each note against gold, aggregates with
bootstrap intervals, and compares runs pairwise on identical transcripts (paired bootstrap on
per-meeting differences, exact McNemar on the binary "hallucination-free note" outcome)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from filenote.corpus.generate import Meeting
from filenote.draft.base import Drafter, DraftError
from filenote.eval.metrics import MeetingMetrics, evaluate_note, failed_metrics
from filenote.eval.stats import bootstrap_ci, paired_bootstrap
from filenote.pii import Pseudonymiser
from filenote.schema import MeetingMeta
from filenote.verify.verifier import Verifier

PRIMARY_SECTIONS = ("circumstance_changes", "goals", "decisions", "action_items")
LOWER_IS_BETTER = frozenset({"hallucination_rate", "unmatched_rate", "omission_rate", "latency_s"})
SECONDARY_SECTIONS = (
    "topics_discussed",
    "advice_discussed",
    "vulnerability_indicators",
    "follow_up",
)
ProgressFn = Callable[[str, MeetingMetrics], None]


class StrategyRun(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    strategy: str
    model: str
    pseudonymise: bool
    corruption: float | None = None
    meetings: list[MeetingMetrics] = Field(default_factory=list)
    aggregate: dict[str, dict[str, float]] = Field(default_factory=dict)
    totals: dict[str, float] = Field(default_factory=dict)
    wall_s: float = 0.0

    def values(self, metric: str) -> list[float]:
        return [_metric(m, metric) for m in self.meetings]

    def binary(self) -> list[bool]:
        return [m.hallucination_free for m in self.meetings]


def _metric(m: MeetingMetrics, metric: str) -> float:
    if metric == "macro_f1":
        return m.macro_f1
    if metric.endswith("_f1"):
        return m.section_f1(metric[: -len("_f1")])
    if metric.endswith("_precision"):
        s = metric[: -len("_precision")]
        return m.sections[s].precision if s in m.sections else 0.0
    if metric.endswith("_recall"):
        s = metric[: -len("_recall")]
        return m.sections[s].recall if s in m.sections else 0.0
    value = getattr(m, metric)
    return float(value) if value is not None else 0.0


AGGREGATE_METRICS = (
    "macro_f1",
    *[f"{s}_f1" for s in PRIMARY_SECTIONS],
    *[f"{s}_precision" for s in PRIMARY_SECTIONS],
    *[f"{s}_recall" for s in PRIMARY_SECTIONS],
    *[f"{s}_f1" for s in SECONDARY_SECTIONS],
    "hallucination_rate",
    "unmatched_rate",
    "omission_rate",
    "compliance_accuracy",
    "verifier_supported_fraction",
    "numeric_grounding_rate",
    "latency_s",
)


def aggregate(run: StrategyRun, *, n_boot: int, seed: int) -> None:
    run.aggregate = {
        metric: bootstrap_ci(run.values(metric), n_boot=n_boot, seed=seed).to_dict()
        for metric in AGGREGATE_METRICS
    }
    hall = sum(m.hallucinated for m in run.meetings)
    surfaced = sum(m.surfaced for m in run.meetings)
    due = [m.sections["action_items"].due_within_tolerance for m in run.meetings]
    due_known = [d for d in due if d is not None]
    run.totals = {
        "meetings": float(len(run.meetings)),
        "failed": float(sum(1 for m in run.meetings if m.failed)),
        "hallucination_free_meetings": float(sum(1 for m in run.meetings if m.hallucination_free)),
        "hallucinated_claims": float(hall),
        "hallucinated_surfaced": float(surfaced),
        "surfaced_rate": surfaced / hall if hall else 1.0,
        "unsupported_remaining": float(sum(m.unsupported_remaining for m in run.meetings)),
        "small_talk_leaks": float(sum(m.small_talk_leaks for m in run.meetings)),
        "json_repairs": float(sum(m.json_repairs for m in run.meetings)),
        "parse_failures": float(sum(m.parse_failures for m in run.meetings)),
        "failed_windows": float(sum(m.failed_windows for m in run.meetings)),
        "model_calls": float(sum(m.model_calls for m in run.meetings)),
        "repair_cited": float(sum(m.repair_cited for m in run.meetings)),
        "repair_dropped": float(sum(m.repair_dropped for m in run.meetings)),
        "prompt_tokens": float(sum(m.prompt_tokens for m in run.meetings)),
        "completion_tokens": float(sum(m.completion_tokens for m in run.meetings)),
        "due_within_tolerance": sum(due_known) / len(due_known) if due_known else 1.0,
    }


def run_strategy(
    meetings: list[Meeting],
    drafter: Drafter,
    verifier: Verifier,
    *,
    name: str | None = None,
    pseudonymise: bool = False,
    corruption: float | None = None,
    n_boot: int = 1000,
    seed: int = 0,
    progress: ProgressFn | None = None,
) -> StrategyRun:
    started = time.perf_counter()
    model_name = "?"
    run = StrategyRun(
        name=name or drafter.strategy,
        strategy=drafter.strategy,
        model=model_name,
        pseudonymise=pseudonymise,
        corruption=corruption,
    )
    for meeting in meetings:
        transcript = meeting.transcript
        meta = meeting.gold.meeting
        pseud: Pseudonymiser | None = None
        if pseudonymise:
            pseud = Pseudonymiser(transcript.attendees)
            transcript = pseud.transcript(transcript)
            meta = MeetingMeta(
                date=meta.date,
                type=meta.type,
                attendees=transcript.attendees,
                duration_minutes=meta.duration_minutes,
            )
        t0 = time.perf_counter()
        try:
            result = drafter.draft(transcript, meeting=meta)
        except DraftError:
            metrics = failed_metrics(meeting, latency_s=time.perf_counter() - t0)
        else:
            run.model = result.model
            note = result.note
            if pseud is not None:
                note = pseud.restore_note(note)
                note.meeting = meeting.gold.meeting
            metrics = evaluate_note(meeting, note, verifier, result=result)
        run.meetings.append(metrics)
        if progress is not None:
            progress(run.name, metrics)
    aggregate(run, n_boot=n_boot, seed=seed)
    run.wall_s = time.perf_counter() - started
    return run


class Comparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    metric: str
    result: dict[str, float | int | str]


def compare_runs(
    a: StrategyRun,
    b: StrategyRun,
    *,
    metrics: tuple[str, ...] = (
        "macro_f1",
        "decisions_f1",
        "action_items_f1",
        "hallucination_rate",
    ),
    n_boot: int = 1000,
    seed: int = 0,
    non_inferiority_margin: float = 0.0,
) -> list[Comparison]:
    ids_a = [m.meeting_id for m in a.meetings]
    ids_b = [m.meeting_id for m in b.meetings]
    if ids_a != ids_b:
        msg = "runs must cover the same meetings in the same order"
        raise ValueError(msg)
    out: list[Comparison] = []
    binary = list(zip(a.binary(), b.binary(), strict=True))
    for metric in metrics:
        lower_is_better = metric in LOWER_IS_BETTER
        sign = -1.0 if lower_is_better else 1.0
        pc = paired_bootstrap(
            [sign * v for v in a.values(metric)],
            [sign * v for v in b.values(metric)],
            n_boot=n_boot,
            seed=seed,
            non_inferiority_margin=non_inferiority_margin,
            binary=binary if metric == "macro_f1" else None,
        )
        result = pc.to_dict()
        if lower_is_better:
            # report the raw means / delta; the verdict already accounts for direction
            result["mean_a"] = -float(result["mean_a"])
            result["mean_b"] = -float(result["mean_b"])
            result["delta"] = -float(result["delta"])
            lo, hi = -float(result["ci_high"]), -float(result["ci_low"])
            result["ci_low"], result["ci_high"] = lo, hi
        out.append(Comparison(a=a.name, b=b.name, metric=metric, result=result))
    return out


class EvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created: str
    corpus: dict[str, Any] = Field(default_factory=dict)
    runs: list[StrategyRun] = Field(default_factory=list)
    comparisons: list[Comparison] = Field(default_factory=list)
    gate: dict[str, Any] = Field(default_factory=dict)

    def run(self, name: str) -> StrategyRun:
        for r in self.runs:
            if r.name == name:
                return r
        msg = f"no run named {name!r}"
        raise KeyError(msg)


class GateThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_macro_f1: float = Field(0.9, ge=0.0, le=1.0)
    min_decisions_f1: float = Field(0.9, ge=0.0, le=1.0)
    max_hallucination_rate: float = Field(0.02, ge=0.0, le=1.0)
    max_omission_rate: float = Field(0.1, ge=0.0, le=1.0)
    min_surfaced_rate: float = Field(0.9, ge=0.0, le=1.0)
    max_failed: int = Field(0, ge=0)


def apply_gate(run: StrategyRun, thresholds: GateThresholds) -> list[str]:
    """Gate on the *conservative* bound of each interval where one exists."""
    failures: list[str] = []
    agg = run.aggregate

    def _low(metric: str) -> float:
        return float(agg[metric]["low"])

    def _high(metric: str) -> float:
        return float(agg[metric]["high"])

    if _low("macro_f1") < thresholds.min_macro_f1:
        failures.append(f"macro F1 lower bound {_low('macro_f1'):.3f} < {thresholds.min_macro_f1}")
    if _low("decisions_f1") < thresholds.min_decisions_f1:
        failures.append(
            f"decisions F1 lower bound {_low('decisions_f1'):.3f} < {thresholds.min_decisions_f1}"
        )
    if _high("hallucination_rate") > thresholds.max_hallucination_rate:
        failures.append(
            f"hallucination rate upper bound {_high('hallucination_rate'):.3f} > "
            f"{thresholds.max_hallucination_rate}"
        )
    if _high("omission_rate") > thresholds.max_omission_rate:
        failures.append(
            f"omission rate upper bound {_high('omission_rate'):.3f} > "
            f"{thresholds.max_omission_rate}"
        )
    if run.totals["surfaced_rate"] < thresholds.min_surfaced_rate:
        failures.append(
            f"surfaced rate {run.totals['surfaced_rate']:.3f} < {thresholds.min_surfaced_rate}"
        )
    if run.totals["failed"] > thresholds.max_failed:
        failures.append(f"{int(run.totals['failed'])} meeting(s) failed to draft")
    return failures


def save_report(report: EvalReport, out_dir: Path | str, md: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "report.json"
    md_path = out / "report.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
