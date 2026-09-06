"""The instrumented Northshore Adviser Assistant: guardrail span (input PII policy), tool spans
with recorded inputs/outputs, an LLM span with model + usage, prompt name/version/variables on
the trace. Failure injection enters through ``Faults`` (latency multipliers, error rates, the
TFN-leaking tool defect, model corruption); simulated time advances through the clock."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field
from typing import Any

from opsloop.demo.book import ClientBook
from opsloop.demo.model import Corruption, DemoFakeModel
from opsloop.demo.questions import Question
from opsloop.demo.tools import Tools
from opsloop.llm import ChatMessage, ChatModel, ModelError
from opsloop.pii import find_pii
from opsloop.prompts.registry import PromptRegistry, PromptSpec
from opsloop.sdk.tracing import Tracer
from opsloop.timeutil import SimClock

APP_VERSION = "1.4.0"
PROMPT_NAME = "adviser_assistant"
BLOCKED_TEXT = (
    "This message was blocked by the input guardrail because it contains a tax file number. "
    "Remove the identifier and ask again."
)
UNAVAILABLE_TEXT = "The assistant is temporarily unavailable. Please try again in a moment."


class ToolError(RuntimeError):
    kind = "tool_error"


@dataclass
class Faults:
    llm_latency_multiplier: float = 1.0
    tool_latency_multiplier: float = 1.0
    error_rate: float = 0.0
    error_kinds: tuple[str, ...] = ("timeout", "provider_error")
    tool_error_rate: float = 0.0
    leak_tfn: bool = False
    corruption: Corruption = field(default_factory=Corruption)


@dataclass(frozen=True, slots=True)
class AppResult:
    trace_id: str
    answer: str
    status: str
    error_class: str | None
    prompt_version: str


def build_messages(
    spec: PromptSpec, variables: dict[str, Any], question: str, tool_outputs: dict[str, Any]
) -> list[ChatMessage]:
    """The app's prompt assembly — also what replay uses to rebuild the exact prompt."""
    system = spec.render(variables)
    user = (
        f"Question: {question}\n\nTool results (JSON):\n```json\n"
        f"{json.dumps(tool_outputs, sort_keys=True, ensure_ascii=False)}\n```"
    )
    return [ChatMessage("system", system), ChatMessage("user", user)]


def messages_hash(messages: list[ChatMessage]) -> str:
    h = hashlib.sha256()
    for m in messages:
        h.update(m.role.encode())
        h.update(b"\0")
        h.update(m.content.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


class AdviserAssistant:
    def __init__(
        self,
        book: ClientBook,
        registry: PromptRegistry,
        tracer: Tracer,
        clock: SimClock,
        model: ChatModel | None = None,
        *,
        app_version: str = APP_VERSION,
        timeout_s: float = 30.0,
    ) -> None:
        self.book = book
        self.registry = registry
        self.tracer = tracer
        self.clock = clock
        self.model: ChatModel = model or DemoFakeModel()
        self.app_version = app_version
        self.timeout_s = timeout_s
        self._specs: dict[str, PromptSpec] = {}

    def spec(self, version: str) -> PromptSpec:
        if version not in self._specs:
            self._specs[version] = self.registry.get(f"{PROMPT_NAME}@{version}")
        return self._specs[version]

    def handle(
        self,
        question: Question,
        *,
        session_id: str,
        request_id: str,
        prompt_version: str,
        rng: random.Random,
        faults: Faults | None = None,
        trace_id: str | None = None,
        adviser_name: str | None = None,
    ) -> AppResult:
        faults = faults or Faults()
        client = self.book.get(question.client_id)
        tools = Tools(self.book, leak_tfn=faults.leak_tfn)
        if isinstance(self.model, DemoFakeModel):
            self.model.corruption = faults.corruption
        spec = self.spec(prompt_version)
        variables = {
            "adviser_name": adviser_name or client.adviser_name,
            "today": self.book.today,
            "client_name": client.name,
            "risk_profile": client.risk_profile,
        }
        answer = ""
        status = "ok"
        error_class: str | None = None
        with self.tracer.trace(
            request_id,
            session_id,
            app_version=self.app_version,
            prompt_name=PROMPT_NAME,
            prompt_version=prompt_version,
            input_text=question.text,
            json_expected=question.type.json_expected,
            trace_id=trace_id,
            attributes={
                "app.intent": question.type.name,
                "app.category": question.type.category,
                "client.id": client.client_id,
                "prompt.hash": spec.content_hash,
                "prompt.variables": variables,
            },
        ) as t:
            with t.span("guardrail", "input_pii") as g:
                self.clock.advance(0.002)
                matches = find_pii(question.text)
                blocked = any(m.kind == "tfn" for m in matches)
                g.set(
                    **{"guardrail.matches": [m.kind for m in matches], "guardrail.blocked": blocked}
                )
            if blocked:
                t.set_attribute("guardrail.blocked", True)
                t.set_output(BLOCKED_TEXT)
                return AppResult(t.trace_id, BLOCKED_TEXT, "ok", None, prompt_version)
            t.set_attribute("guardrail.blocked", False)
            tool_outputs: dict[str, Any] = {}
            try:
                for tool_name in question.type.tools:
                    with t.span("tool", tool_name) as s:
                        s.set(**{"tool.input": {"client_id": client.client_id}})
                        self.clock.advance(
                            rng.lognormvariate(-3.2, 0.4) * faults.tool_latency_multiplier
                        )
                        if faults.tool_error_rate > 0 and rng.random() < faults.tool_error_rate:
                            msg = f"{tool_name}: upstream data service returned 503"
                            raise ToolError(msg)
                        out = tools.call(tool_name, client.client_id)
                        tool_outputs[tool_name] = out
                        s.set(**{"tool.output": out})
                messages = build_messages(spec, variables, question.text, tool_outputs)
                with t.span("llm", "chat") as s:
                    s.set(**{"llm.messages_hash": messages_hash(messages), "llm.temperature": 0.0})
                    if faults.error_rate > 0 and rng.random() < faults.error_rate:
                        kind = rng.choice(faults.error_kinds)
                        self.clock.advance(self.timeout_s if kind == "timeout" else 0.35)
                        s.set_model(self.model.name, prompt_tokens=None, completion_tokens=None)
                        msg = "request timed out" if kind == "timeout" else "HTTP 503 from provider"
                        raise ModelError(msg, kind=kind, status=None if kind == "timeout" else 503)
                    self.clock.advance(
                        rng.lognormvariate(-0.105, 0.35) * faults.llm_latency_multiplier
                    )
                    resp = self.model.chat(
                        messages, max_tokens=int(spec.metadata.get("max_tokens", 400))
                    )
                    s.set_model(
                        resp.model,
                        prompt_tokens=resp.prompt_tokens,
                        completion_tokens=resp.completion_tokens,
                    )
                    s.set(**{"llm.finish_reason": "stop"})
                answer = resp.text
                t.set_output(answer)
            except (ModelError, ToolError) as exc:
                status = "error"
                error_class = str(exc.kind)
                answer = UNAVAILABLE_TEXT
                t.set_status("error", error_class)
                t.set_attribute("error.message", str(exc))
                t.set_output("")
            return AppResult(t.trace_id, answer, status, error_class, prompt_version)
