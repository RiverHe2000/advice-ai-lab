"""The trace data model shared by the SDK, the store, the collector and every consumer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SpanKind = Literal["llm", "tool", "retrieval", "guardrail"]
Status = Literal["ok", "error"]


class Span(BaseModel):
    span_id: str
    trace_id: str
    parent_id: str | None = None
    kind: SpanKind
    name: str
    start_ts: float
    end_ts: float
    latency_ms: float
    status: Status = "ok"
    error_class: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    cost_usd: float | None = None
    cost_missing: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)


class Trace(BaseModel):
    trace_id: str
    request_id: str
    session_id: str
    app_version: str
    prompt_name: str
    prompt_version: str
    start_ts: float
    end_ts: float
    latency_ms: float
    status: Status = "ok"
    error_class: str | None = None
    input_text: str = ""
    output_text: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float | None = None
    cost_missing: bool = False
    json_expected: bool = False
    sampled: bool = True
    attributes: dict[str, Any] = Field(default_factory=dict)
    spans: list[Span] = Field(default_factory=list)

    def spans_of(self, kind: SpanKind) -> list[Span]:
        return [s for s in self.spans if s.kind == kind]

    def tool_outputs(self) -> dict[str, Any]:
        """Recorded tool outputs keyed by tool name (what replay stubs and grounding checks)."""
        return {s.name: s.attributes.get("tool.output") for s in self.spans if s.kind == "tool"}
