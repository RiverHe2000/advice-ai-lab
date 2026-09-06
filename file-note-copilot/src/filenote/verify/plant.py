"""Hallucinations of known kinds, planted into a gold note. Used twice: by the scripted model
to corrupt its gold-derived output, and by the verifier self-evaluation to measure detection
and false-alarm rates against a known truth."""

from __future__ import annotations

import datetime as dt
import random
import re
from typing import Literal

from filenote.corpus.generate import Meeting
from filenote.numbers import format_amount
from filenote.schema import ActionItem, Claim, Evidenced, FileNote, Owner, Transcript

PlantKind = Literal[
    "invented_decision",
    "changed_number",
    "wrong_owner",
    "wrong_date",
    "deferred_as_decided",
    "wrong_citation",
    "small_talk_leakage",
]
PLANT_KINDS: tuple[PlantKind, ...] = (
    "invented_decision",
    "changed_number",
    "wrong_owner",
    "wrong_date",
    "deferred_as_decided",
    "wrong_citation",
    "small_talk_leakage",
)
INVENTED_DECISIONS = [
    "Client agreed to consolidate all super accounts into Northshore Super.",
    "Client agreed to increase income protection cover to $10,000 per month.",
    "Client agreed to establish a self-managed super fund next financial year.",
    "Client agreed to commence a transition-to-retirement pension at $40,000 per year.",
    "Client agreed to nominate the estate as beneficiary of the Northshore Pension.",
]
_NUMBER_SPAN_RE = re.compile(r"\$\d[\d,]*(?:\.\d+)?|\d[\d,]*(?:\.\d+)?%|\b\d[\d,]*(?:\.\d+)?\b")


def change_number(text: str, rng: random.Random) -> str | None:
    """Alter one figure in ``text`` (money first); ``None`` if the text has no figure."""
    spans = list(_NUMBER_SPAN_RE.finditer(text))
    if not spans:
        return None
    money = [m for m in spans if m.group().startswith("$")]
    m = rng.choice(money or spans)
    raw = m.group()
    factor = rng.choice([1.5, 0.5, 1.25, 2.0])
    if raw.startswith("$"):
        value = float(raw[1:].replace(",", "")) * factor
        step = 1_000 if value >= 10_000 else 100
        new = format_amount(max(step, round(value / step) * step))
    elif raw.endswith("%"):
        new = f"{round(float(raw[:-1]) * factor, 1):g}%"
    else:
        value = float(raw.replace(",", ""))
        new = f"{round(value * factor) or 1}"
    return text[: m.start()] + new + text[m.end() :]


def wrong_citation(item: Evidenced, transcript: Transcript, rng: random.Random) -> None:
    others = [s.id for s in transcript.segments if s.id not in item.evidence]
    if others:
        item.evidence = [rng.choice(others)]


def wrong_owner(item: ActionItem, has_paraplanner: bool, rng: random.Random) -> None:
    owners: list[Owner] = (
        ["adviser", "client", "paraplanner"] if has_paraplanner else ["adviser", "client"]
    )
    choices = [o for o in owners if o != item.owner]
    item.owner = rng.choice(choices)


def wrong_date(item: ActionItem, meeting_date: dt.date, rng: random.Random) -> None:
    base = item.due or meeting_date + dt.timedelta(days=14)
    item.due = base + dt.timedelta(days=rng.choice([-21, -14, 14, 21, 35]))


def invented_decision(transcript: Transcript, rng: random.Random) -> Claim:
    text = rng.choice(INVENTED_DECISIONS)
    sid = rng.choice(transcript.segment_ids)
    return Claim(text=text, evidence=[sid])


def deferred_as_decided(meeting: Meeting, rng: random.Random) -> Claim | None:
    if not meeting.deferred:
        return None
    d = rng.choice(meeting.deferred)
    body = d.text.replace(" discussed", "").rstrip(".")
    body = body[0].lower() + body[1:]
    return Claim(text=f"Client agreed to proceed with {body}.", evidence=list(d.evidence))


def small_talk_leakage(
    meeting: Meeting, rng: random.Random, within: set[str] | None = None
) -> Claim | None:
    by_id = meeting.transcript.by_id()
    ids = [i for i in meeting.small_talk_ids if within is None or i in within]
    if not ids:
        return None
    sid = rng.choice(ids)
    return Claim(text=f"Client mentioned: {by_id[sid].text}", evidence=[sid])


def _claims_with_numbers(note: FileNote) -> list[tuple[str, int, Evidenced]]:
    return [
        (s, i, item)
        for s, i, item in note.iter_claims()
        if _NUMBER_SPAN_RE.search(item.label) and s != "follow_up"
    ]


def plant(
    meeting: Meeting, kind: PlantKind, rng: random.Random
) -> tuple[FileNote, str, int] | None:
    """A deep copy of the gold note with one hallucination of ``kind`` planted; returns the
    note and where the planted claim sits. ``None`` when the meeting offers no host for it."""
    note = meeting.gold.model_copy(deep=True)
    transcript = meeting.transcript
    if kind == "invented_decision":
        note.decisions.append(invented_decision(transcript, rng))
        return note, "decisions", len(note.decisions) - 1
    if kind == "deferred_as_decided":
        claim = deferred_as_decided(meeting, rng)
        if claim is None:
            return None
        note.decisions.append(claim)
        return note, "decisions", len(note.decisions) - 1
    if kind == "small_talk_leakage":
        claim = small_talk_leakage(meeting, rng)
        if claim is None:
            return None
        note.topics_discussed.append(claim)
        return note, "topics_discussed", len(note.topics_discussed) - 1
    if kind == "changed_number":
        hosts = _claims_with_numbers(note)
        if not hosts:
            return None
        section, index, item = rng.choice(hosts)
        changed = change_number(item.label, rng)
        if changed is None:
            return None
        if isinstance(item, ActionItem):
            item.description = changed
        elif isinstance(item, Claim):
            item.text = changed
        return note, section, index
    if kind == "wrong_citation":
        hosts = [(s, i, it) for s, i, it in note.iter_claims() if s != "follow_up"]
        if not hosts:
            return None
        section, index, item = rng.choice(hosts)
        wrong_citation(item, transcript, rng)
        return note, section, index
    if not note.action_items:
        return None
    index = rng.randrange(len(note.action_items))
    action = note.action_items[index]
    if kind == "wrong_owner":
        wrong_owner(action, meeting.seed.paraplanner is not None, rng)
    else:
        wrong_date(action, meeting.seed.date, rng)
    return note, "action_items", index
