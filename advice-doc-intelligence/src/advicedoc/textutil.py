"""Small parsers shared by the metadata rules, the rules extractor, the validators and the
evaluator: the three date formats, the three currency formats and percentages the corpus
uses, plus name normalisation."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

MONTHS: dict[str, int] = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
_MONTH_ALT = "|".join(MONTHS)
DATE_LONG = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{4}})\b", re.IGNORECASE)
DATE_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

MONEY = re.compile(
    r"(?P<neg1>-)?\s*(?:\$|AUD)\s*(?P<neg2>-)?\s*(?P<amt1>\d[\d,]*(?:\.\d+)?)"
    r"|(?P<neg3>-)?(?P<amt2>\d[\d,]*(?:\.\d+)?)\s*dollars",
    re.IGNORECASE,
)
PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per cent|percent)", re.IGNORECASE)


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[tuple[int, date]]:
    """Every date in ``text`` in any of the corpus formats, with its character offset."""
    found: list[tuple[int, date]] = []
    for m in DATE_LONG.finditer(text):
        d = _safe_date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1)))
        if d is not None:
            found.append((m.start(), d))
    for m in DATE_SLASH.finditer(text):
        d = _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        if d is not None:
            found.append((m.start(), d))
    for m in DATE_ISO.finditer(text):
        d = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if d is not None:
            found.append((m.start(), d))
    found.sort(key=lambda t: t[0])
    return found


def parse_date(text: str) -> date | None:
    dates = find_dates(text)
    return dates[0][1] if dates else None


def _to_decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", ""))
    except InvalidOperation:
        return None


def find_money(text: str) -> list[tuple[int, Decimal]]:
    found: list[tuple[int, Decimal]] = []
    for m in MONEY.finditer(text):
        raw = m.group("amt1") or m.group("amt2")
        value = _to_decimal(raw)
        if value is None:
            continue
        negative = bool(m.group("neg1") or m.group("neg2") or m.group("neg3"))
        found.append((m.start(), -value if negative else value))
    return found


def parse_money(text: str) -> Decimal | None:
    money = find_money(text)
    return money[0][1] if money else None


def parse_percent(text: str) -> Decimal | None:
    m = PERCENT.search(text)
    return _to_decimal(m.group(1)) if m else None


def normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"\s+", " ", value.strip().lower()))


def split_names(value: str) -> list[str]:
    """``"A and B"`` / ``"A; B"`` / ``"A, B"`` -> ``["A", "B"]`` (emails and parentheticals
    stripped)."""
    cleaned = re.sub(r"<[^>]*>", "", value)
    cleaned = re.sub(r"\([^)]*\)", "", cleaned)
    parts = re.split(r"\s+and\s+|\s*;\s*|\s*&\s*|,\s+", cleaned)
    return [p.strip(" .") for p in parts if p.strip(" .")]
