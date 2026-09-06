"""The transcript and the file note. Every claim in a note cites at least one transcript
segment id; validation against a transcript rejects ids that do not exist."""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Iterator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

MeetingType = Literal["initial", "annual_review", "insurance_review", "retirement_planning"]
Role = Literal["adviser", "client", "paraplanner", "unknown"]
Owner = Literal["adviser", "client", "paraplanner"]
ClaimSection = Literal[
    "circumstance_changes",
    "goals",
    "topics_discussed",
    "advice_discussed",
    "decisions",
    "action_items",
    "vulnerability_indicators",
    "follow_up",
]
CLAIM_SECTIONS: tuple[ClaimSection, ...] = (
    "circumstance_changes",
    "goals",
    "topics_discussed",
    "advice_discussed",
    "decisions",
    "action_items",
    "vulnerability_indicators",
    "follow_up",
)
MEETING_TYPES: tuple[MeetingType, ...] = (
    "initial",
    "annual_review",
    "insurance_review",
    "retirement_planning",
)

# ----- transcript ---------------------------------------------------------------------------


class Attendee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    role: Role


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^s\d{3,}$")
    t: float = Field(ge=0.0, description="seconds from the start of the meeting")
    speaker: str = Field(min_length=1)
    role: Role = "unknown"
    text: str = Field(min_length=1)

    @property
    def timestamp(self) -> str:
        total = int(self.t)
        return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


_HEADER_RE = re.compile(r"^#\s*(?P<key>[a-z_]+)\s*:\s*(?P<value>.*)$")
_SEG_RE = re.compile(
    r"^(?:(?P<id>s\d{3,})\s+)?\[(?P<h>\d{1,2}):(?P<m>\d{2})(?::(?P<s>\d{2}))?\]\s*"
    r"(?P<speaker>[^:\[\]]+?)(?:\s*\((?P<role>adviser|client|paraplanner)\))?\s*:\s*(?P<text>.+)$"
)
_SPEAKER_RE = re.compile(
    r"^(?P<speaker>[^:\[\]]{1,60}?)(?:\s*\((?P<role>adviser|client|paraplanner)\))?\s*:\s*(?P<text>.+)$"
)


class Transcript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str = Field(min_length=1)
    date: dt.date | None = None
    type: MeetingType | None = None
    attendees: list[Attendee] = Field(default_factory=list)
    segments: list[Segment] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Transcript:
        ids = [s.id for s in self.segments]
        if len(set(ids)) != len(ids):
            msg = "duplicate segment ids"
            raise ValueError(msg)
        return self

    @property
    def segment_ids(self) -> list[str]:
        return [s.id for s in self.segments]

    def by_id(self) -> dict[str, Segment]:
        return {s.id: s for s in self.segments}

    def role_of(self, speaker: str) -> Role:
        for a in self.attendees:
            if a.name == speaker:
                return a.role
        return "unknown"

    def windows(self, size: int) -> list[list[Segment]]:
        size = max(1, size)
        return [self.segments[i : i + size] for i in range(0, len(self.segments), size)]

    def to_text(self) -> str:
        lines = [f"# meeting: {self.meeting_id}"]
        if self.date is not None:
            lines.append(f"# date: {self.date.isoformat()}")
        if self.type is not None:
            lines.append(f"# type: {self.type}")
        lines.extend(f"# attendee: {a.name} | {a.role}" for a in self.attendees)
        lines.extend(
            f"{s.id} [{s.timestamp}] {s.speaker} ({s.role}): {s.text}" for s in self.segments
        )
        return "\n".join(lines) + "\n"

    @classmethod
    def from_text(cls, text: str, *, meeting_id: str = "pasted") -> Transcript:
        """Parse ``to_text`` output, or looser ``[hh:mm] Name: text`` / ``Name: text`` /
        bare lines; missing ids and timestamps are generated."""
        header: dict[str, Any] = {"meeting_id": meeting_id, "attendees": []}
        segments: list[Segment] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            h = _HEADER_RE.match(line)
            if h and not segments:
                key, value = h["key"], h["value"].strip()
                if key == "meeting":
                    header["meeting_id"] = value or meeting_id
                elif key == "date":
                    header["date"] = value
                elif key == "type":
                    header["type"] = value
                elif key == "attendee" and "|" in value:
                    name, role = (p.strip() for p in value.split("|", 1))
                    header["attendees"].append({"name": name, "role": role})
                continue
            n = len(segments) + 1
            seg = _SEG_RE.match(line)
            if seg:
                t = int(seg["h"]) * 3600 + int(seg["m"]) * 60 + int(seg["s"] or 0)
                if seg["s"] is None:
                    t = int(seg["h"]) * 60 + int(seg["m"])
                segments.append(
                    Segment(
                        id=seg["id"] or f"s{n:03d}",
                        t=float(t),
                        speaker=seg["speaker"].strip(),
                        role=seg["role"] or "unknown",
                        text=seg["text"].strip(),
                    )
                )
                continue
            sp = _SPEAKER_RE.match(line)
            if sp:
                segments.append(
                    Segment(
                        id=f"s{n:03d}",
                        t=float(n * 10),
                        speaker=sp["speaker"].strip(),
                        role=sp["role"] or "unknown",
                        text=sp["text"].strip(),
                    )
                )
                continue
            segments.append(Segment(id=f"s{n:03d}", t=float(n * 10), speaker="unknown", text=line))
        if not segments:
            msg = "transcript has no segments"
            raise ValueError(msg)
        names = {a["name"] for a in header["attendees"]}
        for s in segments:
            if s.role == "unknown":
                for a in header["attendees"]:
                    if a["name"] == s.speaker:
                        s.role = a["role"]
            elif s.speaker not in names and s.speaker != "unknown":
                header["attendees"].append({"name": s.speaker, "role": s.role})
                names.add(s.speaker)
        return cls(segments=segments, **header)


# ----- file note ----------------------------------------------------------------------------


class Evidenced(BaseModel):
    """Anything the adviser will sign: it cites segments, and the verifier can flag it."""

    model_config = ConfigDict(extra="forbid")

    evidence: list[str] = Field(min_length=1, description="transcript segment ids")
    quote: str | None = None
    unsupported: bool = False
    reasons: list[str] = Field(default_factory=list)
    edited: bool = False

    @property
    def label(self) -> str:
        raise NotImplementedError


class Claim(Evidenced):
    text: str = Field(min_length=1)

    @property
    def label(self) -> str:
        return self.text


class ActionItem(Evidenced):
    description: str = Field(min_length=1)
    owner: Owner
    due: dt.date | None = None

    @property
    def label(self) -> str:
        return self.description


class MeetingMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    date: dt.date
    type: MeetingType
    attendees: list[Attendee] = Field(default_factory=list)
    duration_minutes: int | None = Field(default=None, ge=0)


class ComplianceFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    risk_profile_confirmed: bool | None = None
    risk_profile: str | None = None
    fee_consent_discussed: bool | None = None
    conflicts_disclosed: bool | None = None
    vulnerability_indicators: list[Claim] = Field(default_factory=list)


class FileNote(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting: MeetingMeta
    summary: str = ""
    circumstance_changes: list[Claim] = Field(default_factory=list)
    goals: list[Claim] = Field(default_factory=list)
    topics_discussed: list[Claim] = Field(default_factory=list)
    advice_discussed: list[Claim] = Field(default_factory=list)
    decisions: list[Claim] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    compliance: ComplianceFlags = Field(default_factory=ComplianceFlags)
    follow_up: Claim | None = None

    @model_validator(mode="after")
    def _known_evidence(self, info: ValidationInfo) -> FileNote:
        """``FileNote.model_validate(data, context={"segment_ids": {...}})`` rejects unknown ids."""
        ctx = info.context or {}
        ids = ctx.get("segment_ids")
        if ids is not None:
            unknown = self.unknown_evidence(set(ids))
            if unknown:
                msg = f"unknown segment ids cited: {sorted(unknown)}"
                raise ValueError(msg)
        return self

    def iter_claims(self) -> Iterator[tuple[ClaimSection, int, Evidenced]]:
        for section in CLAIM_SECTIONS:
            for i, item in enumerate(self.section_items(section)):
                yield section, i, item

    def section_items(self, section: ClaimSection) -> list[Evidenced]:
        if section == "action_items":
            return list(self.action_items)
        if section == "vulnerability_indicators":
            return list(self.compliance.vulnerability_indicators)
        if section == "follow_up":
            return [self.follow_up] if self.follow_up is not None else []
        items: list[Claim] = getattr(self, section)
        return list(items)

    def all_claims(self) -> list[Evidenced]:
        return [item for _, _, item in self.iter_claims()]

    def unknown_evidence(self, segment_ids: set[str]) -> set[str]:
        return {e for item in self.all_claims() for e in item.evidence if e not in segment_ids}

    def validate_against(self, transcript: Transcript) -> None:
        unknown = self.unknown_evidence(set(transcript.segment_ids))
        if unknown:
            msg = f"unknown segment ids cited: {sorted(unknown)}"
            raise ValueError(msg)

    def unsupported_count(self) -> int:
        return sum(1 for item in self.all_claims() if item.unsupported and not item.edited)

    def to_markdown(self) -> str:
        """The text the adviser signs; the approval diff is computed on these lines."""
        m = self.meeting
        who = ", ".join(f"{a.name} ({a.role})" for a in m.attendees)
        lines = [
            f"# File note — {m.type.replace('_', ' ')} on {m.date.isoformat()}",
            f"Attendees: {who}",
        ]
        if m.duration_minutes is not None:
            lines.append(f"Duration: {m.duration_minutes} minutes")
        lines += ["", "## Summary", self.summary]

        def _claims(title: str, items: list[Claim]) -> None:
            lines.append("")
            lines.append(f"## {title}")
            if not items:
                lines.append("- (none)")
            for c in items:
                flag = " [UNSUPPORTED]" if c.unsupported and not c.edited else ""
                lines.append(f"- {c.text}{flag} ({', '.join(c.evidence)})")

        _claims("Changes in circumstances", self.circumstance_changes)
        _claims("Goals", self.goals)
        _claims("Topics discussed", self.topics_discussed)
        _claims("Advice discussed", self.advice_discussed)
        _claims("Decisions", self.decisions)
        lines += ["", "## Action items"]
        if not self.action_items:
            lines.append("- (none)")
        for a in self.action_items:
            due = f" due {a.due.isoformat()}" if a.due else ""
            flag = " [UNSUPPORTED]" if a.unsupported and not a.edited else ""
            lines.append(f"- [{a.owner}] {a.description}{due}{flag} ({', '.join(a.evidence)})")
        c = self.compliance
        lines += [
            "",
            "## Compliance",
            f"- Risk profile confirmed: {c.risk_profile_confirmed} ({c.risk_profile})",
            f"- Ongoing fee consent discussed: {c.fee_consent_discussed}",
            f"- Conflicts / related-party products disclosed: {c.conflicts_disclosed}",
        ]
        for v in c.vulnerability_indicators:
            lines.append(f"- Vulnerability indicator: {v.text} ({', '.join(v.evidence)})")
        lines += ["", "## Follow-up"]
        lines.append(
            f"- {self.follow_up.text} ({', '.join(self.follow_up.evidence)})"
            if self.follow_up
            else "- (none)"
        )
        return "\n".join(lines) + "\n"
