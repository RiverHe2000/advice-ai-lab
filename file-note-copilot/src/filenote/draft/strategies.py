"""The three strategies. All share one bounded JSON call: prompt → tolerant repair → pydantic
validation → retry with the error, and a *missing* result after the budget is spent."""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from filenote.config import DraftSettings, Settings
from filenote.draft.base import Drafter, DraftError, DraftEvent, DraftResult, ProgressFn
from filenote.draft.facts import Fact, FactList
from filenote.draft.prompts import (
    compose_messages,
    extract_messages,
    repair_messages,
    retry_message,
    single_shot_messages,
)
from filenote.jsonrepair import repair_json
from filenote.llm import ChatMessage, ChatModel, ChatResponse
from filenote.schema import ActionItem, Claim, FileNote, MeetingMeta, Segment, Transcript
from filenote.verify.text import content_words
from filenote.verify.verifier import Verifier

T = TypeVar("T", bound=BaseModel)


class Resolution(BaseModel):
    index: int
    action: str = "keep"
    evidence: list[str] = []


class Resolutions(BaseModel):
    resolutions: list[Resolution] = []


def default_meeting(transcript: Transcript) -> MeetingMeta:
    return MeetingMeta(
        date=transcript.date or dt.date.today(),
        type=transcript.type or "annual_review",
        attendees=list(transcript.attendees),
        duration_minutes=round(transcript.segments[-1].t / 60.0) if transcript.segments else None,
    )


def coerce_note(obj: dict[str, Any], meeting: MeetingMeta) -> FileNote:
    """Lenient shaping of model output into a ``FileNote``: missing sections become empty,
    claims without evidence cite ``unknown`` (the verifier flags them), extras are dropped."""
    data: dict[str, Any] = {"meeting": meeting.model_dump(mode="json")}
    data["summary"] = str(obj.get("summary") or "")
    for section in (
        "circumstance_changes",
        "goals",
        "topics_discussed",
        "advice_discussed",
        "decisions",
    ):
        data[section] = [_claim_dict(c) for c in _as_list(obj.get(section)) if _text_of(c)]
    data["action_items"] = [
        _action_dict(a) for a in _as_list(obj.get("action_items")) if _text_of(a, "description")
    ]
    comp_raw = obj.get("compliance")
    comp: dict[str, Any] = comp_raw if isinstance(comp_raw, dict) else {}
    data["compliance"] = {
        "risk_profile_confirmed": _as_bool(comp.get("risk_profile_confirmed")),
        "risk_profile": str(comp["risk_profile"]) if comp.get("risk_profile") else None,
        "fee_consent_discussed": _as_bool(comp.get("fee_consent_discussed")),
        "conflicts_disclosed": _as_bool(comp.get("conflicts_disclosed")),
        "vulnerability_indicators": [
            _claim_dict(c) for c in _as_list(comp.get("vulnerability_indicators")) if _text_of(c)
        ],
    }
    follow = obj.get("follow_up")
    data["follow_up"] = (
        _claim_dict(follow) if isinstance(follow, dict) and _text_of(follow) else None
    )
    return FileNote.model_validate(data)


def _as_list(value: Any) -> list[Any]:
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in ("true", "false"):
        return value.lower() == "true"
    return None


def _text_of(item: dict[str, Any], key: str = "text") -> str:
    value = item.get(key) or item.get("text") or item.get("description")
    return str(value).strip() if value else ""


def _evidence_of(item: dict[str, Any]) -> list[str]:
    raw = item.get("evidence")
    ids = [str(e) for e in raw if str(e).strip()] if isinstance(raw, list) else []
    return list(dict.fromkeys(ids)) or ["unknown"]


def _claim_dict(item: dict[str, Any]) -> dict[str, Any]:
    return {"text": _text_of(item), "evidence": _evidence_of(item)}


def _action_dict(item: dict[str, Any]) -> dict[str, Any]:
    owner = str(item.get("owner") or "adviser").lower()
    if owner not in ("adviser", "client", "paraplanner"):
        owner = "adviser"
    due = item.get("due")
    try:
        due_date = dt.date.fromisoformat(str(due)[:10]) if due else None
    except ValueError:
        due_date = None
    return {
        "description": _text_of(item, "description"),
        "owner": owner,
        "due": due_date,
        "evidence": _evidence_of(item),
    }


class _Base:
    def __init__(self, model: ChatModel, settings: DraftSettings) -> None:
        self.model = model
        self.settings = settings

    def _emit(self, result: DraftResult, progress: ProgressFn | None, event: DraftEvent) -> None:
        result.events.append(event)
        if progress is not None:
            progress(event)

    def _account(self, result: DraftResult, response: ChatResponse) -> None:
        result.model_calls += 1
        result.prompt_tokens += response.prompt_tokens or 0
        result.completion_tokens += response.completion_tokens or 0

    def _call_json(
        self,
        messages: list[ChatMessage],
        result: DraftResult,
        parse: Callable[[dict[str, Any]], T],
    ) -> T | None:
        """Bounded call: model → repair → parse; retries with the error; ``None`` on failure."""
        convo = list(messages)
        for attempt in range(self.settings.max_parse_retries + 1):
            response = self.model.chat(convo, max_tokens=1800)
            self._account(result, response)
            obj, repaired = repair_json(response.text)
            if obj is None:
                error = "no JSON object found"
            else:
                if repaired:
                    result.json_repairs += 1
                try:
                    return parse(obj)
                except (ValidationError, ValueError, TypeError) as exc:
                    error = str(exc)
            if attempt < self.settings.max_parse_retries:
                convo = [*convo, ChatMessage("assistant", response.text), retry_message(error)]
        result.parse_failures += 1
        return None


class SingleShotDrafter(_Base):
    strategy = "single_shot"

    def draft(
        self,
        transcript: Transcript,
        *,
        meeting: MeetingMeta | None = None,
        progress: ProgressFn | None = None,
    ) -> DraftResult:
        started = time.perf_counter()
        meta = meeting or default_meeting(transcript)
        result = DraftResult(
            note=FileNote(meeting=meta), strategy=self.strategy, model=self.model.name
        )
        self._emit(result, progress, DraftEvent(stage="drafting", message="one-pass draft"))
        note = self._call_json(
            single_shot_messages(transcript, meta), result, lambda o: coerce_note(o, meta)
        )
        if note is None:
            msg = "model produced no parseable note"
            raise DraftError(msg)
        result.note = note
        result.latency_s = time.perf_counter() - started
        self._emit(result, progress, DraftEvent(stage="done", message="draft complete"))
        return result


class ExtractThenComposeDrafter(_Base):
    strategy = "extract_then_compose"

    def _extract(
        self,
        transcript: Transcript,
        meta: MeetingMeta,
        result: DraftResult,
        progress: ProgressFn | None,
    ) -> list[Fact]:
        windows = transcript.windows(self.settings.window_size)
        facts: list[Fact] = []
        for k, window in enumerate(windows, start=1):
            self._emit(
                result,
                progress,
                DraftEvent(stage="extracting", message=f"window {k}/{len(windows)}"),
            )
            parsed = self._call_json(
                extract_messages(transcript, meta, window, k, len(windows)),
                result,
                FactList.model_validate,
            )
            if parsed is None:
                result.failed_windows.append(k)
                continue
            facts.extend(parsed.facts)
        result.facts = facts
        return facts

    def _compose(
        self,
        transcript: Transcript,
        meta: MeetingMeta,
        facts: list[Fact],
        result: DraftResult,
        progress: ProgressFn | None,
    ) -> FileNote:
        self._emit(result, progress, DraftEvent(stage="composing", message=f"{len(facts)} facts"))
        payload = [f.model_dump(mode="json", exclude_none=True) for f in facts]
        note = self._call_json(
            compose_messages(transcript, meta, payload), result, lambda o: coerce_note(o, meta)
        )
        if note is None:
            msg = "model produced no parseable note from the facts"
            raise DraftError(msg)
        return note

    def draft(
        self,
        transcript: Transcript,
        *,
        meeting: MeetingMeta | None = None,
        progress: ProgressFn | None = None,
    ) -> DraftResult:
        started = time.perf_counter()
        meta = meeting or default_meeting(transcript)
        result = DraftResult(
            note=FileNote(meeting=meta), strategy=self.strategy, model=self.model.name
        )
        facts = self._extract(transcript, meta, result, progress)
        result.note = self._compose(transcript, meta, facts, result, progress)
        self._emit_sections(result, progress)
        result.latency_s = time.perf_counter() - started
        self._emit(result, progress, DraftEvent(stage="done", message="draft complete"))
        return result

    def _emit_sections(self, result: DraftResult, progress: ProgressFn | None) -> None:
        for section in (
            "circumstance_changes",
            "goals",
            "topics_discussed",
            "advice_discussed",
            "decisions",
            "action_items",
        ):
            items = result.note.section_items(section)
            self._emit(
                result,
                progress,
                DraftEvent(
                    stage="partial",
                    section=section,
                    message=f"{len(items)} item(s)",
                    payload={"items": [i.model_dump(mode="json") for i in items]},
                ),
            )


class VerifiedDrafter(ExtractThenComposeDrafter):
    strategy = "verified"

    def __init__(self, model: ChatModel, settings: DraftSettings, verifier: Verifier) -> None:
        super().__init__(model, settings)
        self.verifier = verifier

    def _base_draft(
        self,
        transcript: Transcript,
        meta: MeetingMeta,
        result: DraftResult,
        progress: ProgressFn | None,
    ) -> FileNote:
        """The draft the verifier then checks: extract-then-compose by default."""
        facts = self._extract(transcript, meta, result, progress)
        return self._compose(transcript, meta, facts, result, progress)

    def _candidates(self, transcript: Transcript, items: list[Claim | ActionItem]) -> list[Segment]:
        by_id = transcript.by_id()
        chosen: dict[str, Segment] = {}
        for item in items:
            for e in item.evidence:
                if e in by_id:
                    chosen[e] = by_id[e]
            words = content_words(item.label)
            scored = sorted(
                transcript.segments,
                key=lambda s: -len(words & content_words(s.text)),
            )
            for s in scored[: self.settings.candidate_segments]:
                chosen[s.id] = s
        return [by_id[i] for i in sorted(chosen, key=lambda x: transcript.segment_ids.index(x))]

    def _repair(
        self,
        transcript: Transcript,
        meta: MeetingMeta,
        result: DraftResult,
        progress: ProgressFn | None,
    ) -> None:
        note = result.note
        flagged = [(s, i, it) for s, i, it in note.iter_claims() if it.unsupported]
        if not flagged:
            return
        self._emit(
            result,
            progress,
            DraftEvent(stage="repairing", message=f"{len(flagged)} unsupported claim(s)"),
        )
        claims = [
            {
                "index": n,
                "section": s,
                "text": it.label,
                "evidence": it.evidence,
                "reasons": it.reasons,
            }
            for n, (s, _, it) in enumerate(flagged)
        ]
        items: list[Claim | ActionItem] = [it for _, _, it in flagged]  # type: ignore[misc]
        parsed = self._call_json(
            repair_messages(transcript, meta, claims, self._candidates(transcript, items)),
            result,
            Resolutions.model_validate,
        )
        if parsed is None:
            return
        drop: set[int] = set()
        valid = set(transcript.segment_ids)
        for r in parsed.resolutions:
            if not 0 <= r.index < len(flagged):
                continue
            section, idx, item = flagged[r.index]
            if r.action == "drop":
                drop.add(r.index)
                result.repair_dropped.append(f"{section}: {item.label}")
            elif r.action == "cite" and r.evidence:
                cited = [e for e in r.evidence if e in valid]
                if cited:
                    item.evidence = cited
                    result.repair_cited += 1
        for n in sorted(drop, reverse=True):
            section, idx, _ = flagged[n]
            if section == "follow_up":
                note.follow_up = None
            elif section == "vulnerability_indicators":
                del note.compliance.vulnerability_indicators[idx]
            else:
                getattr(note, section).pop(idx)

    def draft(
        self,
        transcript: Transcript,
        *,
        meeting: MeetingMeta | None = None,
        progress: ProgressFn | None = None,
    ) -> DraftResult:
        started = time.perf_counter()
        meta = meeting or default_meeting(transcript)
        result = DraftResult(
            note=FileNote(meeting=meta), strategy=self.strategy, model=self.model.name
        )
        result.note = self._base_draft(transcript, meta, result, progress)
        self._emit(result, progress, DraftEvent(stage="verifying", message="checking every claim"))
        report = self.verifier.verify(result.note, transcript)
        result.note = self.verifier.apply(result.note, report)
        for _ in range(self.settings.repair_passes):
            if result.note.unsupported_count() == 0:
                break
            self._repair(transcript, meta, result, progress)
            report = self.verifier.verify(result.note, transcript)
            result.note = self.verifier.apply(result.note, report)
        result.verification = report
        self._emit_sections(result, progress)
        result.latency_s = time.perf_counter() - started
        self._emit(
            result,
            progress,
            DraftEvent(
                stage="done",
                message=f"{result.note.unsupported_count()} unsupported claim(s) remain",
                payload=report.summary(),
            ),
        )
        return result


class VerifiedSingleShotDrafter(VerifiedDrafter):
    """The same verify-and-repair loop on top of the one-pass draft, so the effect of
    verification can be measured separately from the effect of the two-pass base."""

    strategy = "verified_single_shot"

    def _base_draft(
        self,
        transcript: Transcript,
        meta: MeetingMeta,
        result: DraftResult,
        progress: ProgressFn | None,
    ) -> FileNote:
        self._emit(result, progress, DraftEvent(stage="drafting", message="one-pass draft"))
        note = self._call_json(
            single_shot_messages(transcript, meta), result, lambda o: coerce_note(o, meta)
        )
        if note is None:
            msg = "model produced no parseable note"
            raise DraftError(msg)
        return note


def build_drafter(strategy: str, model: ChatModel, settings: Settings) -> Drafter:
    if strategy == "single_shot":
        return SingleShotDrafter(model, settings.draft)
    if strategy == "extract_then_compose":
        return ExtractThenComposeDrafter(model, settings.draft)
    if strategy == "verified":
        return VerifiedDrafter(model, settings.draft, Verifier(settings.verifier))
    if strategy == "verified_single_shot":
        return VerifiedSingleShotDrafter(model, settings.draft, Verifier(settings.verifier))
    msg = f"unknown strategy {strategy!r}"
    raise ValueError(msg)
