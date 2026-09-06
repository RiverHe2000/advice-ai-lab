"""Rule-based metadata (client names, adviser, document date) from the first page: labelled
fields first (``Prepared for``, ``Client(s)``, ``Member``, ``Account holder``, ``To`` ...),
then letter conventions (the name line above a street address; the sign-off after ``Kind
regards``), then the first date on the page. The LLM is an optional fallback in the
workflow, not part of these rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from advicedoc.ingest import Document
from advicedoc.textutil import find_dates, split_names

CLIENT_LABELS: tuple[str, ...] = (
    "prepared for",
    "client(s)",
    "clients",
    "client",
    "member",
    "account holder",
    "policy owner",
    "to",
)
ADVISER_LABELS: tuple[str, ...] = (
    "prepared by",
    "your adviser",
    "financial adviser",
    "adviser",
    "from",
)
DATE_LABELS: tuple[str, ...] = (
    "date of advice",
    "advice date",
    "date issued",
    "issue date",
    "date completed",
    "date signed",
    "statement date",
    "date",
)
SIGN_OFFS = re.compile(
    r"^(kind regards|regards|yours sincerely|yours faithfully),?$", re.IGNORECASE
)
STREET = re.compile(
    r"^\d+[a-z]?\s+[A-Z][A-Za-z' ]+\s(Avenue|Street|Crescent|Drive|Road|Court|Lane|Parade)$"
)
CLIENT_N = re.compile(r"^client\s*\d+\s*:\s*(.+)$", re.IGNORECASE)
NAME_SHAPE = re.compile(r"^[A-Z][A-Za-z'\-]+(\s+[A-Z][A-Za-z'\-]+)+$")


def _labelled(line: str, labels: tuple[str, ...]) -> str | None:
    lowered = line.lower()
    for label in labels:
        prefix = f"{label}:"
        if lowered.startswith(prefix):
            return line[len(prefix) :].strip()
    return None


def _clean_person(value: str) -> str:
    value = re.sub(r"<[^>]*>", "", value)
    value = re.sub(r"\([^)]*\)", "", value)
    value = value.split(",")[0]
    return value.strip(" .-")


@dataclass(slots=True)
class MetadataGuess:
    client_names: list[str] = field(default_factory=list)
    adviser_name: str | None = None
    document_date: date | None = None
    evidence: dict[str, str] = field(default_factory=dict)


def extract_metadata(doc: Document) -> MetadataGuess:
    lines = [ln.strip() for ln in (doc.pages[0].lines if doc.pages else [])]
    guess = MetadataGuess()
    numbered: list[str] = []
    for i, line in enumerate(lines):
        m = CLIENT_N.match(line)
        if m:
            numbered.append(_clean_person(m.group(1)))
            guess.evidence.setdefault("client_names", line)
            continue
        if not guess.client_names and not numbered:
            value = _labelled(line, CLIENT_LABELS)
            if value:
                names = [_clean_person(n) for n in split_names(value)]
                guess.client_names = [n for n in names if n]
                guess.evidence["client_names"] = line
        if guess.adviser_name is None:
            value = _labelled(line, ADVISER_LABELS)
            if value:
                guess.adviser_name = _clean_person(value) or None
                guess.evidence["adviser_name"] = line
            elif SIGN_OFFS.match(line) and i + 1 < len(lines) and NAME_SHAPE.match(lines[i + 1]):
                guess.adviser_name = lines[i + 1]
                guess.evidence["adviser_name"] = lines[i + 1]
    if numbered:
        guess.client_names = numbered
    if not guess.client_names:
        for i, line in enumerate(lines):
            if STREET.match(line) and i > 0:
                candidates = [_clean_person(n) for n in split_names(lines[i - 1])]
                if candidates and all(NAME_SHAPE.match(c) for c in candidates):
                    guess.client_names = candidates
                    guess.evidence["client_names"] = lines[i - 1]
                break
    guess.document_date = _document_date(lines, guess.evidence)
    return guess


def _document_date(lines: list[str], evidence: dict[str, str]) -> date | None:
    for label in DATE_LABELS:
        for line in lines:
            value = _labelled(line, (label,))
            if value:
                dates = find_dates(value)
                if dates:
                    evidence["document_date"] = line
                    return dates[0][1]
    for line in lines:
        dates = find_dates(line)
        if dates:
            evidence["document_date"] = line
            return dates[0][1]
    return None
