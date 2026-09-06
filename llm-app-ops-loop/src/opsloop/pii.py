"""PII detection and redaction with Australian checksums.

A TFN is nine digits with a weighted mod-11 check and an ABN eleven digits with a mod-89 check;
without the checksums every balance and account number is a false positive. Redaction replaces
matches with a typed marker (``[TFN]``) so downstream code can still *count* what was there.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any

TFN_WEIGHTS = (1, 4, 3, 7, 5, 8, 6, 9, 10)
ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)

_TFN = re.compile(r"(?<!\d)(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?!\d)")
_ABN = re.compile(r"(?<!\d)(\d{2})[ -]?(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?!\d)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<![\d)])(?:\+61[ -]?|\(0\)|0)[2-478](?:[ -]?\d){8}(?!\d)")

MARKERS = {"tfn": "[TFN]", "abn": "[ABN]", "email": "[EMAIL]", "phone": "[PHONE]"}


def tfn_valid(digits: str) -> bool:
    d = re.sub(r"\D", "", digits)
    if len(d) != 9:
        return False
    return sum(int(c) * w for c, w in zip(d, TFN_WEIGHTS, strict=True)) % 11 == 0


def abn_valid(digits: str) -> bool:
    d = re.sub(r"\D", "", digits)
    if len(d) != 11:
        return False
    first = int(d[0]) - 1
    total = first * ABN_WEIGHTS[0] + sum(
        int(c) * w for c, w in zip(d[1:], ABN_WEIGHTS[1:], strict=True)
    )
    return total % 89 == 0


def generate_tfn(rng: random.Random) -> str:
    """A random *valid* TFN (fictional: the check digit is what makes it look real)."""
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(9))
        if tfn_valid(digits):
            return f"{digits[:3]} {digits[3:6]} {digits[6:]}"


def generate_abn(rng: random.Random) -> str:
    while True:
        digits = "".join(str(rng.randint(0, 9)) for _ in range(11))
        if digits[0] != "0" and abn_valid(digits):
            return f"{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:]}"


@dataclass(frozen=True, slots=True)
class PIIMatch:
    kind: str
    start: int
    end: int
    text: str


def find_pii(text: str) -> list[PIIMatch]:
    found: list[PIIMatch] = []
    for m in _EMAIL.finditer(text):
        found.append(PIIMatch("email", m.start(), m.end(), m.group(0)))
    for m in _ABN.finditer(text):
        if abn_valid(m.group(0)):
            found.append(PIIMatch("abn", m.start(), m.end(), m.group(0)))
    for m in _TFN.finditer(text):
        if tfn_valid(m.group(0)) and not any(
            f.start <= m.start() < f.end for f in found if f.kind == "abn"
        ):
            found.append(PIIMatch("tfn", m.start(), m.end(), m.group(0)))
    for m in _PHONE.finditer(text):
        if not any(f.start <= m.start() < f.end for f in found):
            found.append(PIIMatch("phone", m.start(), m.end(), m.group(0)))
    return sorted(found, key=lambda f: f.start)


def redact_text(text: str) -> tuple[str, dict[str, int]]:
    """Replace every match with its marker; returns the new text and counts per kind."""
    matches = find_pii(text)
    counts: dict[str, int] = {}
    if not matches:
        return text, counts
    out: list[str] = []
    cursor = 0
    for m in matches:
        if m.start < cursor:
            continue
        out.append(text[cursor : m.start])
        out.append(MARKERS[m.kind])
        counts[m.kind] = counts.get(m.kind, 0) + 1
        cursor = m.end
    out.append(text[cursor:])
    return "".join(out), counts


def redact_value(value: Any, counts: dict[str, int] | None = None) -> Any:
    """Recursively redact strings inside dicts / lists / tuples (attribute payloads)."""
    counts = counts if counts is not None else {}
    if isinstance(value, str):
        new, c = redact_text(value)
        for k, v in c.items():
            counts[k] = counts.get(k, 0) + v
        return new
    if isinstance(value, dict):
        return {k: redact_value(v, counts) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [redact_value(v, counts) for v in value]
    return value


def contains_marker(text: str) -> bool:
    return any(marker in text for marker in MARKERS.values())
