"""Prometheus metrics behind a tiny sink protocol so the workflow does not depend on the
exporter (a ``NullMetrics`` is used in tests and the CLI)."""

from __future__ import annotations

from typing import Protocol

from prometheus_client import CollectorRegistry, Counter, Histogram, generate_latest


class MetricsSink(Protocol):
    def document_classified(self, doc_type: str) -> None: ...

    def document_routed(self, route: str) -> None: ...

    def violation(self, code: str) -> None: ...

    def extraction_latency(self, seconds: float) -> None: ...


class NullMetrics:
    def document_classified(self, doc_type: str) -> None:
        del doc_type

    def document_routed(self, route: str) -> None:
        del route

    def violation(self, code: str) -> None:
        del code

    def extraction_latency(self, seconds: float) -> None:
        del seconds


class PrometheusMetrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        self._documents = Counter(
            "advicedoc_documents_total",
            "Documents classified",
            ["doc_type"],
            registry=self.registry,
        )
        self._routed = Counter(
            "advicedoc_routed_total",
            "Documents routed (review or auto)",
            ["route"],
            registry=self.registry,
        )
        self._violations = Counter(
            "advicedoc_validator_violations_total",
            "Validator violations",
            ["code"],
            registry=self.registry,
        )
        self._latency = Histogram(
            "advicedoc_extraction_latency_seconds",
            "Extraction latency per document",
            registry=self.registry,
            buckets=(0.01, 0.05, 0.1, 0.5, 1, 2, 5, 10, 30, 60),
        )

    def document_classified(self, doc_type: str) -> None:
        self._documents.labels(doc_type=doc_type).inc()

    def document_routed(self, route: str) -> None:
        self._routed.labels(route=route).inc()

    def violation(self, code: str) -> None:
        self._violations.labels(code=code).inc()

    def extraction_latency(self, seconds: float) -> None:
        self._latency.observe(seconds)

    def render(self) -> bytes:
        return generate_latest(self.registry)
