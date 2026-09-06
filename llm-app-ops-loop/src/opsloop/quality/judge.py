"""LLM rubric judge: helpfulness / grounding / tone on 1-5, JSON output with tolerant repair
and bounded retries. A judge failure is a *missing* score, never a default number, and every
score is stored with the judge model and judge-prompt version so a judge change is auditable."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from opsloop.jsonrepair import repair_json
from opsloop.llm import ChatMessage, ChatModel, ChatResponse, estimate_tokens
from opsloop.quality.scorers import score_answer
from opsloop.sdk.models import Trace
from opsloop.store import TraceStore

JUDGE_PROMPT_VERSION = "judge-v1"
JUDGE_SYSTEM = (
    "You are a strict reviewer of an internal assistant for Australian financial advisers. "
    "Score the ANSWER to the QUESTION using only the TOOL RESULTS as ground truth.\n"
    "Return a JSON object with integer fields helpfulness, grounding, tone (each 1-5) and a "
    "short rationale string. grounding=5 means every figure appears in the tool results; "
    "grounding=1 means figures are invented or altered. helpfulness=1 for an unjustified "
    "refusal. tone=5 for professional, direct and courteous. Return only the JSON."
)


class JudgeScores(BaseModel):
    helpfulness: int = Field(ge=1, le=5)
    grounding: int = Field(ge=1, le=5)
    tone: int = Field(ge=1, le=5)
    rationale: str = ""

    @property
    def mean(self) -> float:
        return (self.helpfulness + self.grounding + self.tone) / 3.0


@dataclass(slots=True)
class JudgeResult:
    trace_id: str
    model: str
    prompt_version: str
    scores: JudgeScores | None
    missing: bool
    repairs: int
    attempts: int
    error: str | None = None
    raw: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "scores": None if self.scores is None else self.scores.model_dump(),
            "mean": None if self.scores is None else round(self.scores.mean, 3),
            "missing": self.missing,
            "repairs": self.repairs,
            "attempts": self.attempts,
            "error": self.error,
        }


def judge_messages(question: str, answer: str, tool_outputs: Any) -> list[ChatMessage]:
    user = (
        f"QUESTION:\n{question}\n\nTOOL RESULTS (JSON):\n"
        f"{json.dumps(tool_outputs, sort_keys=True, ensure_ascii=False)}\n\n"
        f"ANSWER:\n{answer}\n\nReturn the JSON scores."
    )
    return [ChatMessage("system", JUDGE_SYSTEM), ChatMessage("user", user)]


_Q = re.compile(
    r"QUESTION:\n(.*?)\n\nTOOL RESULTS \(JSON\):\n(.*?)\n\nANSWER:\n(.*)\n\nReturn", re.DOTALL
)


@dataclass
class FakeJudgeModel:
    """Scripted judge: derives the rubric from the heuristic scorers (so it agrees with them on
    grounding and refusals) and, with ``invalid_rate`` > 0, returns broken JSON on a seeded
    subset of calls to exercise the repair / missing-score path."""

    invalid_rate: float = 0.0
    seed: int = 0
    name_: str = "northshore-judge-8b"
    calls: list[list[ChatMessage]] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.name_

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,  # noqa: ARG002 - protocol signature
        temperature: float = 0.0,  # noqa: ARG002
    ) -> ChatResponse:
        self.calls.append(list(messages))
        user = messages[-1].content
        m = _Q.search(user)
        question, tools_text, answer = (
            (m.group(1), m.group(2), m.group(3)) if m else ("", "{}", user)
        )
        rng = random.Random(f"{self.seed}:{answer}")
        if self.invalid_rate > 0 and rng.random() < self.invalid_rate:
            text = '{"helpfulness": 4, "grounding": '  # truncated on purpose
        else:
            tools = repair_json(tools_text).value or {}
            h = score_answer(answer, tool_outputs=tools, question=question)
            grounding = 5 if h.grounded else 1
            helpfulness = 1 if h.refusal else (5 if h.grounded else 3)
            tone = 5 if h.tone_ok or h.tone_ok is None else 3
            if h.pii_leak:
                helpfulness = min(helpfulness, 2)
            scores = {
                "helpfulness": helpfulness,
                "grounding": grounding,
                "tone": tone,
                "rationale": "refusal"
                if h.refusal
                else (
                    "figures match tool results"
                    if h.grounded
                    else f"ungrounded: {h.ungrounded_numbers[:2]}"
                ),
            }
            text = "```json\n" + json.dumps(scores) + "\n```"
        return ChatResponse(
            text=text,
            model=self.name_,
            prompt_tokens=sum(estimate_tokens(x.content) for x in messages),
            completion_tokens=estimate_tokens(text),
        )


def judge_answer(
    model: ChatModel,
    *,
    trace_id: str,
    question: str,
    answer: str,
    tool_outputs: Any,
    max_attempts: int = 2,
) -> JudgeResult:
    messages = judge_messages(question, answer, tool_outputs)
    repairs = 0
    last_error: str | None = None
    raw = ""
    for attempt in range(1, max_attempts + 1):
        try:
            resp = model.chat(messages, max_tokens=300)
        except Exception as exc:
            last_error = f"judge call failed: {exc}"
            continue
        raw = resp.text
        result = repair_json(raw)
        repairs += result.repairs
        if result.value is None:
            last_error = result.error
            continue
        try:
            scores = JudgeScores.model_validate(result.value)
        except ValidationError as exc:
            last_error = f"schema: {exc.errors()[0]['msg']}"
            continue
        return JudgeResult(
            trace_id, model.name, JUDGE_PROMPT_VERSION, scores, False, repairs, attempt, None, raw
        )
    return JudgeResult(
        trace_id,
        model.name,
        JUDGE_PROMPT_VERSION,
        None,
        True,
        repairs,
        max_attempts,
        last_error,
        raw,
    )


def judge_trace(model: ChatModel, trace: Trace, *, max_attempts: int = 2) -> JudgeResult:
    return judge_answer(
        model,
        trace_id=trace.trace_id,
        question=trace.input_text,
        answer=trace.output_text,
        tool_outputs=trace.tool_outputs(),
        max_attempts=max_attempts,
    )


def judge_and_store(
    store: TraceStore,
    model: ChatModel,
    trace_ids: Sequence[str],
    *,
    ts: float,
    max_attempts: int = 2,
    slo_eligible: bool = True,
) -> list[JudgeResult]:
    """Judge and persist. ``slo_eligible=False`` keeps the score row (auditable) but does not
    write the trace's ``judge`` column, so a failure-targeted sample cannot bias the SLO."""
    results: list[JudgeResult] = []
    for trace_id in trace_ids:
        trace = store.get_trace(trace_id)
        if trace is None or trace.status != "ok":
            continue
        result = judge_trace(model, trace, max_attempts=max_attempts)
        store.add_score(
            trace_id,
            scorer="judge",
            model=result.model,
            prompt_version=result.prompt_version,
            ts=ts,
            missing=result.missing,
            repairs=result.repairs,
            payload=result.as_dict(),
            judge_mean=None if (result.scores is None or not slo_eligible) else result.scores.mean,
        )
        results.append(result)
    return results


def judge_summary(results: Sequence[JudgeResult]) -> dict[str, Any]:
    scored = [r for r in results if r.scores is not None]
    n = len(results)
    return {
        "judged": n,
        "scored": len(scored),
        "missing": n - len(scored),
        "repairs": sum(r.repairs for r in results),
        "helpfulness_mean": round(
            sum(r.scores.helpfulness for r in scored if r.scores) / len(scored), 3
        )
        if scored
        else None,
        "grounding_mean": round(
            sum(r.scores.grounding for r in scored if r.scores) / len(scored), 3
        )
        if scored
        else None,
        "tone_mean": round(sum(r.scores.tone for r in scored if r.scores) / len(scored), 3)
        if scored
        else None,
        "overall_mean": round(sum(r.scores.mean for r in scored if r.scores) / len(scored), 3)
        if scored
        else None,
    }
