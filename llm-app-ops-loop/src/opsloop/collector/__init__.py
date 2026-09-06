"""FastAPI collector: trace ingest + query API, feedback, window stats, Prometheus metrics."""

from opsloop.collector.api import create_app

__all__ = ["create_app"]
