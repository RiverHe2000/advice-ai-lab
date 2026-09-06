"""Exporters: a JSONL file, HTTP ``POST /v1/traces`` to the collector, and OTLP-style JSONL.
The SQLite exporter is simply ``store.ingest`` (see ``opsloop.quality.pipeline``)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from opsloop.llm import RETRIABLE_STATUS
from opsloop.sdk.models import Trace
from opsloop.sdk.otlp import to_otlp


class JsonlExporter:
    def __init__(self, path: Path, *, otlp: bool = False) -> None:
        self.path = path
        self.otlp = otlp
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, trace: Trace) -> None:
        payload = to_otlp(trace) if self.otlp else trace.model_dump(mode="json")
        line = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        with self._lock, self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


class HttpExporter:
    """``POST {base_url}/v1/traces`` with bounded retries on 408/429/5xx and transport errors.
    A failure raises to the ``Tracer``, which counts it and moves on."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout_s: float = 5.0,
        max_retries: int = 2,
        backoff_s: float = 0.2,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._url = base_url.rstrip("/") + "/v1/traces"
        self._max_retries = max_retries
        self._backoff_s = backoff_s
        self._sleep = sleep
        self._client = client or httpx.Client(timeout=timeout_s)

    def __call__(self, trace: Trace) -> None:
        body = trace.model_dump(mode="json")
        last = ""
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.post(self._url, json=body)
            except httpx.TransportError as exc:
                last = f"transport error: {exc}"
            else:
                if resp.status_code < 300:
                    return
                last = f"HTTP {resp.status_code}: {resp.text[:200]}"
                if resp.status_code not in RETRIABLE_STATUS:
                    raise RuntimeError(last)
            if attempt < self._max_retries:
                self._sleep(self._backoff_s * (2**attempt))
        msg = f"trace export failed after {self._max_retries + 1} attempts: {last}"
        raise RuntimeError(msg)

    def close(self) -> None:
        self._client.close()


class FanOutExporter:
    """Deliver to several exporters; one failing does not stop the others (the last error is
    re-raised so the tracer counts it)."""

    def __init__(self, *exporters: Callable[[Trace], None]) -> None:
        self._exporters = list(exporters)

    def __call__(self, trace: Trace) -> None:
        error: Exception | None = None
        for exporter in self._exporters:
            try:
                exporter(trace)
            except Exception as exc:  # one failure must not block the rest
                error = exc
        if error is not None:
            raise error
