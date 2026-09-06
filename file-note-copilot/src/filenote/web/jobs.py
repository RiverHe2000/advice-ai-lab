"""Background drafting jobs with an append-only event log per draft, so a Server-Sent Events
stream can start late, resume after a reconnect (``Last-Event-ID``) and always end on
``done`` or ``error``."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

TERMINAL = frozenset({"done", "error"})


@dataclass
class Event:
    id: int
    event: str
    data: dict[str, Any]

    def render(self) -> str:
        import json

        payload = json.dumps(self.data, ensure_ascii=False, default=str)
        return f"id: {self.id}\nevent: {self.event}\ndata: {payload}\n\n"


@dataclass
class Job:
    draft_id: str
    events: list[Event] = field(default_factory=list)
    cond: threading.Condition = field(default_factory=threading.Condition)
    finished: bool = False

    def push(self, event: str, data: dict[str, Any] | None = None) -> Event:
        with self.cond:
            ev = Event(len(self.events) + 1, event, data or {})
            self.events.append(ev)
            if event in TERMINAL:
                self.finished = True
            self.cond.notify_all()
            return ev

    def stream(self, *, after: int = 0, heartbeat_s: float = 5.0) -> Iterator[str]:
        """Yields SSE frames from event ``after + 1``; a comment heartbeat while idle."""
        cursor = after
        while True:
            with self.cond:
                pending = self.events[cursor:]
                if not pending and not self.finished:
                    self.cond.wait(timeout=heartbeat_s)
                    pending = self.events[cursor:]
            if not pending:
                if self.finished:
                    return
                yield ": ping\n\n"
                continue
            for ev in pending:
                cursor = ev.id
                yield ev.render()
                if ev.event in TERMINAL:
                    return


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def create(self, draft_id: str) -> Job:
        with self._lock:
            job = Job(draft_id)
            self._jobs[draft_id] = job
            return job

    def get(self, draft_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(draft_id)

    def start(self, job: Job, target: Callable[[Job], None]) -> threading.Thread:
        thread = threading.Thread(
            target=target, args=(job,), name=f"draft-{job.draft_id}", daemon=True
        )
        thread.start()
        return thread
