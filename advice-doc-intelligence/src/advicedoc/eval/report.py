"""Markdown + JSON writer for extraction evaluations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from advicedoc.eval.extraction import StrategyComparison, StrategyEvaluation
from advicedoc.eval.matching import ALL_FIELDS
from advicedoc.stats import PAIRED_HEADER, render_paired


@dataclass(slots=True)
class ExtractionReport:
    title: str
    strategies: list[StrategyEvaluation]
    comparisons: list[StrategyComparison] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    settings: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "settings": self.settings,
            "notes": self.notes,
            "strategies": [s.to_dict() for s in self.strategies],
            "comparisons": [c.to_dict() for c in self.comparisons],
        }


def render_extraction_report(report: ExtractionReport) -> str:
    strategies = report.strategies
    lines = [f"# {report.title}", ""]
    if report.settings:
        lines.append("Settings: " + ", ".join(f"{k}={v}" for k, v in report.settings.items()))
        lines.append("")
    lines += [
        "## Headline",
        "",
        "| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | "
        "Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | "
        "Tokens / doc | Latency / doc |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for s in strategies:
        tokens = (s.prompt_tokens + s.completion_tokens) / max(1, s.n_docs)
        lines.append(
            f"| {s.strategy} | {s.n_docs} | {s.doc_accuracy.fmt()} | {s.field_accuracy.fmt()} | "
            f"{s.recommendations['f1'].fmt()} | {s.replacements['f1'].fmt()} | {s.repairs} | "
            f"{s.parse_failures} | {s.retries} | {s.reasks} ({s.reasks_fixed}) | {s.n_calls} | "
            f"{tokens:.0f} | {s.latency_s_per_doc * 1000:.0f} ms |"
        )
    lines += ["", "## Per field (accuracy [95 % CI])", ""]
    lines.append("| Field | " + " | ".join(s.strategy for s in strategies) + " |")
    lines.append("|---|" + "---:|" * len(strategies))
    for f in ALL_FIELDS:
        lines.append(f"| {f} | " + " | ".join(s.per_field[f].fmt() for s in strategies) + " |")
    lines += [
        "",
        "## List fields",
        "",
        "| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | "
        "Repl. recall | Repl. F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for s in strategies:
        r, p = s.recommendations, s.replacements
        lines.append(
            f"| {s.strategy} | {r['precision'].fmt()} | {r['recall'].fmt()} | {r['f1'].fmt()} | "
            f"{p['precision'].fmt()} | {p['recall'].fmt()} | {p['f1'].fmt()} |"
        )
    lines += ["", "## Validator violations by code", ""]
    codes = sorted({c for s in strategies for c in s.violations_by_code})
    lines.append("| Code | " + " | ".join(s.strategy for s in strategies) + " |")
    lines.append("|---|" + "---:|" * len(strategies))
    for c in codes:
        lines.append(
            f"| {c} | " + " | ".join(str(s.violations_by_code.get(c, 0)) for s in strategies) + " |"
        )
    sections = sorted({m for s in strategies for m in s.missing_sections})
    if sections:
        lines += ["", "## Missing sections (count of documents)", ""]
        lines.append("| Section | " + " | ".join(s.strategy for s in strategies) + " |")
        lines.append("|---|" + "---:|" * len(strategies))
        for m in sections:
            lines.append(
                f"| {m} | "
                + " | ".join(str(s.missing_sections.get(m, 0)) for s in strategies)
                + " |"
            )
    if report.comparisons:
        lines += [
            "",
            "## Paired comparisons (A vs B on the same documents)",
            "",
            "Document-level correctness:",
            "",
            PAIRED_HEADER,
        ]
        for cmp_ in report.comparisons:
            lines.append(render_paired(cmp_.a, cmp_.b, cmp_.doc_correct))
        lines += ["", "Mean field accuracy:", "", PAIRED_HEADER]
        for cmp_ in report.comparisons:
            lines.append(render_paired(cmp_.a, cmp_.b, cmp_.field_accuracy))
    if report.notes:
        lines += ["", "## Notes", "", *[f"- {n}" for n in report.notes]]
    return "\n".join(lines) + "\n"


def save_extraction_report(
    report: ExtractionReport, out_dir: str | Path, *, stem: str = "extraction_report"
) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    md = out / f"{stem}.md"
    js = out / f"{stem}.json"
    md.write_text(render_extraction_report(report), encoding="utf-8")
    js.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    return md, js


def per_doc_table(evaluations: Sequence[StrategyEvaluation]) -> str:
    lines = [
        "| Document | " + " | ".join(e.strategy for e in evaluations) + " |",
        "|---|" + "---:|" * len(evaluations),
    ]
    by_strategy = {e.strategy: {d.doc_id: d for d in e.per_doc} for e in evaluations}
    ids = [d.doc_id for d in evaluations[0].per_doc] if evaluations else []
    for doc_id in ids:
        cells = []
        for e in evaluations:
            d = by_strategy[e.strategy].get(doc_id)
            cells.append("-" if d is None else ("ok" if d.correct else f"{d.field_accuracy:.2f}"))
        lines.append(f"| {doc_id} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"
