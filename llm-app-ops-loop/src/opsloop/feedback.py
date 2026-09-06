"""User feedback against a trace: explicit (thumbs, comment, which part was wrong) and implicit
(regenerate clicked; normalised edit distance between the answer and the user's edited version).
A negative signal marks the trace, feeds the sampling policy and the negative-feedback SLO, and
promotes a sampled-out trace in the SDK buffer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field
from rapidfuzz.distance import Levenshtein

from opsloop.sdk.tracing import Tracer
from opsloop.store import TraceStore

WrongPart = Literal["numbers", "answer", "tone", "refusal", "format", "other"]


class Feedback(BaseModel):
    trace_id: str
    ts: float
    thumbs: Literal["up", "down"] | None = None
    comment: str | None = None
    wrong_part: WrongPart | None = None
    regenerated: bool = False
    edit_ratio: float | None = Field(default=None, ge=0.0, le=1.0)
    negative: bool = False
    reasons: list[str] = Field(default_factory=list)


def edit_ratio(original: str, edited: str) -> float:
    """Levenshtein distance normalised by the longer length (0 = unchanged, 1 = rewritten)."""
    if not original and not edited:
        return 0.0
    return float(Levenshtein.normalized_distance(original, edited))


def build_feedback(
    trace_id: str,
    *,
    ts: float,
    thumbs: Literal["up", "down"] | None = None,
    comment: str | None = None,
    wrong_part: WrongPart | None = None,
    regenerated: bool = False,
    original_text: str | None = None,
    edited_text: str | None = None,
    edit_threshold: float = 0.3,
) -> Feedback:
    ratio: float | None = None
    if edited_text is not None and original_text is not None:
        ratio = edit_ratio(original_text, edited_text)
    reasons: list[str] = []
    if thumbs == "down":
        reasons.append("thumbs_down")
    if regenerated:
        reasons.append("regenerated")
    if ratio is not None and ratio >= edit_threshold:
        reasons.append(f"edited({ratio:.2f})")
    if wrong_part is not None and "thumbs_down" not in reasons:
        reasons.append(f"wrong_part={wrong_part}")
    return Feedback(
        trace_id=trace_id,
        ts=ts,
        thumbs=thumbs,
        comment=comment,
        wrong_part=wrong_part,
        regenerated=regenerated,
        edit_ratio=ratio,
        negative=bool(reasons),
        reasons=reasons,
    )


def add_feedback(store: TraceStore, feedback: Feedback, *, tracer: Tracer | None = None) -> int:
    """Persist feedback. If the trace was sampled out and is still in the tracer's retention
    buffer, negative feedback promotes it first so the row exists."""
    if tracer is not None and feedback.negative:
        tracer.keep(feedback.trace_id)
    payload: dict[str, Any] = feedback.model_dump(
        mode="json", exclude={"trace_id", "ts", "negative"}
    )
    return store.add_feedback(feedback.trace_id, feedback.ts, feedback.negative, payload)
