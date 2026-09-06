"""FastAPI backend (drafts, Server-Sent Events progress, edits, approval with diff, feedback,
Prometheus metrics, health / readiness) and the framework-free static front end."""

from filenote.web.app import create_app

__all__ = ["create_app"]
