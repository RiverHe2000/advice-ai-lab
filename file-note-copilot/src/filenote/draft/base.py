"""Shared types for the drafting strategies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from filenote.draft.facts import Fact
from filenote.schema import FileNote, MeetingMeta, Transcript
from filenote.verify.verifier import VerificationReport


class DraftError(RuntimeError):
    """The model never produced a parseable note within the retry budget."""


class DraftEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str
    message: str = ""
    section: str | None = None
    payload: dict[str, Any] | None = None


ProgressFn = Callable[[DraftEvent], None]


class DraftResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: FileNote
    strategy: str
    model: str
    events: list[DraftEvent] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)
    verification: VerificationReport | None = None
    model_calls: int = 0
    json_repairs: int = 0
    parse_failures: int = 0
    failed_windows: list[int] = Field(default_factory=list)
    repair_cited: int = 0
    repair_dropped: list[str] = Field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_s: float = 0.0


class Drafter(Protocol):
    @property
    def strategy(self) -> str: ...

    def draft(
        self,
        transcript: Transcript,
        *,
        meeting: MeetingMeta | None = None,
        progress: ProgressFn | None = None,
    ) -> DraftResult: ...
