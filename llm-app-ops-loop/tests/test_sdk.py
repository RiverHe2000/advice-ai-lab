"""Tracing SDK: spans, cost with missing-cost semantics, sampling that keeps errors and promotes
on negative feedback, redaction with counts, never raising, thread safety, OTLP conversion,
exporters."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from opsloop.llm import ModelError
from opsloop.sdk.exporters import FanOutExporter, HttpExporter, JsonlExporter
from opsloop.sdk.models import Trace
from opsloop.sdk.otlp import to_otlp
from opsloop.sdk.pricing import PriceTable
from opsloop.sdk.tracing import Tracer, current_trace
from opsloop.timeutil import SimClock


class Sink:
    def __init__(self, fail: bool = False) -> None:
        self.traces: list[Trace] = []
        self.fail = fail

    def __call__(self, trace: Trace) -> None:
        if self.fail:
            msg = "exporter down"
            raise RuntimeError(msg)
        self.traces.append(trace)


def test_trace_records_spans_latency_tokens_and_cost() -> None:
    clock = SimClock(1000.0)
    sink = Sink()
    tracer = Tracer(sink, clock=clock.now, app_version="9.9")
    with tracer.trace("r1", "s1", prompt_name="p", prompt_version="v1", input_text="hi") as t:
        with t.span("tool", "get_holdings") as s:
            clock.advance(0.05)
            s.set(**{"tool.output": {"balance": 10.0}})
        with t.span("llm", "chat") as s:
            clock.advance(0.9)
            s.set_model("northshore-assistant-4b", prompt_tokens=1000, completion_tokens=500)
        t.set_output("answer")
    trace = sink.traces[0]
    assert trace.request_id == "r1" and trace.app_version == "9.9" and trace.status == "ok"
    assert trace.latency_ms == pytest.approx(950.0)
    assert [s.kind for s in trace.spans] == ["tool", "llm"]
    assert trace.spans[0].latency_ms == pytest.approx(50.0)
    assert trace.prompt_tokens == 1000 and trace.completion_tokens == 500
    assert trace.cost_usd == pytest.approx((1000 * 0.40 + 500 * 1.60) / 1e6)
    assert not trace.cost_missing
    assert trace.tool_outputs() == {"get_holdings": {"balance": 10.0}}
    assert tracer.stats.exported == 1 and tracer.stats.started == 1


def test_unknown_model_marks_cost_missing_not_zero() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    with tracer.trace("r", "s") as t, t.span("llm", "chat") as s:
        s.set_model("mystery-model", prompt_tokens=10, completion_tokens=10)
    trace = sink.traces[0]
    assert trace.cost_missing and trace.cost_usd is None
    assert trace.spans[0].cost_missing and trace.spans[0].cost_usd is None


def test_no_llm_span_means_zero_cost_not_missing() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    with tracer.trace("r", "s") as t, t.span("guardrail", "input"):
        pass
    assert sink.traces[0].cost_usd == 0.0 and not sink.traces[0].cost_missing


def test_nested_spans_have_parent_ids_and_deterministic_ids() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    with (
        tracer.trace("r", "s", trace_id="fixed") as t,
        t.span("tool", "outer"),
        t.span("retrieval", "inner"),
    ):
        pass
    outer, inner = sink.traces[0].spans[1], sink.traces[0].spans[0]
    assert outer.name == "outer" and inner.parent_id == outer.span_id and outer.parent_id is None
    sink2 = Sink()
    with (
        Tracer(sink2).trace("r", "s", trace_id="fixed") as t,
        t.span("tool", "outer"),
        t.span("retrieval", "inner"),
    ):
        pass
    assert [s.span_id for s in sink.traces[0].spans] == [s.span_id for s in sink2.traces[0].spans]


def test_application_exception_is_recorded_and_reraised() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    with pytest.raises(ModelError), tracer.trace("r", "s") as t, t.span("llm", "chat"):
        raise ModelError("boom", kind="timeout")
    trace = sink.traces[0]
    assert trace.status == "error" and trace.error_class == "timeout"
    assert trace.spans[0].status == "error" and trace.spans[0].error_class == "timeout"


def test_plain_exception_uses_class_name() -> None:
    sink = Sink()
    with pytest.raises(ValueError), Tracer(sink).trace("r", "s"):
        raise ValueError("bad")
    assert sink.traces[0].error_class == "ValueError"


def test_decorator_creates_span_inside_trace_and_is_noop_outside() -> None:
    sink = Sink()
    tracer = Tracer(sink)

    inside: list[bool] = []

    @tracer.traced("tool", "fee_schedule")
    def fees(x: int) -> int:
        inside.append(current_trace() is not None)
        return x * 2

    @tracer.traced("tool")
    def named_by_function() -> int:
        return 1

    assert fees(2) == 4  # outside a trace: plain call
    with tracer.trace("r", "s"):
        assert fees(3) == 6
        assert named_by_function() == 1
    assert [s.name for s in sink.traces[0].spans] == ["fee_schedule", "named_by_function"]
    assert inside == [False, True] and current_trace() is None


def test_head_sampling_keeps_errors_and_promotes_on_feedback() -> None:
    sink = Sink()
    tracer = Tracer(sink, sample_rate=0.0, retain_unsampled=2)
    with tracer.trace("r1", "s", trace_id="a"):
        pass
    with pytest.raises(RuntimeError), tracer.trace("r2", "s", trace_id="b"):
        raise RuntimeError("x")
    assert [t.trace_id for t in sink.traces] == ["b"]
    assert sink.traces[0].attributes["sampling.kept_on_error"] is True
    assert tracer.stats.sampled_out == 1 and tracer.stats.errors_kept == 1
    assert tracer.retained_ids() == ["a"]
    assert tracer.keep("a") is True
    assert (
        sink.traces[-1].trace_id == "a" and sink.traces[-1].attributes["sampling.promoted"] is True
    )
    assert tracer.keep("a") is False and tracer.stats.promoted == 1
    for i in range(4):  # the retention buffer is bounded
        with tracer.trace(f"r{i}", "s", trace_id=f"x{i}"):
            pass
    assert len(tracer.retained_ids()) == 2


def test_sampling_rate_is_deterministic_per_trace_id() -> None:
    a, b = Sink(), Sink()
    for sink in (a, b):
        tracer = Tracer(sink, sample_rate=0.5)
        for i in range(50):
            with tracer.trace("r", "s", trace_id=f"trace-{i}"):
                pass
    assert [t.trace_id for t in a.traces] == [t.trace_id for t in b.traces]
    assert 5 < len(a.traces) < 45


def test_invalid_sample_rate_rejected() -> None:
    with pytest.raises(ValueError):
        Tracer(None, sample_rate=1.5)


def test_redaction_of_text_and_attributes_with_counts() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    tfn = "123 456 782"
    with tracer.trace("r", "s", input_text=f"Client TFN {tfn}") as t:
        with t.span("tool", "get_holdings") as s:
            s.set(**{"tool.output": {"tfn": tfn, "email": "a.b@example.com", "nested": [tfn]}})
        t.set_output(f"TFN on file: {tfn}, call 0412 345 678")
    trace = sink.traces[0]
    assert "[TFN]" in trace.input_text and tfn not in trace.input_text
    assert "[TFN]" in trace.output_text and "[PHONE]" in trace.output_text
    assert trace.spans[0].attributes["tool.output"]["tfn"] == "[TFN]"
    assert trace.spans[0].attributes["tool.output"]["email"] == "[EMAIL]"
    assert trace.attributes["pii.input_redactions"] == 1
    assert trace.attributes["pii.output_redactions"] == 2
    assert trace.attributes["pii.attribute_redactions"] == 3
    assert trace.attributes["pii.kinds"] == ["email", "phone", "tfn"]
    assert tracer.stats.redactions == 6


def test_redaction_can_be_disabled() -> None:
    sink = Sink()
    with Tracer(sink, redact=False).trace("r", "s", input_text="TFN 123 456 782"):
        pass
    assert "123 456 782" in sink.traces[0].input_text


def test_exporter_failure_never_raises_into_the_application() -> None:
    tracer = Tracer(Sink(fail=True))
    with tracer.trace("r", "s"):
        pass
    assert tracer.stats.export_errors == 1 and tracer.stats.exported == 0


def test_no_exporter_is_fine() -> None:
    tracer = Tracer(None)
    with tracer.trace("r", "s"):
        pass
    assert tracer.stats.exported == 0


def test_thread_safety_under_concurrent_traces() -> None:
    sink = Sink()
    tracer = Tracer(sink)
    lock = threading.Lock()
    seen: list[str] = []

    def work(i: int) -> None:
        with tracer.trace(f"r{i}", "s", trace_id=f"t{i}") as t:
            with t.span("tool", "x"):
                pass
            with lock:
                seen.append(t.trace_id)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(sink.traces) == 20 and len({t.trace_id for t in sink.traces}) == 20
    assert all(len(t.spans) == 1 for t in sink.traces)


def test_otlp_conversion_uses_gen_ai_attribute_names(make_trace) -> None:  # type: ignore[no-untyped-def]
    trace = make_trace("abc", status="error", error_class="timeout")
    otlp = to_otlp(trace)
    spans = otlp["resourceSpans"][0]["scopeSpans"][0]["spans"]
    assert len(spans) == 3 and spans[0]["kind"] == "SPAN_KIND_SERVER"
    assert spans[0]["status"] == {"code": "STATUS_CODE_ERROR", "message": "timeout"}
    llm = next(s for s in spans if s["name"] == "chat chat")
    keys = {a["key"]: a["value"] for a in llm["attributes"]}
    assert keys["gen_ai.request.model"] == {"stringValue": "northshore-assistant-4b"}
    assert keys["gen_ai.usage.input_tokens"] == {"intValue": "500"}
    assert keys["gen_ai.operation.name"] == {"stringValue": "chat"}
    assert keys["error.type"] == {"stringValue": "timeout"}
    tool = next(s for s in spans if s["name"].startswith("execute_tool"))
    tool_keys = {a["key"]: a["value"] for a in tool["attributes"]}
    assert tool_keys["gen_ai.tool.name"] == {"stringValue": "get_holdings"}
    assert "stringValue" in tool_keys["opsloop.attr.tool.output"]
    resource = {a["key"]: a["value"] for a in otlp["resourceSpans"][0]["resource"]["attributes"]}
    assert resource["service.version"] == {"stringValue": "1.4.0"}
    assert spans[1]["parentSpanId"] == spans[0]["spanId"]
    assert int(spans[0]["startTimeUnixNano"]) == round(trace.start_ts * 1e9)


def test_otlp_attribute_value_types(make_trace) -> None:  # type: ignore[no-untyped-def]
    trace = make_trace(
        "v", attributes={"flag": True, "n": 3, "x": 1.5, "s": "str", "obj": {"a": 1}}
    )
    root = to_otlp(trace)["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    values = {a["key"]: a["value"] for a in root["attributes"]}
    assert values["opsloop.attr.flag"] == {"boolValue": True}
    assert values["opsloop.attr.n"] == {"intValue": "3"}
    assert values["opsloop.attr.x"] == {"doubleValue": 1.5}
    assert values["opsloop.attr.obj"] == {"stringValue": "{'a': 1}"}


def test_jsonl_exporter_plain_and_otlp(tmp_path: Path, make_trace) -> None:  # type: ignore[no-untyped-def]
    plain = JsonlExporter(tmp_path / "out" / "traces.jsonl")
    otlp = JsonlExporter(tmp_path / "otlp.jsonl", otlp=True)
    trace = make_trace("j1")
    plain(trace)
    otlp(trace)
    line = json.loads((tmp_path / "out" / "traces.jsonl").read_text(encoding="utf-8"))
    assert line["trace_id"] == "j1"
    assert "resourceSpans" in json.loads((tmp_path / "otlp.jsonl").read_text(encoding="utf-8"))


def _http_exporter(
    handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any
) -> HttpExporter:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpExporter("http://collector", client=client, sleep=lambda _: None, **kwargs)


def test_http_exporter_posts_and_retries(make_trace) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if len(calls) < 2:
            return httpx.Response(503, text="busy")
        body = json.loads(request.content)
        assert body["trace_id"] == "h1"
        return httpx.Response(202, json={"accepted": 1})

    _http_exporter(handler, max_retries=2)(make_trace("h1"))
    assert calls == ["/v1/traces", "/v1/traces"]


def test_http_exporter_gives_up_and_rejects_non_retriable(make_trace) -> None:  # type: ignore[no-untyped-def]
    def always_503(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    with pytest.raises(RuntimeError, match="after 2 attempts"):
        _http_exporter(always_503, max_retries=1)(make_trace("h2"))

    def bad_request(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="nope")

    with pytest.raises(RuntimeError, match="HTTP 400"):
        _http_exporter(bad_request)(make_trace("h3"))

    def transport_error(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    exporter = _http_exporter(transport_error, max_retries=0)
    with pytest.raises(RuntimeError, match="transport error"):
        exporter(make_trace("h4"))
    exporter.close()


def test_fanout_delivers_to_all_and_reraises_last_error(make_trace) -> None:  # type: ignore[no-untyped-def]
    good, bad = Sink(), Sink(fail=True)
    fan = FanOutExporter(bad, good)
    with pytest.raises(RuntimeError):
        fan(make_trace("f"))
    assert len(good.traces) == 1


def test_price_table_normalisation_and_yaml(tmp_path: Path) -> None:
    table = PriceTable()
    assert table.known("openai[gpt-4o-mini]") and table.known("hf[D:/models/Mystery-7B]") is False
    assert table.cost("GPT-4o-mini", 1_000_000, 0).usd == pytest.approx(0.15)
    assert table.cost("gpt-4o-mini", None, 10).missing
    assert table.cost("nope", 1, 1).value_or_zero == 0.0
    (tmp_path / "prices.yaml").write_text(
        "my-model: {input_per_million: 1.0, output_per_million: 2.0}\n", encoding="utf-8"
    )
    custom = PriceTable.from_yaml(tmp_path / "prices.yaml")
    assert custom.models() == ["my-model"] and custom.cost(
        "my-model", 1000, 1000
    ).usd == pytest.approx(0.003)
