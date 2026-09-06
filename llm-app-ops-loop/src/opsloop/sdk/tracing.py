"""The tracing SDK.

::

    tracer = Tracer(exporter=store.ingest)
    with tracer.trace(request_id, session_id, prompt_name="adviser_assistant", prompt_version="v1",
                      input_text=question) as t:
        with t.span("tool", "get_holdings") as s:
            s.set(**{"tool.output": holdings})
        with t.span("llm", "answer") as s:
            s.set_model("northshore-assistant-4b", prompt_tokens=612, completion_tokens=88)
        t.set_output(answer)

What it guarantees:

* cost from ``PriceTable`` — an unknown model marks the cost *missing*, never zero;
* PII redaction of input, output and every string attribute before export, with the counts
  kept as attributes so "the model leaked a TFN" is still observable after redaction;
* head-based sampling that **always keeps errors** and can promote a retained, unsampled trace
  when negative feedback arrives later (``tracer.keep(trace_id)``);
* thread safety, and *never raising into the application*: SDK/exporter failures are counted
  in ``tracer.stats`` (the application's own exceptions are recorded and re-raised).
"""

from __future__ import annotations

import contextvars
import functools
import hashlib
import threading
import time
import uuid
import zlib
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, ParamSpec, TypeVar

from opsloop.pii import redact_text, redact_value
from opsloop.sdk.models import Span, SpanKind, Status, Trace
from opsloop.sdk.pricing import PriceTable

Exporter = Callable[[Trace], None]
P = ParamSpec("P")
R = TypeVar("R")

_current: contextvars.ContextVar[TraceContext | None] = contextvars.ContextVar(
    "opsloop_current_trace", default=None
)


def current_trace() -> TraceContext | None:
    return _current.get()


def _new_id(n: int = 16) -> str:
    return uuid.uuid4().hex[:n]


@dataclass
class TracerStats:
    started: int = 0
    exported: int = 0
    sampled_out: int = 0
    errors_kept: int = 0
    promoted: int = 0
    export_errors: int = 0
    sdk_errors: int = 0
    redactions: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class SpanContext:
    trace: TraceContext
    span_id: str
    parent_id: str | None
    kind: SpanKind
    name: str
    start_ts: float
    attributes: dict[str, Any] = field(default_factory=dict)
    status: Status = "ok"
    error_class: str | None = None
    model: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None

    def set(self, **attributes: Any) -> SpanContext:
        self.attributes.update(attributes)
        return self

    def set_model(
        self, model: str, *, prompt_tokens: int | None, completion_tokens: int | None
    ) -> SpanContext:
        self.model = model
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        return self

    def set_error(self, error_class: str) -> SpanContext:
        self.status = "error"
        self.error_class = error_class
        return self


@dataclass
class TraceContext:
    tracer: Tracer
    trace_id: str
    request_id: str
    session_id: str
    app_version: str
    prompt_name: str
    prompt_version: str
    start_ts: float
    input_text: str = ""
    output_text: str = ""
    json_expected: bool = False
    status: Status = "ok"
    error_class: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    spans: list[Span] = field(default_factory=list)
    _stack: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _n_spans: int = 0

    def _next_span_id(self) -> str:
        # Derived from the trace id so a seeded run produces byte-identical traces.
        self._n_spans += 1
        return hashlib.sha1(f"{self.trace_id}:{self._n_spans}".encode()).hexdigest()[:16]

    def set_output(self, text: str) -> None:
        self.output_text = text

    def set_status(self, status: Status, error_class: str | None = None) -> None:
        self.status = status
        self.error_class = error_class

    def set_attribute(self, key: str, value: Any) -> None:
        self.attributes[key] = value

    @contextmanager
    def span(self, kind: SpanKind, name: str, **attributes: Any) -> Iterator[SpanContext]:
        with self._lock:
            parent = self._stack[-1] if self._stack else None
            ctx = SpanContext(
                self,
                self._next_span_id(),
                parent,
                kind,
                name,
                self.tracer.clock(),
                dict(attributes),
            )
            self._stack.append(ctx.span_id)
        try:
            yield ctx
        except BaseException as exc:
            if ctx.status == "ok":
                ctx.set_error(str(getattr(exc, "kind", None) or type(exc).__name__))
            raise
        finally:
            end = self.tracer.clock()
            self._finish_span(ctx, end)

    def _finish_span(self, ctx: SpanContext, end_ts: float) -> None:
        try:
            cost_usd: float | None = None
            cost_missing = False
            if ctx.kind == "llm":
                cost = self.tracer.prices.cost(
                    ctx.model or "", ctx.prompt_tokens, ctx.completion_tokens
                )
                cost_usd, cost_missing = cost.usd, cost.missing
            span = Span(
                span_id=ctx.span_id,
                trace_id=self.trace_id,
                parent_id=ctx.parent_id,
                kind=ctx.kind,
                name=ctx.name,
                start_ts=ctx.start_ts,
                end_ts=end_ts,
                latency_ms=max(0.0, (end_ts - ctx.start_ts) * 1000.0),
                status=ctx.status,
                error_class=ctx.error_class,
                model=ctx.model,
                prompt_tokens=ctx.prompt_tokens,
                completion_tokens=ctx.completion_tokens,
                cost_usd=cost_usd,
                cost_missing=cost_missing,
                attributes=ctx.attributes,
            )
            with self._lock:
                self.spans.append(span)
                if self._stack and self._stack[-1] == ctx.span_id:
                    self._stack.pop()
        except Exception:  # pragma: no cover - defensive: the SDK never raises into the app
            self.tracer._count_sdk_error()


class Tracer:
    def __init__(
        self,
        exporter: Exporter | None = None,
        *,
        clock: Callable[[], float] = time.time,
        sample_rate: float = 1.0,
        redact: bool = True,
        prices: PriceTable | None = None,
        app_version: str = "0.0.0",
        retain_unsampled: int = 500,
    ) -> None:
        if not 0.0 <= sample_rate <= 1.0:
            msg = f"sample_rate must be in [0, 1], got {sample_rate}"
            raise ValueError(msg)
        self.exporter = exporter
        self.clock = clock
        self.sample_rate = sample_rate
        self.redact = redact
        self.prices = prices or PriceTable()
        self.app_version = app_version
        self.stats = TracerStats()
        self._retain = retain_unsampled
        self._retained: OrderedDict[str, Trace] = OrderedDict()
        self._lock = threading.Lock()

    # ----- public API -----------------------------------------------------------------------

    @contextmanager
    def trace(
        self,
        request_id: str | None = None,
        session_id: str = "",
        *,
        app_version: str | None = None,
        prompt_name: str = "",
        prompt_version: str = "",
        input_text: str = "",
        json_expected: bool = False,
        trace_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Iterator[TraceContext]:
        ctx = TraceContext(
            tracer=self,
            trace_id=trace_id or _new_id(32),
            request_id=request_id or _new_id(),
            session_id=session_id,
            app_version=app_version or self.app_version,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            start_ts=self.clock(),
            input_text=input_text,
            json_expected=json_expected,
            attributes=dict(attributes or {}),
        )
        with self._lock:
            self.stats.started += 1
        token = _current.set(ctx)
        try:
            yield ctx
        except BaseException as exc:
            if ctx.status == "ok":
                ctx.set_status("error", str(getattr(exc, "kind", None) or type(exc).__name__))
            raise
        finally:
            _current.reset(token)
            self._finish(ctx)

    def traced(
        self, kind: SpanKind, name: str | None = None
    ) -> Callable[[Callable[P, R]], Callable[P, R]]:
        """Decorate a plain function: a span in the current trace, a no-op outside one."""

        def decorator(fn: Callable[P, R]) -> Callable[P, R]:
            span_name = name or fn.__name__

            @functools.wraps(fn)
            def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                ctx = _current.get()
                if ctx is None:
                    return fn(*args, **kwargs)
                with ctx.span(kind, span_name):
                    return fn(*args, **kwargs)

            return wrapper

        return decorator

    def keep(self, trace_id: str) -> bool:
        """Promote a retained (sampled-out) trace to the exporter — the negative-feedback path.
        Returns False if the trace was already exported or has aged out of the buffer."""
        with self._lock:
            trace = self._retained.pop(trace_id, None)
        if trace is None:
            return False
        trace.sampled = True
        trace.attributes["sampling.promoted"] = True
        with self._lock:
            self.stats.promoted += 1
        self._export(trace)
        return True

    def retained_ids(self) -> list[str]:
        with self._lock:
            return list(self._retained)

    # ----- internals ------------------------------------------------------------------------

    def _count_sdk_error(self) -> None:
        with self._lock:
            self.stats.sdk_errors += 1

    def _sampled_in(self, trace_id: str) -> bool:
        if self.sample_rate >= 1.0:
            return True
        if self.sample_rate <= 0.0:
            return False
        return (zlib.crc32(trace_id.encode("utf-8")) % 10_000) < int(self.sample_rate * 10_000)

    def _build(self, ctx: TraceContext) -> Trace:
        end_ts = self.clock()
        llm_spans = [s for s in ctx.spans if s.kind == "llm"]
        prompt_tokens = sum(s.prompt_tokens or 0 for s in llm_spans)
        completion_tokens = sum(s.completion_tokens or 0 for s in llm_spans)
        cost_missing = any(s.cost_missing for s in llm_spans)
        cost_usd: float | None
        if cost_missing or not llm_spans:
            cost_usd = None if cost_missing else 0.0
        else:
            cost_usd = float(sum(s.cost_usd or 0.0 for s in llm_spans))
        attributes = dict(ctx.attributes)
        input_text, output_text = ctx.input_text, ctx.output_text
        spans = ctx.spans
        if self.redact:
            input_text, in_counts = redact_text(input_text)
            output_text, out_counts = redact_text(output_text)
            attr_counts: dict[str, int] = {}
            attributes = redact_value(attributes, attr_counts)
            spans = []
            for s in ctx.spans:
                span_counts: dict[str, int] = {}
                new_attrs = redact_value(s.attributes, span_counts)
                for k, v in span_counts.items():
                    attr_counts[k] = attr_counts.get(k, 0) + v
                spans.append(s.model_copy(update={"attributes": new_attrs}))
            attributes["pii.input_redactions"] = sum(in_counts.values())
            attributes["pii.output_redactions"] = sum(out_counts.values())
            attributes["pii.attribute_redactions"] = sum(attr_counts.values())
            kinds = sorted({*in_counts, *out_counts, *attr_counts})
            if kinds:
                attributes["pii.kinds"] = kinds
            with self._lock:
                self.stats.redactions += (
                    attributes["pii.input_redactions"]
                    + attributes["pii.output_redactions"]
                    + attributes["pii.attribute_redactions"]
                )
        return Trace(
            trace_id=ctx.trace_id,
            request_id=ctx.request_id,
            session_id=ctx.session_id,
            app_version=ctx.app_version,
            prompt_name=ctx.prompt_name,
            prompt_version=ctx.prompt_version,
            start_ts=ctx.start_ts,
            end_ts=end_ts,
            latency_ms=max(0.0, (end_ts - ctx.start_ts) * 1000.0),
            status=ctx.status,
            error_class=ctx.error_class,
            input_text=input_text,
            output_text=output_text,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost_usd,
            cost_missing=cost_missing,
            json_expected=ctx.json_expected,
            attributes=attributes,
            spans=spans,
        )

    def _finish(self, ctx: TraceContext) -> None:
        try:
            trace = self._build(ctx)
        except Exception:
            self._count_sdk_error()
            return
        keep = self._sampled_in(trace.trace_id)
        if not keep and trace.status == "error":
            keep = True
            with self._lock:
                self.stats.errors_kept += 1
            trace.attributes["sampling.kept_on_error"] = True
        if keep:
            self._export(trace)
            return
        trace.sampled = False
        with self._lock:
            self.stats.sampled_out += 1
            self._retained[trace.trace_id] = trace
            while len(self._retained) > self._retain:
                self._retained.popitem(last=False)

    def _export(self, trace: Trace) -> None:
        if self.exporter is None:
            return
        try:
            self.exporter(trace)
        except Exception:
            with self._lock:
                self.stats.export_errors += 1
            return
        with self._lock:
            self.stats.exported += 1
