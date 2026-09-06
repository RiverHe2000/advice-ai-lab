"""Deterministic trace replay: rebuild the exact prompt (prompt version + recorded variables +
recorded tool outputs), re-run the model with tool spans stubbed by the recorded outputs, diff
the new answer against the recorded one, and re-score both."""

from __future__ import annotations

import difflib
from typing import Any

from pydantic import BaseModel
from rapidfuzz import fuzz

from opsloop.demo.app import build_messages
from opsloop.llm import ChatModel, ModelError
from opsloop.prompts.registry import PromptRegistry
from opsloop.quality.scorers import score_answer
from opsloop.sdk.models import Trace
from opsloop.sdk.pricing import PriceTable


class ReplayResult(BaseModel):
    trace_id: str
    prompt_ref: str
    prompt_hash: str
    recorded_prompt_hash: str | None
    prompt_changed_since_recording: bool
    model: str
    recorded_model: str | None
    recorded_answer: str
    new_answer: str
    identical: bool
    similarity: float
    diff: str
    recorded_scores: dict[str, Any]
    new_scores: dict[str, Any]
    prompt_tokens: int | None
    completion_tokens: int | None
    cost_usd: float | None
    cost_missing: bool
    error: str | None = None


def replay_trace(
    trace: Trace,
    registry: PromptRegistry,
    model: ChatModel,
    *,
    prices: PriceTable | None = None,
    prompt_version: str | None = None,
) -> ReplayResult:
    prices = prices or PriceTable()
    version = prompt_version or trace.prompt_version
    spec = registry.get(f"{trace.prompt_name}@{version}")
    variables = dict(trace.attributes.get("prompt.variables", {}))
    tool_outputs = trace.tool_outputs()
    messages = build_messages(spec, variables, trace.input_text, tool_outputs)
    recorded_hash = trace.attributes.get("prompt.hash")
    llm_spans = trace.spans_of("llm")
    recorded_model = llm_spans[0].model if llm_spans else None
    error: str | None = None
    try:
        resp = model.chat(messages, max_tokens=int(spec.metadata.get("max_tokens", 400)))
        new_answer, resp_model = resp.text, resp.model
        prompt_tokens, completion_tokens = resp.prompt_tokens, resp.completion_tokens
    except ModelError as exc:
        error = str(exc)
        new_answer, resp_model = "", model.name
        prompt_tokens = completion_tokens = None
    cost = prices.cost(resp_model, prompt_tokens, completion_tokens)
    recorded = score_answer(
        trace.output_text,
        tool_outputs=tool_outputs,
        question=trace.input_text,
        json_expected=trace.json_expected,
    )
    new = score_answer(
        new_answer,
        tool_outputs=tool_outputs,
        question=trace.input_text,
        json_expected=trace.json_expected,
    )
    diff = "\n".join(
        difflib.unified_diff(
            trace.output_text.splitlines(),
            new_answer.splitlines(),
            fromfile="recorded",
            tofile=f"replay[{resp_model}]",
            lineterm="",
        )
    )
    return ReplayResult(
        trace_id=trace.trace_id,
        prompt_ref=spec.ref,
        prompt_hash=spec.content_hash,
        recorded_prompt_hash=None if recorded_hash is None else str(recorded_hash),
        prompt_changed_since_recording=recorded_hash is not None
        and recorded_hash != spec.content_hash,
        model=resp_model,
        recorded_model=recorded_model,
        recorded_answer=trace.output_text,
        new_answer=new_answer,
        identical=new_answer == trace.output_text,
        similarity=round(float(fuzz.ratio(trace.output_text, new_answer)) / 100.0, 4),
        diff=diff,
        recorded_scores=recorded.as_dict(),
        new_scores=new.as_dict(),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost.usd,
        cost_missing=cost.missing,
        error=error,
    )


def render_markdown(r: ReplayResult) -> str:
    lines = [
        f"# Replay of trace `{r.trace_id}`",
        "",
        f"- prompt: `{r.prompt_ref}` (hash `{r.prompt_hash}`; recorded `{r.recorded_prompt_hash}`"
        f"{', CHANGED since recording' if r.prompt_changed_since_recording else ''})",
        f"- model: `{r.model}` (recorded `{r.recorded_model}`)",
        f"- identical answer: **{'yes' if r.identical else 'no'}** (similarity {r.similarity:.3f})",
        f"- recorded quality {r.recorded_scores['quality']} -> replay quality "
        f"{r.new_scores['quality']}; grounded {r.recorded_scores['grounded']} -> "
        f"{r.new_scores['grounded']}",
        f"- tokens {r.prompt_tokens} / {r.completion_tokens}, cost "
        f"{'missing' if r.cost_missing else f'${r.cost_usd:.6f}'}",
    ]
    if r.error:
        lines.append(f"- error: {r.error}")
    lines += ["", "## Recorded", "", r.recorded_answer, "", "## Replay", "", r.new_answer, ""]
    if r.diff:
        lines += ["## Diff", "", "```diff", r.diff, "```", ""]
    return "\n".join(lines)
