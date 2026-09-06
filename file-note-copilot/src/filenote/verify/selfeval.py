"""Verifier self-evaluation: plant hallucinations of known kinds into gold notes and measure,
per kind, how often the verifier flags the planted claim as *unsupported* (what blocks
approval), how often it flags it at all, whether the stated reason names the right problem,
and — on untouched gold claims — the false-alarm rate. Cluster bootstrap over meetings."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from filenote.corpus.generate import Meeting
from filenote.eval.stats import (
    Calibration,
    Interval,
    cluster_bootstrap_rate,
    expected_calibration_error,
)
from filenote.schema import CLAIM_SECTIONS
from filenote.verify.plant import PLANT_KINDS, PlantKind, plant
from filenote.verify.verifier import Verifier

EXPECTED_REASON: dict[PlantKind, tuple[str, ...]] = {
    "invented_decision": ("lexical support", "commitment", "deferral", "small talk", "figure"),
    "changed_number": ("figure",),
    "wrong_owner": ("assigns this to",),
    "wrong_date": ("date",),
    "deferred_as_decided": ("deferral",),
    "wrong_citation": ("lexical support", "figure", "date", "small talk", "commitment", "assigns"),
    "small_talk_leakage": ("small talk",),
}


class KindResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    n: int
    detected: dict[str, float]
    flagged: dict[str, float]
    attributed: dict[str, float]


class SelfEvalReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meetings: int
    clean_claims: int
    kinds: list[KindResult]
    false_alarm_unsupported: dict[str, float]
    false_alarm_any: dict[str, float]
    false_alarm_by_section: dict[str, dict[str, float]]
    calibration: dict[str, Any]
    n_boot: int = 1000
    config: dict[str, Any] = Field(default_factory=dict)

    def gate(self, *, min_detection: float, max_false_alarm: float) -> list[str]:
        failures: list[str] = []
        for k in self.kinds:
            if k.detected["mean"] < min_detection:
                failures.append(f"{k.kind}: detection {k.detected['mean']:.3f} < {min_detection}")
        if self.false_alarm_unsupported["mean"] > max_false_alarm:
            failures.append(
                f"false alarm {self.false_alarm_unsupported['mean']:.3f} > {max_false_alarm}"
            )
        return failures


def _iv(interval: Interval) -> dict[str, float]:
    return {k: float(v) for k, v in interval.to_dict().items()}


def evaluate_verifier(
    meetings: list[Meeting], verifier: Verifier, *, seed: int = 0, n_boot: int = 1000
) -> SelfEvalReport:
    clean_unsupported: list[list[float]] = []
    clean_any: list[list[float]] = []
    by_section: dict[str, list[list[float]]] = {s: [] for s in CLAIM_SECTIONS}
    scores: list[float] = []
    genuine: list[bool] = []
    for m in meetings:
        report = verifier.verify(m.gold, m.transcript)
        unsupported = [1.0 if v.status == "unsupported" else 0.0 for v in report.verdicts]
        flagged = [1.0 if v.status != "supported" else 0.0 for v in report.verdicts]
        clean_unsupported.append(unsupported)
        clean_any.append(flagged)
        for v in report.verdicts:
            by_section[v.section].append([1.0 if v.status == "unsupported" else 0.0])
            scores.append(v.score)
            genuine.append(True)

    kinds: list[KindResult] = []
    for k_i, kind in enumerate(PLANT_KINDS):
        det: list[list[float]] = []
        flag: list[list[float]] = []
        attr: list[list[float]] = []
        for m_i, m in enumerate(meetings):
            rng = random.Random(f"{seed}|{kind}|{m.id}")
            planted = plant(m, kind, rng)
            if planted is None:
                continue
            note, section, index = planted
            report = verifier.verify(note, m.transcript)
            verdict = report.verdict_for(section, index)
            assert verdict is not None
            det.append([1.0 if verdict.status == "unsupported" else 0.0])
            flag.append([1.0 if verdict.status != "supported" else 0.0])
            reasons = " ".join(verdict.reasons).lower()
            attr.append([1.0 if any(e in reasons for e in EXPECTED_REASON[kind]) else 0.0])
            scores.append(verdict.score)
            genuine.append(False)
            _ = (k_i, m_i)
        kinds.append(
            KindResult(
                kind=kind,
                n=len(det),
                detected=_iv(cluster_bootstrap_rate(det, n_boot=n_boot, seed=seed)),
                flagged=_iv(cluster_bootstrap_rate(flag, n_boot=n_boot, seed=seed)),
                attributed=_iv(cluster_bootstrap_rate(attr, n_boot=n_boot, seed=seed)),
            )
        )
    calibration: Calibration = expected_calibration_error(scores, genuine)
    return SelfEvalReport(
        meetings=len(meetings),
        clean_claims=sum(len(c) for c in clean_unsupported),
        kinds=kinds,
        false_alarm_unsupported=_iv(
            cluster_bootstrap_rate(clean_unsupported, n_boot=n_boot, seed=seed)
        ),
        false_alarm_any=_iv(cluster_bootstrap_rate(clean_any, n_boot=n_boot, seed=seed)),
        false_alarm_by_section={
            s: _iv(cluster_bootstrap_rate(rows, n_boot=n_boot, seed=seed))
            for s, rows in by_section.items()
            if rows
        },
        calibration=calibration.to_dict(),
        n_boot=n_boot,
        config=verifier.config.model_dump(),
    )


def _pct(d: dict[str, float]) -> str:
    return f"{100 * d['mean']:.1f}% [{100 * d['low']:.1f}, {100 * d['high']:.1f}]"


def render_selfeval_md(report: SelfEvalReport, *, gate_failures: list[str] | None = None) -> str:
    lines = [
        "# Verifier self-evaluation on planted hallucinations",
        "",
        f"- meetings: {report.meetings}; untouched gold claims: {report.clean_claims}",
        f"- false-alarm rate (gold claim marked *unsupported*): "
        f"**{_pct(report.false_alarm_unsupported)}**",
        f"- gold claims marked weak or unsupported: {_pct(report.false_alarm_any)}",
        f"- intervals: 95 % cluster bootstrap over meetings, {report.n_boot} resamples",
        "",
        "| Planted hallucination | n | Detected (unsupported) | Flagged (weak or worse) "
        "| Reason names the problem |",
        "|---|---:|---:|---:|---:|",
    ]
    for k in report.kinds:
        lines.append(
            f"| {k.kind} | {k.n} | **{_pct(k.detected)}** | {_pct(k.flagged)} | "
            f"{_pct(k.attributed)} |"
        )
    lines += ["", "| Section | Gold claims | False alarms (unsupported) |", "|---|---:|---:|"]
    for s, d in report.false_alarm_by_section.items():
        lines.append(f"| {s} | {int(d['n'])} | {_pct(d)} |")
    cal = report.calibration
    lines += [
        "",
        f"Support score calibration (score as P(claim is genuine), genuine = gold claim, "
        f"not genuine = planted): ECE = {cal['ece']:.3f} over {cal['n']} claims.",
        "",
        "| Score bin | n | Mean score | Fraction genuine |",
        "|---|---:|---:|---:|",
    ]
    for b in cal["bins"]:
        if b["n"]:
            lines.append(
                f"| {b['low']:.1f}-{b['high']:.1f} | {b['n']} | {b['mean_confidence']:.3f} | "
                f"{b['mean_accuracy']:.3f} |"
            )
    if gate_failures is not None:
        lines += [
            "",
            "Gate: "
            + ("**PASS**" if not gate_failures else "**FAIL** — " + "; ".join(gate_failures)),
        ]
    return "\n".join(lines) + "\n"


def save_selfeval(report: SelfEvalReport, out_dir: Path | str, md: str) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "verifier_selfeval.json"
    md_path = out / "verifier_selfeval.md"
    json_path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    md_path.write_text(md, encoding="utf-8")
    return json_path, md_path
