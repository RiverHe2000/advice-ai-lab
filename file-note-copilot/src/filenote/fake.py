"""The scripted backend: a ``ChatModel`` that answers every drafting prompt from the *gold*
note of the meeting it is shown, corrupted with probability ``p`` per item in the ways a real
model goes wrong (dropped items, changed numbers, wrong citations, wrong owners or dates,
invented decisions, deferred advice recorded as decided, small talk leaking into the note,
malformed JSON). It exercises every verifier and evaluator path deterministically; it says
nothing about a real model's quality — that is what the GPU stage measures."""

from __future__ import annotations

import json
import random
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from rapidfuzz import fuzz

from filenote.corpus.generate import Meeting
from filenote.draft.facts import Fact, compliance_facts, compose_from_facts, facts_from_note
from filenote.draft.prompts import (
    json_block_in,
    last_user,
    meeting_id_of,
    segment_ids_in,
    task_of,
)
from filenote.llm import ChatMessage, ChatResponse
from filenote.pii import Pseudonymiser
from filenote.schema import ActionItem, Claim, FileNote, MeetingMeta, Transcript
from filenote.verify.plant import (
    change_number,
    deferred_as_decided,
    invented_decision,
    small_talk_leakage,
    wrong_citation,
    wrong_date,
    wrong_owner,
)
from filenote.verify.text import domain_terms

CORRUPTION_KINDS = (
    "drop",
    "changed_number",
    "wrong_citation",
    "wrong_owner",
    "wrong_date",
    "invented_decision",
    "deferred_as_decided",
    "small_talk_leakage",
    "malformed_json",
    "repair_keep",  # the model insists on an unsupported claim instead of citing or dropping
)
_PLACEHOLDER_RE = re.compile(r"\b(?:CLIENT|ADVISER|PARAPLANNER|SPEAKER)(?:_\d+)?\b")
_ITEM_KINDS = ("drop", "changed_number", "wrong_citation", "wrong_owner", "wrong_date")


@dataclass(frozen=True, slots=True)
class Corruption:
    p: float = 0.0
    seed: int = 0
    kinds: frozenset[str] = frozenset(CORRUPTION_KINDS)

    def on(self, kind: str) -> bool:
        return self.p > 0.0 and kind in self.kinds


class GoldFakeChatModel:
    """Deterministic: the same prompt (task, meeting, window) always gets the same answer."""

    def __init__(
        self, meetings: Mapping[str, Meeting], *, corruption: Corruption | None = None
    ) -> None:
        self._meetings = dict(meetings)
        self.corruption = corruption or Corruption()
        self.calls: list[str] = []

    @property
    def name(self) -> str:
        return f"fake[p={self.corruption.p:g}]"

    def ready(self) -> bool:
        return True

    # ----- protocol ---------------------------------------------------------------------------

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 1800,  # noqa: ARG002 - protocol signature
        temperature: float = 0.0,  # noqa: ARG002
    ) -> ChatResponse:
        msgs = list(messages)
        task = task_of(msgs)
        meeting_id = meeting_id_of(msgs) or "unknown"
        user = last_user(msgs)
        window = self._window_key(user)
        key = f"{task}|{meeting_id}|{window}"
        self.calls.append(key)
        # A retry carries the drafter's "Your previous output was not valid" message; the
        # scripted model answers cleanly then, so the behaviour depends only on the prompt,
        # never on call history (two runs in one process see the same model).
        is_retry = bool(msgs) and msgs[-1].content.startswith("Your previous output")
        rng = random.Random(f"{self.corruption.seed}|{key}")
        meeting = self._meetings.get(meeting_id)
        pseud = self._pseudonymiser(meeting, user)
        if task == "single_shot":
            obj = self._single_shot(meeting, user, rng, pseud)
        elif task == "extract":
            obj = self._extract(meeting, user, rng, pseud)
        elif task == "compose":
            obj = self._compose(meeting, user, rng, pseud)
        elif task == "repair":
            obj = self._repair(meeting, user, rng, pseud)
        else:
            obj = {}
        text = json.dumps(obj, ensure_ascii=False, default=str)
        if (
            not is_retry
            and self.corruption.on("malformed_json")
            and rng.random() < self.corruption.p
        ):
            text = self._malform(text, rng)
        return ChatResponse(
            text=text,
            model=self.name,
            prompt_tokens=sum(len(m.content.split()) for m in msgs),
            completion_tokens=len(text.split()),
        )

    # ----- helpers ----------------------------------------------------------------------------

    @staticmethod
    def _window_key(user: str) -> str:
        found = re.search(r"^#\s*window:\s*(\d+)\s*/\s*(\d+)", user, re.MULTILINE)
        return f"w{found.group(1)}of{found.group(2)}" if found else "all"

    @staticmethod
    def _pseudonymiser(meeting: Meeting | None, user: str) -> Pseudonymiser | None:
        if meeting is None or not _PLACEHOLDER_RE.search(user):
            return None
        return Pseudonymiser(meeting.transcript.attendees)

    @staticmethod
    def _malform(text: str, rng: random.Random) -> str:
        style = rng.choice(["fenced", "trailing_comma", "truncated"])
        if style == "fenced":
            return f"Here is the note you asked for:\n```json\n{text}\n```\nLet me know."
        if style == "trailing_comma":
            return text[:-1] + ", }" if text.endswith("}") else text + ","
        return text[: max(10, int(len(text) * 0.6))]

    def _corrupt_items(self, note: FileNote, meeting: Meeting, rng: random.Random) -> FileNote:
        """Per-item corruption on a note copy (drop / number / citation / owner / date)."""
        c = self.corruption
        has_pp = meeting.seed.paraplanner is not None
        for section, _, item in list(note.iter_claims()):
            if rng.random() >= c.p:
                continue
            kinds = [k for k in _ITEM_KINDS if c.on(k)]
            if not isinstance(item, ActionItem):
                kinds = [k for k in kinds if k not in ("wrong_owner", "wrong_date")]
            if not kinds:
                continue
            kind = rng.choice(kinds)
            if kind == "drop":
                self._remove(note, section, item)
            elif kind == "changed_number":
                changed = change_number(item.label, rng)
                if changed is not None:
                    if isinstance(item, ActionItem):
                        item.description = changed
                    elif isinstance(item, Claim):
                        item.text = changed
            elif kind == "wrong_citation":
                wrong_citation(item, meeting.transcript, rng)
            elif kind == "wrong_owner" and isinstance(item, ActionItem):
                wrong_owner(item, has_pp, rng)
            elif kind == "wrong_date" and isinstance(item, ActionItem):
                wrong_date(item, meeting.seed.date, rng)
        return note

    @staticmethod
    def _remove(note: FileNote, section: str, item: Any) -> None:
        if section == "follow_up":
            note.follow_up = None
        elif section == "vulnerability_indicators":
            note.compliance.vulnerability_indicators = [
                v for v in note.compliance.vulnerability_indicators if v is not item
            ]
        else:
            items: list[Any] = getattr(note, section)
            setattr(note, section, [x for x in items if x is not item])

    def _note_level(self, note: FileNote, meeting: Meeting, rng: random.Random) -> None:
        c = self.corruption
        if c.on("invented_decision") and rng.random() < c.p:
            note.decisions.append(invented_decision(meeting.transcript, rng))
        if c.on("deferred_as_decided"):
            for _ in meeting.deferred:
                if rng.random() < c.p:
                    claim = deferred_as_decided(meeting, rng)
                    if claim is not None and claim.text not in {d.text for d in note.decisions}:
                        note.decisions.append(claim)
        if c.on("small_talk_leakage") and rng.random() < c.p:
            claim = small_talk_leakage(meeting, rng)
            if claim is not None:
                note.topics_discussed.append(claim)

    @staticmethod
    def _pseudonymise_note(note: FileNote, pseud: Pseudonymiser | None) -> FileNote:
        if pseud is None:
            return note
        data = note.model_dump(mode="json")

        def _walk(v: Any) -> Any:
            if isinstance(v, str):
                return pseud.apply(v)
            if isinstance(v, dict):
                return {k: _walk(x) for k, x in v.items()}
            if isinstance(v, list):
                return [_walk(x) for x in v]
            return v

        return FileNote.model_validate(_walk(data))

    @staticmethod
    def _note_json(note: FileNote) -> dict[str, Any]:
        data = note.model_dump(mode="json", exclude={"meeting"})
        for section in (
            "circumstance_changes",
            "goals",
            "topics_discussed",
            "advice_discussed",
            "decisions",
        ):
            data[section] = [{"text": c["text"], "evidence": c["evidence"]} for c in data[section]]
        data["action_items"] = [
            {
                "description": a["description"],
                "owner": a["owner"],
                "due": a["due"],
                "evidence": a["evidence"],
            }
            for a in data["action_items"]
        ]
        data["compliance"]["vulnerability_indicators"] = [
            {"text": c["text"], "evidence": c["evidence"]}
            for c in data["compliance"]["vulnerability_indicators"]
        ]
        if data["follow_up"] is not None:
            data["follow_up"] = {
                "text": data["follow_up"]["text"],
                "evidence": data["follow_up"]["evidence"],
            }
        return data

    # ----- tasks ------------------------------------------------------------------------------

    def _single_shot(
        self, meeting: Meeting | None, user: str, rng: random.Random, pseud: Pseudonymiser | None
    ) -> dict[str, Any]:
        if meeting is None:
            facts = self._generic_facts(user)
            return self._note_json(
                compose_from_facts(facts, _meta_placeholder(), _generic_summary(user))
            )
        note = meeting.gold.model_copy(deep=True)
        self._corrupt_items(note, meeting, rng)
        self._note_level(note, meeting, rng)
        return self._note_json(self._pseudonymise_note(note, pseud))

    def _extract(
        self, meeting: Meeting | None, user: str, rng: random.Random, pseud: Pseudonymiser | None
    ) -> dict[str, Any]:
        window_ids = set(segment_ids_in(user))
        if meeting is None:
            facts = self._generic_facts(user)
            return {"facts": [f.model_dump(mode="json", exclude_none=True) for f in facts]}
        note = meeting.gold.model_copy(deep=True)
        self._corrupt_items(note, meeting, rng)
        note = self._pseudonymise_note(note, pseud)
        facts = facts_from_note(note, only_ids=window_ids | {"unknown"})
        facts = [f for f in facts if any(e in window_ids for e in f.evidence)]
        key = self._window_key(user)
        if key.endswith("of1") or (key != "all" and key.split("of")[0][1:] == key.split("of")[1]):
            facts.extend(compliance_facts(note.compliance))
        if self.corruption.on("small_talk_leakage") and rng.random() < self.corruption.p:
            leak = small_talk_leakage(meeting, rng, within=window_ids)
            if leak is not None:
                facts.append(Fact(category="topic", text=leak.text, evidence=list(leak.evidence)))
        return {"facts": [f.model_dump(mode="json", exclude_none=True) for f in facts]}

    def _compose(
        self, meeting: Meeting | None, user: str, rng: random.Random, pseud: Pseudonymiser | None
    ) -> dict[str, Any]:
        block = json_block_in(user) or {}
        raw_facts = block.get("facts")
        raw: list[Any] = raw_facts if isinstance(raw_facts, list) else []
        facts: list[Fact] = []
        for f in raw:
            try:
                facts.append(Fact.model_validate(f))
            except ValueError:
                continue
        meta = _meta_placeholder()
        summary = _generic_summary(user)
        if meeting is not None:
            summary = meeting.gold.summary
            if pseud is not None:
                summary = pseud.apply(summary)
        note = compose_from_facts(facts, meta, summary)
        if meeting is not None:
            self._note_level(note, meeting, rng)
            note = self._pseudonymise_note(note, pseud) if pseud else note
        return self._note_json(note)

    def _repair(
        self, meeting: Meeting | None, user: str, rng: random.Random, pseud: Pseudonymiser | None
    ) -> dict[str, Any]:
        block = json_block_in(user) or {}
        raw_claims = block.get("claims")
        claims: list[Any] = raw_claims if isinstance(raw_claims, list) else []
        resolutions: list[dict[str, Any]] = []
        gold = meeting.gold if meeting is not None else None
        if gold is not None and pseud is not None:
            gold = self._pseudonymise_note(gold, pseud)
        for c in claims:
            idx = c.get("index")
            match = self._gold_match(gold, str(c.get("section", "")), str(c.get("text", "")))
            if match is not None:
                resolutions.append({"index": idx, "action": "cite", "evidence": match})
            elif self.corruption.on("repair_keep") and rng.random() < self.corruption.p:
                resolutions.append({"index": idx, "action": "keep"})
            else:
                resolutions.append({"index": idx, "action": "drop"})
        return {"resolutions": resolutions}

    @staticmethod
    def _gold_match(gold: FileNote | None, section: str, text: str) -> list[str] | None:
        if gold is None:
            return None
        for s, _, item in gold.iter_claims():
            if s == section and fuzz.ratio(item.label, text) >= 85:
                return list(item.evidence)
        return None

    @staticmethod
    def _generic_facts(user: str) -> list[Fact]:
        """Unknown transcript (pasted text): one topic fact per substantive segment, capped."""
        facts: list[Fact] = []
        for line in user.splitlines():
            m = re.match(r"^(s\d{3,}) \[[^\]]*\] [^:]+: (.*)$", line)
            if not m or not domain_terms(m.group(2)):
                continue
            facts.append(Fact(category="topic", text=m.group(2), evidence=[m.group(1)]))
            if len(facts) >= 3:
                break
        return facts


def _meta_placeholder() -> MeetingMeta:
    import datetime as dt

    return MeetingMeta(date=dt.date(2026, 1, 1), type="annual_review")


def _generic_summary(user: str) -> str:
    ids = segment_ids_in(user)
    return f"Meeting transcript with {len(ids)} segments; topics as listed below."


def transcript_of(meeting: Meeting) -> Transcript:
    return meeting.transcript
