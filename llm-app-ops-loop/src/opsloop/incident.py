"""Incident report generation: classify every failure in a window, aggregate by prompt version,
tool, topic and time bucket, locate the change point in the failure-rate series, and write a
markdown incident report skeleton (timeline, impact, suspected cause, evidence, follow-ups)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from typing import Any

import numpy as np
from pydantic import BaseModel, Field

from opsloop.monitor.drift import HashingEmbedder, TopicModel
from opsloop.stats import two_proportion_test
from opsloop.store import SpanErrorRow, TraceRow, TraceStore
from opsloop.timeutil import iso

FAILURE_KINDS = (
    "timeout",
    "provider_error",
    "tool_error",
    "invalid_json",
    "guardrail_block",
    "pii_leak",
    "ungrounded",
    "refusal",
    "low_judge_score",
    "negative_feedback",
)


def classify_failures(row: TraceRow, *, low_judge: float = 3.0) -> list[str]:
    kinds: list[str] = []
    if row.status == "error":
        if row.error_class == "timeout":
            kinds.append("timeout")
        elif row.error_class == "tool_error":
            kinds.append("tool_error")
        else:
            kinds.append("provider_error")
    if row.json_expected and row.json_valid is False:
        kinds.append("invalid_json")
    if row.attributes.get("guardrail.blocked"):
        kinds.append("guardrail_block")
    if row.pii_leak:
        kinds.append("pii_leak")
    if row.grounded is False:
        kinds.append("ungrounded")
    if row.refusal and not row.attributes.get("guardrail.blocked"):
        kinds.append("refusal")
    if row.judge is not None and row.judge < low_judge:
        kinds.append("low_judge_score")
    if row.negative_feedback:
        kinds.append("negative_feedback")
    return kinds


class ChangePoint(BaseModel):
    bucket_index: int
    ts: float
    end_ts: float | None = None
    before_rate: float
    after_rate: float
    statistic: float


def change_point(series: Sequence[float], counts: Sequence[int]) -> ChangePoint | None:
    """Single change point by binary segmentation on the per-bucket failure rate: the split
    maximising the standardised difference of means (weighted by bucket counts)."""
    x = np.asarray(series, dtype=np.float64)
    w = np.asarray(counts, dtype=np.float64)
    n = x.size
    if n < 4:
        return None
    best: tuple[float, int, float, float] | None = None
    for k in range(2, n - 1):
        wa, wb = w[:k].sum(), w[k:].sum()
        if wa <= 0 or wb <= 0:
            continue
        ma = float((x[:k] * w[:k]).sum() / wa)
        mb = float((x[k:] * w[k:]).sum() / wb)
        pooled = (ma * wa + mb * wb) / (wa + wb)
        se = math.sqrt(max(pooled * (1 - pooled), 1e-9) * (1 / wa + 1 / wb))
        stat = abs(mb - ma) / se
        if best is None or stat > best[0]:
            best = (stat, k, ma, mb)
    if best is None:
        return None
    stat, k, ma, mb = best
    return ChangePoint(
        bucket_index=k,
        ts=0.0,
        before_rate=round(ma, 4),
        after_rate=round(mb, 4),
        statistic=round(stat, 3),
    )


def elevated_segment(rates: Sequence[float], counts: Sequence[int]) -> tuple[int, int] | None:
    """The contiguous run of buckets around the peak whose failure rate exceeds the overall
    rate - the incident's footprint in time (a burst has two edges; a single change point only
    finds one of them)."""
    if not rates or sum(counts) == 0:
        return None
    overall = sum(r * c for r, c in zip(rates, counts, strict=True)) / sum(counts)
    peak = max(range(len(rates)), key=lambda i: (rates[i], counts[i]))
    if rates[peak] <= overall:
        return None
    i0 = i1 = peak
    while i0 > 0 and rates[i0 - 1] > overall:
        i0 -= 1
    while i1 < len(rates) - 1 and rates[i1 + 1] > overall:
        i1 += 1
    return i0, i1


class IncidentReport(BaseModel):
    window_start: float
    window_end: float
    bucket_minutes: float
    n_requests: int
    n_failed: int
    failure_rate: float
    by_kind: dict[str, int]
    by_prompt_version: dict[str, dict[str, int]]
    by_tool: dict[str, int]
    by_topic: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    change_point: ChangePoint | None
    suspected_cause: str
    evidence: list[str]
    follow_ups: list[str] = Field(default_factory=list)


def build_incident_report(
    store: TraceStore,
    *,
    since: float,
    until: float,
    bucket_minutes: float = 10.0,
    low_judge: float = 3.0,
    seed: int = 0,
) -> IncidentReport:
    rows = store.rows(since, until)
    span_errors = store.span_errors(since, until)
    return analyse(
        rows,
        span_errors,
        since=since,
        until=until,
        bucket_minutes=bucket_minutes,
        low_judge=low_judge,
        seed=seed,
    )


def analyse(
    rows: Sequence[TraceRow],
    span_errors: Sequence[SpanErrorRow],
    *,
    since: float,
    until: float,
    bucket_minutes: float = 10.0,
    low_judge: float = 3.0,
    seed: int = 0,
) -> IncidentReport:
    kinds_by_trace = {r.trace_id: classify_failures(r, low_judge=low_judge) for r in rows}
    failed = [r for r in rows if kinds_by_trace[r.trace_id]]
    by_kind = Counter(k for ks in kinds_by_trace.values() for k in ks)
    by_version: dict[str, dict[str, int]] = {}
    for r in rows:
        d = by_version.setdefault(r.prompt_version, {"requests": 0, "failed": 0})
        d["requests"] += 1
        if kinds_by_trace[r.trace_id]:
            d["failed"] += 1
    by_tool = Counter(
        f"{s.name}:{s.error_class or 'error'}" for s in span_errors if s.kind == "tool"
    )
    # topics: fit on the window's inputs, report failure rate per topic
    by_topic: list[dict[str, Any]] = []
    texts = [r.input_text for r in rows if r.input_text]
    if len(texts) >= 16:
        tm = TopicModel(HashingEmbedder(), k=min(8, len(texts) // 4), seed=seed).fit(texts)
        labels = tm.assign(texts)
        terms = tm.top_terms(texts, labels)
        idx = 0
        per_topic: dict[int, list[TraceRow]] = {}
        for r in rows:
            if not r.input_text:
                continue
            per_topic.setdefault(int(labels[idx]), []).append(r)
            idx += 1
        for t, trs in sorted(per_topic.items()):
            nf = sum(1 for r in trs if kinds_by_trace[r.trace_id])
            by_topic.append(
                {
                    "topic": t,
                    "terms": terms[t],
                    "requests": len(trs),
                    "failed": nf,
                    "failure_rate": round(nf / len(trs), 4),
                }
            )
        by_topic.sort(key=lambda d: -float(d["failure_rate"]))
    # timeline buckets
    width = bucket_minutes * 60.0
    n_buckets = max(1, math.ceil((until - since) / width))
    buckets: list[dict[str, Any]] = [
        {"start": since + i * width, "requests": 0, "failed": 0, "kinds": Counter()}
        for i in range(n_buckets)
    ]
    for r in rows:
        i = min(int((r.start_ts - since) // width), n_buckets - 1)
        buckets[i]["requests"] += 1
        ks = kinds_by_trace[r.trace_id]
        if ks:
            buckets[i]["failed"] += 1
            buckets[i]["kinds"].update(ks)
    timeline = [
        {
            "start": iso(b["start"]),
            "requests": b["requests"],
            "failed": b["failed"],
            "failure_rate": round(b["failed"] / b["requests"], 4) if b["requests"] else None,
            "kinds": dict(b["kinds"].most_common(3)),
        }
        for b in buckets
    ]
    rates = [b["failed"] / b["requests"] if b["requests"] else 0.0 for b in buckets]
    counts = [int(b["requests"]) for b in buckets]
    segment = elevated_segment(rates, counts)
    cp: ChangePoint | None = None
    elevated_ids: set[str] = set()
    if segment is not None:
        i0, i1 = segment
        for r in rows:
            bucket = min(int((r.start_ts - since) // width), n_buckets - 1)
            if i0 <= bucket <= i1:
                elevated_ids.add(r.trace_id)
        n_in = len(elevated_ids)
        n_out = len(rows) - n_in
        f_in = sum(1 for r in rows if r.trace_id in elevated_ids and kinds_by_trace[r.trace_id])
        f_out = sum(1 for r in failed if r.trace_id not in elevated_ids)
        test = two_proportion_test(f_in, n_in, f_out, n_out, alternative="greater")
        cp = ChangePoint(
            bucket_index=i0,
            ts=buckets[i0]["start"],
            end_ts=buckets[i1]["start"] + width,
            before_rate=round(f_out / n_out, 4) if n_out else 0.0,
            after_rate=round(f_in / n_in, 4) if n_in else 0.0,
            statistic=0.0 if math.isnan(test.z) else round(test.z, 3),
        )
    cause, evidence = _suspect(
        rows, failed, kinds_by_trace, elevated_ids, by_version, by_tool, by_topic, cp
    )
    follow_ups = _follow_ups(by_kind)
    return IncidentReport(
        window_start=since,
        window_end=until,
        bucket_minutes=bucket_minutes,
        n_requests=len(rows),
        n_failed=len(failed),
        failure_rate=round(len(failed) / len(rows), 4) if rows else 0.0,
        by_kind=dict(by_kind.most_common()),
        by_prompt_version=by_version,
        by_tool=dict(by_tool.most_common()),
        by_topic=by_topic[:8],
        timeline=timeline,
        change_point=cp,
        suspected_cause=cause,
        evidence=evidence,
        follow_ups=follow_ups,
    )


GROUPS: dict[str, tuple[str, ...]] = {
    "availability": ("timeout", "provider_error", "tool_error"),
    "behaviour": ("ungrounded", "refusal", "invalid_json"),
    "pii": ("pii_leak",),
    "feedback": ("negative_feedback", "low_judge_score"),
}
CAUSES = {
    "availability": "model provider availability (timeouts / 5xx)",
    "tools": "an upstream data service used by a tool",
    "behaviour": "a prompt or model behaviour change",
    "pii": "a tool or prompt exposing identifiers to the model",
    "feedback": "user-visible answer quality",
}


def _group_rate(
    rows: Sequence[TraceRow], kinds_by_trace: dict[str, list[str]], group: str
) -> float:
    if not rows:
        return 0.0
    wanted = set(GROUPS[group])
    return sum(1 for r in rows if set(kinds_by_trace[r.trace_id]) & wanted) / len(rows)


def _suspect(
    rows: Sequence[TraceRow],
    failed: Sequence[TraceRow],
    kinds_by_trace: dict[str, list[str]],
    elevated_ids: set[str],
    by_version: dict[str, dict[str, int]],
    by_tool: Counter[str],
    by_topic: list[dict[str, Any]],
    cp: ChangePoint | None,
) -> tuple[str, list[str]]:
    """Name the failure *group* that rose most during the elevated period (falling back to the
    largest group in the window), then add the prompt-version, tool and topic evidence."""
    evidence: list[str] = []
    if not failed:
        return "no failures in the window", evidence
    by_kind = Counter(k for ks in kinds_by_trace.values() for k in ks)
    inside = [r for r in rows if r.trace_id in elevated_ids]
    outside = [r for r in rows if r.trace_id not in elevated_ids]
    increase: dict[str, tuple[float, float]] = {}
    if inside and outside:
        for g in GROUPS:
            r_in = _group_rate(inside, kinds_by_trace, g)
            r_out = _group_rate(outside, kinds_by_trace, g)
            increase[g] = (r_in - r_out, r_in)
    if increase and max(v[0] for v in increase.values()) > 0.02:
        group = max(increase, key=lambda g: increase[g][0])
        delta, r_in = increase[group]
        evidence.append(
            f"during the elevated period, {group} failures rose from {r_in - delta:.1%} to "
            f"{r_in:.1%} of requests"
        )
    else:
        group = max(GROUPS, key=lambda g: sum(by_kind.get(k, 0) for k in GROUPS[g]))
    top = ", ".join(f"{k} {by_kind[k]}" for k in GROUPS[group] if by_kind.get(k))
    evidence.append(
        f"largest failure group: {group} ({top}) of {len(failed)} failed requests in the window"
    )
    cause_key = group
    if group == "availability":
        tool_errors = by_kind.get("tool_error", 0)
        if tool_errors > by_kind.get("timeout", 0) + by_kind.get("provider_error", 0):
            cause_key = "tools"
    parts: list[str] = [CAUSES[cause_key]]
    versions = {v: d for v, d in by_version.items() if d["requests"] >= 10}
    if len(versions) > 1:
        worst = max(versions.items(), key=lambda kv: kv[1]["failed"] / kv[1]["requests"])
        best = min(versions.items(), key=lambda kv: kv[1]["failed"] / kv[1]["requests"])
        wr = worst[1]["failed"] / worst[1]["requests"]
        br = best[1]["failed"] / best[1]["requests"]
        if wr - br > 0.10:
            parts.append(
                f"prompt version {worst[0]} (failure rate {wr:.0%} vs {br:.0%} for {best[0]})"
            )
            evidence.append(
                f"prompt {worst[0]}: {worst[1]['failed']}/{worst[1]['requests']} failed; "
                f"{best[0]}: {best[1]['failed']}/{best[1]['requests']}"
            )
    if by_tool:
        tool, n = by_tool.most_common(1)[0]
        evidence.append(f"tool span errors: {tool} x{n}")
    if by_topic:
        t = by_topic[0]
        if float(t["failure_rate"]) > 0.5 and int(t["requests"]) >= 10:
            evidence.append(
                f"topic {t['topic']} ({' '.join(t['terms'])}) failure rate "
                f"{t['failure_rate']:.0%} on {t['requests']} requests"
            )
    if cp is not None and cp.statistic > 3.0:
        until_text = f" to {iso(cp.end_ts)}" if cp.end_ts is not None else ""
        evidence.append(
            f"elevated from {iso(cp.ts)}{until_text}: failure rate {cp.after_rate:.1%} "
            f"vs {cp.before_rate:.1%} outside (z={cp.statistic})"
        )
    examples = [r.trace_id for r in failed[:5]]
    evidence.append("example traces: " + ", ".join(examples))
    return "; ".join(parts), evidence


def _follow_ups(by_kind: Counter[str]) -> list[str]:
    items: list[str] = []
    if by_kind.get("timeout") or by_kind.get("provider_error"):
        items.append(
            "Confirm provider status / rate limits; check retry + fallback configuration "
            "in the gateway."
        )
    if by_kind.get("tool_error"):
        items.append(
            "Check the upstream data service health and the tool's timeout and error handling."
        )
    if by_kind.get("ungrounded") or by_kind.get("invalid_json") or by_kind.get("refusal"):
        items.append(
            "Diff the active prompt against the last known-good version; replay failed "
            "traces with both."
        )
        items.append("Add the failed traces to the review queue and grow the regression dataset.")
    if by_kind.get("pii_leak"):
        items.append(
            "Find the tool output carrying identifiers; add a redaction test; rotate any "
            "exposed identifiers per policy."
        )
    if by_kind.get("negative_feedback"):
        items.append(
            "Read the comments and 'which part was wrong' tags; sample those traces for the judge."
        )
    items.append("Record the incident timeline and the SLO impact in the post-incident review.")
    return items


def render_markdown(r: IncidentReport, *, title: str = "Incident report (draft)") -> str:
    lines = [
        f"# {title}",
        "",
        f"Window {iso(r.window_start)} to {iso(r.window_end)} ({r.n_requests} requests, "
        f"{r.n_failed} with at least one failure, failure rate {r.failure_rate:.1%}).",
        "",
        "## Timeline",
        "",
        "| Bucket start | Requests | Failed | Rate | Top kinds |",
        "|---|---:|---:|---:|---|",
    ]
    for b in r.timeline:
        rate = "-" if b["failure_rate"] is None else f"{b['failure_rate']:.1%}"
        kinds = ", ".join(f"{k} {v}" for k, v in b["kinds"].items()) or "-"
        lines.append(f"| {b['start']} | {b['requests']} | {b['failed']} | {rate} | {kinds} |")
    if r.change_point is not None:
        cp = r.change_point
        until_text = f" to **{iso(cp.end_ts)}**" if cp.end_ts is not None else ""
        lines += [
            "",
            f"Elevated period: **{iso(cp.ts)}**{until_text} (failure rate {cp.after_rate:.1%} "
            f"inside vs {cp.before_rate:.1%} outside; z = {cp.statistic}).",
        ]
    lines += ["", "## Impact", "", "| Failure kind | Count |", "|---|---:|"]
    for k, v in r.by_kind.items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "| Prompt version | Requests | Failed |", "|---|---:|---:|"]
    for version, d in r.by_prompt_version.items():
        lines.append(f"| {version} | {d['requests']} | {d['failed']} |")
    if r.by_tool:
        lines += ["", "| Tool span error | Count |", "|---|---:|"]
        for k, v in r.by_tool.items():
            lines.append(f"| {k} | {v} |")
    if r.by_topic:
        lines += ["", "| Topic | Terms | Requests | Failed | Rate |", "|---:|---|---:|---:|---:|"]
        for t in r.by_topic:
            lines.append(
                f"| {t['topic']} | {' '.join(t['terms'])} | {t['requests']} | {t['failed']} | "
                f"{t['failure_rate']:.1%} |"
            )
    lines += ["", "## Suspected cause", "", r.suspected_cause, "", "## Evidence", ""]
    lines += [f"- {e}" for e in r.evidence]
    lines += ["", "## Follow-ups", ""]
    lines += [f"- [ ] {f}" for f in r.follow_ups]
    return "\n".join(lines) + "\n"
