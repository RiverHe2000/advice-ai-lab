"""Numbers and dates as they are *spoken* in a meeting and *written* in a note.

"eighty-five thousand", "$85k", "85,000" and "85 thousand dollars" are the same figure; the
verifier compares figures after this normalisation so a paraphrase is not a mismatch and a
changed number is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_UNITS: dict[str, int] = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
}
_TENS: dict[str, int] = {
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
}
_BIG: dict[str, float] = {
    "thousand": 1e3,
    "grand": 1e3,
    "million": 1e6,
    "mil": 1e6,
    "billion": 1e9,
}
_SUFFIX: dict[str, float] = {
    "k": 1e3,
    "m": 1e6,
    "mil": 1e6,
    "million": 1e6,
    "thousand": 1e3,
    "grand": 1e3,
    "bn": 1e9,
    "billion": 1e9,
}
_FILLER = {"a", "an", "and", "point"}
NUMBER_WORDS = frozenset(set(_UNITS) | set(_TENS) | set(_BIG) | {"hundred"})
_WORDS = sorted(NUMBER_WORDS | _FILLER, key=len, reverse=True)

_SPOKEN_RE = re.compile(r"\b(?:(?:" + "|".join(_WORDS) + r")\b[\s-]*)+", re.IGNORECASE)
# Identifiers such as ``s034`` or the pseudonym ``CLIENT_2`` are never figures: a digit run
# must not be glued to a letter, a digit, a dot, a comma or an underscore on either side.
_DIGIT_RE = re.compile(
    r"(?<![A-Za-z\d.,_])"
    r"(?:AUD\s?|A?\$\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?:\.(?P<frac>\d+))?"
    r"(?:\s*(?P<suffix>million|thousand|billion|percent|per\s?cent|grand|mil|bn|k|m|%)"
    r"(?![A-Za-z\d_])|(?![A-Za-z\d_]))",
    re.IGNORECASE,
)

_MONTHS: dict[str, int] = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_MONTH_RE = (
    r"(?P<month>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_ISO_RE = re.compile(r"\b(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})\b")
_SLASH_RE = re.compile(r"\b(?P<d>\d{1,2})/(?P<m>\d{1,2})/(?P<y>\d{4})\b")
_DMY_RE = re.compile(
    r"\b(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?" + _MONTH_RE + r"\b\.?,?(?:\s+(?P<y>\d{4}))?",
    re.IGNORECASE,
)
_MDY_RE = re.compile(
    r"\b" + _MONTH_RE + r"\b\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(?P<y>\d{4}))?\b",
    re.IGNORECASE,
)
_MY_RE = re.compile(r"\b" + _MONTH_RE + r"\b\.?\s+(?P<y>\d{4})\b", re.IGNORECASE)


@dataclass(frozen=True, slots=True, order=True)
class DateRef:
    """A date mention; ``year`` / ``day`` are ``None`` when the text did not say them."""

    month: int
    day: int | None = None
    year: int | None = None

    def agrees(self, other: DateRef) -> bool:
        if self.month != other.month:
            return False
        if self.day is not None and other.day is not None and self.day != other.day:
            return False
        return self.year is None or other.year is None or self.year == other.year

    def __str__(self) -> str:
        y = f"{self.year:04d}" if self.year is not None else "????"
        d = f"-{self.day:02d}" if self.day is not None else ""
        return f"{y}-{self.month:02d}{d}"


def _month_number(name: str) -> int:
    return _MONTHS[name[:3].lower()]


def _parse_words(tokens: list[str]) -> float | None:
    total = 0.0
    current = 0.0
    seen = False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in _UNITS:
            current += _UNITS[t]
            seen = True
        elif t in _TENS:
            current += _TENS[t]
            seen = True
        elif t == "hundred":
            current = (current or 1.0) * 100.0
            seen = True
        elif t in _BIG:
            total += (current or 1.0) * _BIG[t]
            current = 0.0
            seen = True
        elif t == "point":
            digits: list[str] = []
            i += 1
            while i < len(tokens) and tokens[i] in _UNITS and _UNITS[tokens[i]] < 10:
                digits.append(str(_UNITS[tokens[i]]))
                i += 1
            if digits:
                current += float("0." + "".join(digits))
                seen = True
            continue
        i += 1
    return total + current if seen else None


def find_dates(text: str) -> tuple[list[DateRef], list[tuple[int, int]]]:
    """Date mentions and their character spans (spans are removed before number extraction)."""
    found: list[tuple[int, int, DateRef]] = []
    taken: list[tuple[int, int]] = []

    def _free(start: int, end: int) -> bool:
        return all(end <= s or start >= e for s, e in taken)

    for m in _ISO_RE.finditer(text):
        found.append((m.start(), m.end(), DateRef(int(m["m"]), int(m["d"]), int(m["y"]))))
        taken.append((m.start(), m.end()))
    for m in _SLASH_RE.finditer(text):
        if _free(m.start(), m.end()) and 1 <= int(m["m"]) <= 12:
            found.append((m.start(), m.end(), DateRef(int(m["m"]), int(m["d"]), int(m["y"]))))
            taken.append((m.start(), m.end()))
    for pattern in (_DMY_RE, _MDY_RE):
        for m in pattern.finditer(text):
            if not _free(m.start(), m.end()):
                continue
            day = int(m["d"])
            if not 1 <= day <= 31:
                continue
            year = int(m["y"]) if m["y"] else None
            found.append((m.start(), m.end(), DateRef(_month_number(m["month"]), day, year)))
            taken.append((m.start(), m.end()))
    for m in _MY_RE.finditer(text):
        if _free(m.start(), m.end()):
            found.append(
                (m.start(), m.end(), DateRef(_month_number(m["month"]), None, int(m["y"])))
            )
            taken.append((m.start(), m.end()))
    found.sort(key=lambda f: f[0])
    return [f[2] for f in found], [(f[0], f[1]) for f in found]


def strip_dates(text: str) -> str:
    _, spans = find_dates(text)
    if not spans:
        return text
    out: list[str] = []
    cursor = 0
    for start, end in spans:
        out.append(text[cursor:start])
        out.append(" " * (end - start))
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def find_numbers(text: str, *, skip_dates: bool = True) -> list[float]:
    """Every figure in ``text`` normalised to a float, in order of appearance.

    Digits with thousands separators, decimals, currency and ``k``/``m``/``%`` suffixes, and
    spoken forms ("twenty-seven thousand five hundred", "one point two million").
    """
    src = strip_dates(text) if skip_dates else text
    values: list[tuple[int, float]] = []
    for m in _DIGIT_RE.finditer(src):
        value = float(m["num"].replace(",", ""))
        if m["frac"]:
            value += float("0." + m["frac"])
        suffix = (m["suffix"] or "").lower().replace(" ", "")
        if suffix in _SUFFIX:
            value *= _SUFFIX[suffix]
        values.append((m.start(), value))
    for m in _SPOKEN_RE.finditer(src):
        tokens = [t for t in re.split(r"[\s-]+", m.group(0).lower()) if t]
        spoken = _parse_words(tokens)
        if spoken is None:
            continue
        # "85 thousand": the digit regex already took the scale word as a suffix.
        prefix = src[max(0, m.start() - 12) : m.start()]
        if tokens[0] in _BIG and re.search(r"\d\s*$", prefix):
            continue
        values.append((m.start(), spoken))
    values.sort(key=lambda v: v[0])
    return [round(v, 6) for _, v in values]


def number_set(text: str) -> set[float]:
    return set(find_numbers(text))


def format_amount(value: float) -> str:
    """Canonical written form used in gold notes and rendered claims."""
    if float(value).is_integer():
        return f"${int(value):,}"
    return f"${value:,.2f}"


_ONES_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_TENS_WORDS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def _below_thousand(n: int) -> str:
    parts: list[str] = []
    if n >= 100:
        parts.append(f"{_ONES_WORDS[n // 100]} hundred")
        n %= 100
        if n:
            parts.append("and")
    if n >= 20:
        tens = _TENS_WORDS[n // 10]
        parts.append(f"{tens}-{_ONES_WORDS[n % 10]}" if n % 10 else tens)
    elif n or not parts:
        parts.append(_ONES_WORDS[n])
    return " ".join(parts)


def number_to_words(value: float) -> str:
    """Spoken form of a non-negative number: 85000 -> "eighty-five thousand",
    9.5 -> "nine point five", 1200000 -> "one point two million" when that is shorter."""
    if value < 0:
        return "minus " + number_to_words(-value)
    if not float(value).is_integer():
        whole, frac = f"{value:.6f}".rstrip("0").split(".")
        return number_to_words(int(whole)) + " point " + " ".join(_ONES_WORDS[int(d)] for d in frac)
    n = int(value)
    if n >= 1_000_000 and n % 100_000 == 0 and n % 1_000_000:
        return number_to_words(n / 1_000_000) + " million"
    if n == 0:
        return "zero"
    chunks: list[str] = []
    for name, size in (("billion", 10**9), ("million", 10**6), ("thousand", 10**3)):
        if n >= size:
            chunks.append(f"{_below_thousand(n // size)} {name}")
            n %= size
    if n:
        chunks.append(_below_thousand(n))
    return " ".join(chunks)
