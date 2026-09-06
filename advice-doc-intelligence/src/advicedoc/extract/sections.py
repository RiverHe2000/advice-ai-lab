"""Section detection for a Statement of Advice: headings are matched against a small set of
patterns per section (numbered or not, any case); tables are attributed to a section by
their header cells, falling back to the section active on that page."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from advicedoc.ingest import Document, Table

HEADING_PATTERNS: dict[str, tuple[str, ...]] = {
    "scope": (r"scope of (the )?advice", r"what this advice covers"),
    "situation": (r"your (current )?situation", r"your personal and financial situation"),
    "risk": (r"(your )?risk profile( assessment)?",),
    "recommendations": (r"(our )?recommendations", r"what we recommend"),
    "replacement": (r"product replacement( comparison)?", r"replacing your existing products"),
    "fees": (r"fees and (costs|charges)", r"what this advice costs"),
    "important": (r"important information", r"disclosures"),
    "authority": (r"(your )?authority to proceed",),
}
_HEADINGS = {
    name: re.compile(r"^\s*(\d+\.\s*)?(" + "|".join(pats) + r")\s*$", re.IGNORECASE)
    for name, pats in HEADING_PATTERNS.items()
}
TABLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("recommendations", ("action", "product")),
    ("replacement", ("current product", "recommended product")),
    ("fees", ("fee", "amount")),
    ("situation", ("balance / cover",)),
)


@dataclass(slots=True)
class Section:
    name: str
    lines: list[str] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    pages: list[int] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def flat(self) -> str:
        return " ".join(ln.strip() for ln in self.lines if ln.strip())


_HEADING_PHRASES: dict[str, tuple[str, ...]] = {
    "scope": ("scope of advice", "scope of the advice", "what this advice covers"),
    "situation": (
        "your current situation",
        "your situation",
        "your personal and financial situation",
    ),
    "risk": ("your risk profile", "risk profile", "risk profile assessment"),
    "recommendations": ("our recommendations", "recommendations", "what we recommend"),
    "replacement": (
        "product replacement",
        "product replacement comparison",
        "replacing your existing products",
    ),
    "fees": ("fees and costs", "fees and charges", "what this advice costs"),
    "important": ("important information", "disclosures"),
    "authority": ("authority to proceed", "your authority to proceed"),
}
_NUMBERING = re.compile(r"^\s*\d+[.)]?\s*")
FUZZY_HEADING_SCORE = 88.0
MAX_HEADING_CHARS = 45


def heading_of(line: str) -> str | None:
    """Exact heading match first; for short lines a fuzzy match against the known heading
    phrases so that OCR-like corruption (``0ur recommendatlons``) still finds the section."""
    for name, pattern in _HEADINGS.items():
        if pattern.match(line):
            return name
    stripped = _NUMBERING.sub("", line).strip().lower()
    # Headings carry no sentence punctuation; a wrapped sentence tail such as
    # "... aligned to your risk profile." must not open a section.
    if (
        not stripped
        or len(stripped) > MAX_HEADING_CHARS
        or stripped[-1] in ".,;:"
        or ":" in stripped
    ):
        return None
    best_name, best_score = None, 0.0
    for name, phrases in _HEADING_PHRASES.items():
        for phrase in phrases:
            score = fuzz.ratio(stripped, phrase)
            if score > best_score:
                best_name, best_score = name, score
    return best_name if best_score >= FUZZY_HEADING_SCORE else None


def table_section(table: Table) -> str | None:
    header = [c.lower().strip() for c in table[0]] if table else []
    joined = " | ".join(header)
    for name, hints in TABLE_HINTS:
        if all(h in joined for h in hints):
            return name
    return None


def detect_sections(doc: Document) -> dict[str, Section]:
    sections: dict[str, Section] = {"header": Section("header")}
    current = "header"
    for page in doc.pages:
        page_start = current
        for line in page.lines:
            name = heading_of(line)
            if name is not None:
                current = name
                sections.setdefault(name, Section(name))
                if page.number not in sections[name].pages:
                    sections[name].pages.append(page.number)
                continue
            sections[current].lines.append(line)
            if page.number not in sections[current].pages:
                sections[current].pages.append(page.number)
        for table in page.tables:
            target = table_section(table) or current
            if target == page_start and target not in sections:
                target = current
            sections.setdefault(target, Section(target)).tables.append(table)
    return sections
