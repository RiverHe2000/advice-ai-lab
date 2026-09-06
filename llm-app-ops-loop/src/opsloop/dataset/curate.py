"""From a production trace to a curated evaluation case.

A case snapshots the input, the context the model saw (tool outputs, prompt version), the
expected properties (must / must-not contain, numeric facts the answer should quote), an
optional reference answer, tags for slicing, and provenance (trace id, reviewer, date). The
automatic pass proposes expectations from the trace; a reviewer edits them in the queue file."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from opsloop.quality.scorers import is_refusal
from opsloop.sdk.models import Trace
from opsloop.store import TraceStore
from opsloop.timeutil import iso


class Expected(BaseModel):
    must_contain: list[str] = Field(default_factory=list)
    must_not_contain: list[str] = Field(default_factory=list)
    numeric_facts: list[float] = Field(default_factory=list)
    json_expected: bool = False
    allow_refusal: bool = False


class Provenance(BaseModel):
    trace_id: str
    reviewer: str
    date: str
    prompt_version: str
    source: str = "production"
    notes: str = ""


class CuratedCase(BaseModel):
    id: str
    input: str
    context: dict[str, Any] = Field(default_factory=dict)
    expected: Expected = Field(default_factory=Expected)
    reference: str | None = None
    tags: list[str] = Field(default_factory=list)
    provenance: Provenance


class ReviewItem(BaseModel):
    """A queue entry: the proposed case plus what the reviewer needs to decide."""

    case: CuratedCase
    status: str = "pending"  # pending | accepted | rejected
    heuristic: dict[str, Any] = Field(default_factory=dict)
    feedback: list[dict[str, Any]] = Field(default_factory=list)
    judge: list[dict[str, Any]] = Field(default_factory=list)
    recorded_answer: str = ""


def _numeric_facts(trace: Trace) -> list[float]:
    """Numbers the recorded answer quoted that exist in the tool outputs (facts worth keeping)."""
    from opsloop.quality.scorers import evidence_values, extract_numbers

    values, _ = evidence_values(trace.tool_outputs())
    facts: list[float] = []
    for _, v in extract_numbers(trace.output_text):
        if any(abs(v - e) <= 0.005 for e in values) and v not in facts:
            facts.append(v)
    return facts[:6]


def curate_from_trace(trace: Trace, *, reviewer: str, now: float) -> CuratedCase:
    intent = str(trace.attributes.get("app.intent", "unknown"))
    category = str(trace.attributes.get("app.category", "unknown"))
    blocked = bool(trace.attributes.get("guardrail.blocked", False))
    out_of_scope = category == "out_of_scope"
    refusal = is_refusal(trace.output_text)
    expected = Expected(
        json_expected=trace.json_expected and not blocked,
        allow_refusal=out_of_scope or blocked,
        must_not_contain=[] if (out_of_scope or blocked) else ["cannot answer", "I can only help"],
        numeric_facts=[] if (refusal or trace.status != "ok") else _numeric_facts(trace),
    )
    if out_of_scope:
        expected.must_contain = ["can only help"]
    tags = [category, intent, f"prompt:{trace.prompt_version}"]
    if trace.json_expected:
        tags.append("json")
    if out_of_scope:
        tags.append("out_of_scope")
    return CuratedCase(
        id=f"case-{trace.trace_id[:12]}",
        input=trace.input_text,
        context={
            "tool_outputs": trace.tool_outputs(),
            "prompt_variables": trace.attributes.get("prompt.variables", {}),
            "prompt_version": trace.prompt_version,
        },
        expected=expected,
        reference=None if (trace.status != "ok" or refusal) else trace.output_text,
        tags=tags,
        provenance=Provenance(
            trace_id=trace.trace_id,
            reviewer=reviewer,
            date=iso(now),
            prompt_version=trace.prompt_version,
            source="production",
        ),
    )


def build_review_queue(
    store: TraceStore, trace_ids: Sequence[str], *, reviewer: str, now: float
) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for trace_id in trace_ids:
        trace = store.get_trace(trace_id)
        if trace is None or trace.status != "ok":
            continue
        case = curate_from_trace(trace, reviewer=reviewer, now=now)
        items.append(
            ReviewItem(
                case=case,
                heuristic={
                    "quality": trace.attributes.get("quality"),
                },
                feedback=store.feedback_for(trace_id),
                judge=store.scores_for(trace_id),
                recorded_answer=trace.output_text,
            )
        )
    return items


def write_review_queue(items: Sequence[ReviewItem], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item.model_dump(mode="json"), ensure_ascii=False) + "\n")
    return len(items)


def read_review_queue(path: Path) -> list[ReviewItem]:
    items: list[ReviewItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(ReviewItem.model_validate(json.loads(line)))
    return items
