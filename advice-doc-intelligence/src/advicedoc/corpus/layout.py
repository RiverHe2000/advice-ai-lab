"""Layout model for generated documents: a document is a list of pages, a page a list of
blocks (headings, paragraphs, tables). The same block structure is rendered to a real PDF
(``render.py``) and to the in-memory ``Document`` the pipeline consumes (``to_document``),
so tests can exercise everything downstream without touching PDFs while the results in
``docs/`` come from the PDF round trip.

Layout *variants* differ in fonts, heading style, date and currency formats, section order
and table-vs-prose presentation; the generator picks one per document.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from advicedoc.ingest import Document, Table


@dataclass(frozen=True, slots=True)
class Heading:
    text: str
    level: int = 1


@dataclass(frozen=True, slots=True)
class Para:
    text: str
    style: Literal["body", "small", "label", "bullet"] = "body"


@dataclass(frozen=True, slots=True)
class TableBlock:
    rows: tuple[tuple[str, ...], ...]


@dataclass(frozen=True, slots=True)
class Spacer:
    height: float = 8.0


Block = Heading | Para | TableBlock | Spacer


@dataclass(slots=True)
class LayoutDocument:
    doc_id: str
    pages: list[list[Block]]
    header: str
    footer: str
    style: Style

    @property
    def n_pages(self) -> int:
        return len(self.pages)


DateFormat = Literal["long", "slash", "iso"]
MoneyFormat = Literal["dollar", "aud", "words"]


@dataclass(frozen=True, slots=True)
class Style:
    variant: int
    font: str
    date_fmt: DateFormat
    money_fmt: MoneyFormat
    heading_upper: bool
    numbered: bool
    use_tables: bool
    pct_words: bool = False
    body_size: float = 10.0
    page_numbers: str = "Page {n}"
    filler_paragraphs: int = 2
    filler_sentences: list[str] = field(default_factory=list)


STYLES: tuple[Style, ...] = (
    Style(0, "Helvetica", "long", "dollar", False, True, True, body_size=10.0),
    Style(1, "Times-Roman", "slash", "aud", False, False, False, pct_words=True, body_size=10.5),
    Style(2, "Courier", "iso", "words", True, True, True, body_size=9.5, page_numbers="p. {n}"),
)

MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def fmt_date(d: date, style: Style) -> str:
    if style.date_fmt == "long":
        return f"{d.day} {MONTHS[d.month - 1]} {d.year}"
    if style.date_fmt == "slash":
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
    return d.isoformat()


def fmt_money(amount: Decimal, style: Style) -> str:
    sign = "-" if amount < 0 else ""
    magnitude = abs(amount)
    whole = magnitude.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    if style.money_fmt == "dollar":
        cents = magnitude.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return f"{sign}${cents:,.2f}"
    if style.money_fmt == "aud":
        return f"AUD {sign}{whole}"
    return f"{sign}{whole:,} dollars"


def article(noun: str) -> str:
    return "an" if noun[:1].lower() in "aeiou" else "a"


def fmt_pct(pct: Decimal, style: Style) -> str:
    value = f"{pct.normalize():f}" if pct != pct.to_integral() else f"{int(pct)}"
    return f"{value} per cent" if style.pct_words else f"{value}%"


def heading_text(text: str, number: int | None, style: Style) -> str:
    label = f"{number}. {text}" if (style.numbered and number is not None) else text
    return label.upper() if style.heading_upper else label


# ----- text rendering (what pdfplumber would give back, approximately) ----------------------

WRAP_WIDTH = 95


def block_lines(block: Block, tables: list[Table]) -> list[str]:
    if isinstance(block, Heading):
        return [block.text]
    if isinstance(block, Para):
        prefix = "- " if block.style == "bullet" else ""
        return textwrap.wrap(prefix + block.text, width=WRAP_WIDTH) or [""]
    if isinstance(block, TableBlock):
        rows = [list(r) for r in block.rows]
        tables.append(rows)
        return ["  ".join(cell for cell in row) for row in rows]
    return []


def to_document(layout: LayoutDocument) -> Document:
    pages: list[tuple[list[str], list[Table]]] = []
    for i, blocks in enumerate(layout.pages):
        lines: list[str] = [layout.header]
        tables: list[Table] = []
        for b in blocks:
            lines.extend(block_lines(b, tables))
        lines.append(f"{layout.footer}  {layout.style.page_numbers.format(n=i + 1)}")
        pages.append(([ln for ln in lines if ln is not None], tables))
    return Document.from_pages(pages, source=layout.doc_id)
