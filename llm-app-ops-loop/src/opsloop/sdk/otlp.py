"""Convert a ``Trace`` to OTLP-style JSON with the OpenTelemetry GenAI semantic-convention
attribute names (``gen_ai.*``). No OpenTelemetry dependency: a real deployment would swap this
module for the OTel SDK + OTLP exporter and keep the same attribute names, so dashboards and
queries written against this output carry over."""

from __future__ import annotations

from typing import Any

from opsloop.sdk.models import Span, Trace

_KIND_NAMES = {"llm": "chat", "tool": "execute_tool", "retrieval": "retrieve", "guardrail": "guard"}


def _attr(key: str, value: Any) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": str(value)}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    if isinstance(value, str):
        return {"key": key, "value": {"stringValue": value}}
    return {"key": key, "value": {"stringValue": repr(value)}}


def _nanos(ts: float) -> str:
    return str(round(ts * 1_000_000_000))


def _span_json(span: Span, root_id: str) -> dict[str, Any]:
    attrs: list[dict[str, Any]] = [_attr("gen_ai.operation.name", _KIND_NAMES[span.kind])]
    if span.kind == "llm":
        attrs.append(_attr("gen_ai.system", "openai_compatible"))
        if span.model:
            attrs.append(_attr("gen_ai.request.model", span.model))
        if span.prompt_tokens is not None:
            attrs.append(_attr("gen_ai.usage.input_tokens", span.prompt_tokens))
        if span.completion_tokens is not None:
            attrs.append(_attr("gen_ai.usage.output_tokens", span.completion_tokens))
        attrs.append(_attr("opsloop.cost.missing", span.cost_missing))
        if span.cost_usd is not None:
            attrs.append(_attr("opsloop.cost.usd", span.cost_usd))
    if span.kind == "tool":
        attrs.append(_attr("gen_ai.tool.name", span.name))
    for k, v in span.attributes.items():
        attrs.append(_attr(f"opsloop.attr.{k}", v))
    status = {"code": "STATUS_CODE_ERROR" if span.status == "error" else "STATUS_CODE_OK"}
    if span.error_class:
        status["message"] = span.error_class
        attrs.append(_attr("error.type", span.error_class))
    return {
        "traceId": span.trace_id,
        "spanId": span.span_id,
        "parentSpanId": span.parent_id or root_id,
        "name": f"{_KIND_NAMES[span.kind]} {span.name}",
        "kind": "SPAN_KIND_CLIENT" if span.kind == "llm" else "SPAN_KIND_INTERNAL",
        "startTimeUnixNano": _nanos(span.start_ts),
        "endTimeUnixNano": _nanos(span.end_ts),
        "attributes": attrs,
        "status": status,
    }


def to_otlp(trace: Trace, *, service_name: str = "northshore-adviser-assistant") -> dict[str, Any]:
    root_id = trace.trace_id[:16]
    root_attrs = [
        _attr("opsloop.request_id", trace.request_id),
        _attr("session.id", trace.session_id),
        _attr("opsloop.prompt.name", trace.prompt_name),
        _attr("opsloop.prompt.version", trace.prompt_version),
        _attr("gen_ai.usage.input_tokens", trace.prompt_tokens),
        _attr("gen_ai.usage.output_tokens", trace.completion_tokens),
        _attr("opsloop.cost.missing", trace.cost_missing),
        _attr("opsloop.json_expected", trace.json_expected),
    ]
    if trace.cost_usd is not None:
        root_attrs.append(_attr("opsloop.cost.usd", trace.cost_usd))
    for k, v in trace.attributes.items():
        root_attrs.append(_attr(f"opsloop.attr.{k}", v))
    root_status = {"code": "STATUS_CODE_ERROR" if trace.status == "error" else "STATUS_CODE_OK"}
    if trace.error_class:
        root_status["message"] = trace.error_class
        root_attrs.append(_attr("error.type", trace.error_class))
    root = {
        "traceId": trace.trace_id,
        "spanId": root_id,
        "name": f"request {trace.prompt_name}",
        "kind": "SPAN_KIND_SERVER",
        "startTimeUnixNano": _nanos(trace.start_ts),
        "endTimeUnixNano": _nanos(trace.end_ts),
        "attributes": root_attrs,
        "status": root_status,
    }
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _attr("service.name", service_name),
                        _attr("service.version", trace.app_version),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "opsloop.sdk", "version": "0.1.0"},
                        "spans": [root, *(_span_json(s, root_id) for s in trace.spans)],
                    }
                ],
            }
        ]
    }
