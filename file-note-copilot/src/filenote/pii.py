"""PII minimisation.

Two different jobs:

* **Pseudonymisation** before the transcript reaches a model: attendee names become
  ``CLIENT_1`` / ``ADVISER`` / ``PARAPLANNER`` through a reversible map, and the names are put
  back into the final note. The model never sees who the client is.
* **Redaction** of anything that is logged or exported (audit trail, metrics, telemetry):
  TFN (weighted mod-11 check so a balance is not mistaken for one), Australian phone numbers,
  e-mail addresses, dates of birth and street addresses.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

from filenote.schema import Attendee, FileNote, Role, Transcript

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_AU_PHONE_RE = re.compile(
    r"(?<![\w-])(?:\+61[ -]?|0)(?:4\d{2}[ -]?\d{3}[ -]?\d{3}|[2378][ -]?\d{4}[ -]?\d{4})(?![\w-])"
)
_TFN_RE = re.compile(r"(?<![\w-])\d{3}[ -]?\d{3}[ -]?\d{3}(?![\w-])")
_DOB_RE = re.compile(
    r"(?:\b(?:born(?: on)?|date of birth|DOB|D\.O\.B\.)\s*(?:is|was|:)?\s*)"
    r"(?P<date>\d{1,2}(?:st|nd|rd|th)?(?:\s+of)?\s+[A-Za-z]{3,9}\.?,?\s+\d{4}|"
    r"\d{1,2}/\d{1,2}/\d{4}|\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_ADDRESS_RE = re.compile(
    r"\b\d{1,4}[A-Za-z]?(?:/\d{1,4})?\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Court|Ct|Place|Pl|Lane|Ln|Crescent|Cres|"
    r"Parade|Pde|Way|Terrace|Tce|Boulevard|Blvd|Close|Cl)\b"
    r"(?:,?\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)?(?:,?\s+(?:NSW|VIC|QLD|WA|SA|TAS|ACT|NT))?(?:\s+\d{4})?"
)

TFN_WEIGHTS = (1, 4, 3, 7, 5, 8, 6, 9, 10)


@dataclass(frozen=True, slots=True)
class PIIMatch:
    kind: str
    start: int
    end: int
    text: str


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def tfn_valid(number: str) -> bool:
    digits = _digits(number)
    if len(digits) != 9:
        return False
    return sum(int(d) * w for d, w in zip(digits, TFN_WEIGHTS, strict=True)) % 11 == 0


def make_tfn(rng: random.Random) -> str:
    """A syntactically valid (mod-11) but random nine-digit TFN for synthetic transcripts."""
    while True:
        first = [rng.randint(1, 9)] + [rng.randint(0, 9) for _ in range(7)]
        partial = sum(d * w for d, w in zip(first, TFN_WEIGHTS[:8], strict=True))
        for last in range(10):
            if (partial + last * TFN_WEIGHTS[8]) % 11 == 0:
                digits = "".join(str(d) for d in [*first, last])
                return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def detect(text: str) -> list[PIIMatch]:
    """All matches, earliest-then-longest priority, overlaps removed."""
    raw: list[PIIMatch] = []
    for m in _DOB_RE.finditer(text):
        raw.append(PIIMatch("DOB", m.start("date"), m.end("date"), m.group("date")))
    for m in _TFN_RE.finditer(text):
        if tfn_valid(m.group()):
            raw.append(PIIMatch("TFN", m.start(), m.end(), m.group()))
    for m in _AU_PHONE_RE.finditer(text):
        raw.append(PIIMatch("PHONE", m.start(), m.end(), m.group()))
    for m in _EMAIL_RE.finditer(text):
        raw.append(PIIMatch("EMAIL", m.start(), m.end(), m.group()))
    for m in _ADDRESS_RE.finditer(text):
        raw.append(PIIMatch("ADDRESS", m.start(), m.end(), m.group()))
    raw.sort(key=lambda p: (p.start, -(p.end - p.start)))
    kept: list[PIIMatch] = []
    for p in raw:
        if kept and p.start < kept[-1].end:
            continue
        kept.append(p)
    return kept


def redact(text: str) -> tuple[str, list[PIIMatch]]:
    matches = detect(text)
    if not matches:
        return text, []
    out: list[str] = []
    cursor = 0
    for m in matches:
        out.append(text[cursor : m.start])
        out.append(f"[{m.kind}]")
        cursor = m.end
    out.append(text[cursor:])
    return "".join(out), matches


# Fields that identify the *staff member* accountable for a decision: kept intact.
PRESERVE_KEYS = frozenset({"approver", "approved_by", "adviser", "requested_by"})


def redact_any(value: Any) -> Any:
    """Recursively redact every string in a JSON-like structure."""
    if isinstance(value, str):
        return redact(value)[0]
    if isinstance(value, dict):
        return {
            k: (v if k in PRESERVE_KEYS and isinstance(v, str) else redact_any(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact_any(v) for v in value]
    return value


# ----- pseudonymisation ---------------------------------------------------------------------

_ROLE_PREFIX: dict[Role, str] = {
    "adviser": "ADVISER",
    "client": "CLIENT",
    "paraplanner": "PARAPLANNER",
    "unknown": "SPEAKER",
}


class Pseudonymiser:
    """Reversible name → placeholder map for one meeting's attendees.

    Full names and bare first names both map to the placeholder; restoration always writes
    the full name, so a note that says ``CLIENT_1's salary`` comes back as ``James Chen's
    salary``.
    """

    def __init__(self, attendees: list[Attendee]) -> None:
        counts: dict[str, int] = {}
        self._full: dict[str, str] = {}
        self._first: dict[str, str] = {}
        self._placeholders: list[str] = []
        for a in attendees:
            prefix = _ROLE_PREFIX[a.role]
            counts[prefix] = counts.get(prefix, 0) + 1
            n_same_role = sum(1 for b in attendees if _ROLE_PREFIX[b.role] == prefix)
            placeholder = f"{prefix}_{counts[prefix]}" if n_same_role > 1 else prefix
            self._full[a.name] = placeholder
            self._placeholders.append(placeholder)
            first = a.name.split()[0]
            if first != a.name:
                self._first.setdefault(first, placeholder)
        firsts = list(self._first)
        for f in firsts:
            if sum(1 for a in attendees if a.name.split()[0] == f) > 1:
                del self._first[f]  # ambiguous first name: leave it (still no full name)
        self._restore = {v: k for k, v in self._full.items()}
        names = sorted(self._full, key=len, reverse=True)
        firsts_sorted = sorted(self._first, key=len, reverse=True)
        pattern = "|".join(re.escape(n) for n in names + firsts_sorted)
        self._apply_re = re.compile(rf"\b(?:{pattern})\b") if pattern else None
        self._restore_re = re.compile(
            r"\b(?:" + "|".join(re.escape(p) for p in self._placeholders) + r")\b"
        )

    @property
    def mapping(self) -> dict[str, str]:
        return dict(self._full)

    def apply(self, text: str) -> str:
        if self._apply_re is None:
            return text
        return self._apply_re.sub(
            lambda m: self._full.get(m.group(0), self._first.get(m.group(0), m.group(0))), text
        )

    def restore(self, text: str) -> str:
        if not self._placeholders:
            return text
        return self._restore_re.sub(lambda m: self._restore.get(m.group(0), m.group(0)), text)

    def transcript(self, transcript: Transcript) -> Transcript:
        return transcript.model_copy(
            update={
                "attendees": [
                    Attendee(name=self.apply(a.name), role=a.role) for a in transcript.attendees
                ],
                "segments": [
                    s.model_copy(
                        update={"speaker": self.apply(s.speaker), "text": self.apply(s.text)}
                    )
                    for s in transcript.segments
                ],
            }
        )

    def restore_note(self, note: FileNote) -> FileNote:
        data = note.model_dump(mode="json")
        return FileNote.model_validate(_map_strings(data, self.restore))


def _map_strings(value: Any, fn: Any) -> Any:
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, dict):
        return {k: _map_strings(v, fn) for k, v in value.items()}
    if isinstance(value, list):
        return [_map_strings(v, fn) for v in value]
    return value
