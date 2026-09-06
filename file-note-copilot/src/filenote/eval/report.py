"""Markdown rendering of an evaluation report."""

from __future__ import annotations

from filenote.eval.runner import PRIMARY_SECTIONS, SECONDARY_SECTIONS, EvalReport, StrategyRun


def _ci(d: dict[str, float], *, pct: bool = False, digits: int = 3) -> str:
    if pct:
        return f"{100 * d['mean']:.1f}% [{100 * d['low']:.1f}, {100 * d['high']:.1f}]"
    return f"{d['mean']:.{digits}f} [{d['low']:.{digits}f}, {d['high']:.{digits}f}]"


def _run_header(run: StrategyRun) -> str:
    extras = []
    if run.corruption is not None:
        extras.append(f"corruption {run.corruption:g}")
    extras.append("pseudonymised" if run.pseudonymise else "raw names")
    return f"{run.name} ({run.strategy}, {run.model}, {', '.join(extras)})"


def _totals_rows(run: StrategyRun) -> list[tuple[str, str]]:
    t = run.totals
    a = run.aggregate
    return [
        (
            "Hallucination rate (no gold match AND verifier-unsupported)",
            _ci(a["hallucination_rate"], pct=True),
        ),
        ("Unmatched predicted claims", _ci(a["unmatched_rate"], pct=True)),
        ("Omission rate", _ci(a["omission_rate"], pct=True)),
        ("Compliance flags accuracy", _ci(a["compliance_accuracy"], pct=True)),
        ("Verifier-supported fraction", _ci(a["verifier_supported_fraction"], pct=True)),
        ("Numeric grounding rate", _ci(a["numeric_grounding_rate"], pct=True)),
        (
            "Action-item due date exact or within 3 days",
            f"{100 * t['due_within_tolerance']:.1f}%",
        ),
        ("Hallucinated claims (total)", f"{int(t['hallucinated_claims'])}"),
        (
            "... surfaced to the adviser as unsupported",
            f"{int(t['hallucinated_surfaced'])} ({100 * t['surfaced_rate']:.1f}%)",
        ),
        ("Unsupported flags left in final notes", f"{int(t['unsupported_remaining'])}"),
        (
            "Repair pass: cited / dropped",
            f"{int(t['repair_cited'])} / {int(t['repair_dropped'])}",
        ),
        ("Small-talk segments cited", f"{int(t['small_talk_leaks'])}"),
        (
            "Hallucination-free meetings",
            f"{int(t['hallucination_free_meetings'])} / {int(t['meetings'])}",
        ),
    ]


def _run_section(run: StrategyRun) -> list[str]:
    t = run.totals
    a = run.aggregate
    lines = [
        f"### {_run_header(run)}",
        "",
        f"- wall clock {run.wall_s:.1f} s; model calls {int(t['model_calls'])}; JSON repairs "
        f"{int(t['json_repairs'])}; parse failures {int(t['parse_failures'])}; failed windows "
        f"{int(t['failed_windows'])}; failed meetings {int(t['failed'])}",
        f"- tokens: prompt {int(t['prompt_tokens'])}, completion {int(t['completion_tokens'])}; "
        f"latency per meeting {_ci(a['latency_s'])} s",
        "",
        "| Section | Precision | Recall | F1 |",
        "|---|---:|---:|---:|",
    ]
    for s in PRIMARY_SECTIONS:
        lines.append(
            f"| {s} | {_ci(a[f'{s}_precision'])} | {_ci(a[f'{s}_recall'])} | "
            f"**{_ci(a[f'{s}_f1'])}** |"
        )
    for s in SECONDARY_SECTIONS:
        lines.append(f"| {s} | | | {_ci(a[f'{s}_f1'])} |")
    lines.append(f"| **macro F1 (4 primary sections)** | | | **{_ci(a['macro_f1'])}** |")
    lines += ["", "| Metric | Value |", "|---|---:|"]
    lines.extend(f"| {k} | {v} |" for k, v in _totals_rows(run))
    lines.append("")
    return lines


def render_report_md(report: EvalReport) -> str:
    corpus = report.corpus
    lines = [
        "# File-note evaluation report",
        "",
        f"- created: {report.created}",
        f"- corpus: {corpus.get('meetings', '?')} meetings, seed {corpus.get('seed', '?')}",
        f"- intervals: 95 % bootstrap over meetings, {corpus.get('n_boot', 1000)} resamples; "
        "the gate uses the conservative bound",
        "",
        "## Runs",
        "",
    ]
    for run in report.runs:
        lines.extend(_run_section(run))
    if report.comparisons:
        lines += [
            "## Paired comparisons (same transcripts)",
            "",
            "| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p "
            "| Verdict |",
            "|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|",
        ]
        for c in report.comparisons:
            r = c.result
            lines.append(
                f"| {c.a} | {c.b} | {c.metric} | {float(r['mean_a']):.3f} | "
                f"{float(r['mean_b']):.3f} | {float(r['delta']):+.3f} | "
                f"[{float(r['ci_low']):+.3f}, {float(r['ci_high']):+.3f}] | "
                f"{float(r['p_improve']):.2f} | {r['wins']} / {r['losses']} | "
                f"{float(r['mcnemar_p']):.3f} | {r['verdict']} |"
            )
        lines += [
            "",
            "McNemar pairs are the binary per-meeting outcome *hallucination-free note* "
            "(reported on the macro-F1 row); other rows use the sign of the per-meeting "
            "difference.",
            "",
        ]
    if report.gate:
        failures = report.gate.get("failures", [])
        lines.append(
            f"## Gate on `{report.gate.get('run')}`: "
            + ("**PASS**" if not failures else "**FAIL**")
        )
        lines.extend(f"- {f}" for f in failures)
        lines.append("")
    return "\n".join(lines) + "\n"
