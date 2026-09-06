"""Atomic facts: what the extraction pass produces per transcript window and the *only* thing
the composition pass sees. The model never sees the raw transcript in pass 2, which shrinks
the surface for invention and lets a two-hour meeting fit any context window."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from filenote.schema import (
    ActionItem,
    Claim,
    ComplianceFlags,
    FileNote,
    MeetingMeta,
    Owner,
)

FactCategory = Literal[
    "circumstance_change",
    "goal",
    "topic",
    "advice",
    "decision",
    "action_item",
    "vulnerability",
    "follow_up",
    "compliance",
]
ComplianceKey = Literal[
    "risk_profile_confirmed", "risk_profile", "fee_consent_discussed", "conflicts_disclosed"
]
CATEGORY_TO_SECTION: dict[str, str] = {
    "circumstance_change": "circumstance_changes",
    "goal": "goals",
    "topic": "topics_discussed",
    "advice": "advice_discussed",
    "decision": "decisions",
    "action_item": "action_items",
    "vulnerability": "vulnerability_indicators",
    "follow_up": "follow_up",
}
SECTION_TO_CATEGORY: dict[str, str] = {v: k for k, v in CATEGORY_TO_SECTION.items()}


class Fact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: FactCategory
    text: str = ""
    evidence: list[str] = Field(default_factory=list)
    owner: Owner | None = None
    due: dt.date | None = None
    key: ComplianceKey | None = None
    value: bool | str | None = None


class FactList(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facts: list[Fact] = Field(default_factory=list)


def _evidence(fact: Fact) -> list[str]:
    return list(dict.fromkeys(fact.evidence)) or ["unknown"]


def compose_from_facts(facts: list[Fact], meeting: MeetingMeta, summary: str) -> FileNote:
    """Deterministic composition used by the scripted model and as the reference behaviour
    the composition prompt asks a real model for: merge facts with the same category and
    text (union of evidence), map categories to sections, fold compliance facts into flags."""
    merged: dict[tuple[str, str], Fact] = {}
    order: list[tuple[str, str]] = []
    flags = ComplianceFlags()
    for f in facts:
        if f.category == "compliance":
            if f.key == "risk_profile":
                flags.risk_profile = str(f.value) if f.value is not None else None
            elif f.key is not None and isinstance(f.value, bool):
                setattr(flags, f.key, f.value)
            continue
        key: tuple[str, str] = (f.category, f.text.strip().lower())
        if key in merged:
            m = merged[key]
            m.evidence = list(dict.fromkeys([*m.evidence, *f.evidence]))
            m.owner = m.owner or f.owner
            m.due = m.due or f.due
        else:
            merged[key] = f.model_copy(deep=True)
            order.append(key)
    note = FileNote(meeting=meeting, summary=summary, compliance=flags)
    for key in order:
        f = merged[key]
        if not f.text.strip():
            continue
        if f.category == "action_item":
            note.action_items.append(
                ActionItem(
                    description=f.text, owner=f.owner or "adviser", due=f.due, evidence=_evidence(f)
                )
            )
        elif f.category == "vulnerability":
            flags.vulnerability_indicators.append(Claim(text=f.text, evidence=_evidence(f)))
        elif f.category == "follow_up":
            if note.follow_up is None:
                note.follow_up = Claim(text=f.text, evidence=_evidence(f))
        else:
            section: list[Claim] = getattr(note, CATEGORY_TO_SECTION[f.category])
            section.append(Claim(text=f.text, evidence=_evidence(f)))
    return note


def facts_from_note(note: FileNote, *, only_ids: set[str] | None = None) -> list[Fact]:
    """Inverse of ``compose_from_facts`` (used by the scripted model): one fact per claim,
    optionally restricted to claims with evidence inside ``only_ids``."""
    out: list[Fact] = []
    for section, _, item in note.iter_claims():
        evidence = [e for e in item.evidence if only_ids is None or e in only_ids]
        if only_ids is not None and not evidence:
            continue
        fact = Fact(category=SECTION_TO_CATEGORY[section], text=item.label, evidence=evidence)
        if isinstance(item, ActionItem):
            fact.owner = item.owner
            fact.due = item.due
        out.append(fact)
    return out


def compliance_facts(flags: ComplianceFlags) -> list[Fact]:
    out: list[Fact] = []
    for key in ("risk_profile_confirmed", "fee_consent_discussed", "conflicts_disclosed"):
        value = getattr(flags, key)
        if value is not None:
            out.append(Fact(category="compliance", key=key, value=value))
    if flags.risk_profile is not None:
        out.append(Fact(category="compliance", key="risk_profile", value=flags.risk_profile))
    return out
