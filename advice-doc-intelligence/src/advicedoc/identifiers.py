"""Australian business / tax identifiers: ABN (11 digits, weighted mod-89) and TFN (9 digits,
weighted mod-11). Used to *generate* valid fictional ABNs for the corpus and to *detect*
TFN-shaped numbers in extracted text (a privacy check) without flagging every 9-digit
account number — the checksum is what keeps the false-positive rate down.
"""

from __future__ import annotations

import random
import re

ABN_WEIGHTS: tuple[int, ...] = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)
TFN_WEIGHTS: tuple[int, ...] = (1, 4, 3, 7, 5, 8, 6, 9, 10)

_ABN_SHAPED = re.compile(r"(?<![\d-])(\d{2})[ -]?(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?![\d-])")
_TFN_SHAPED = re.compile(r"(?<![\d-])(\d{3})[ -]?(\d{3})[ -]?(\d{3})(?![\d-])")


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def abn_is_valid(abn: str) -> bool:
    digits = _digits(abn)
    if len(digits) != 11 or digits[0] == "0":
        return False
    values = [int(digits[0]) - 1, *(int(d) for d in digits[1:])]
    return sum(w * v for w, v in zip(ABN_WEIGHTS, values, strict=True)) % 89 == 0


def format_abn(digits: str) -> str:
    d = _digits(digits)
    return f"{d[0:2]} {d[2:5]} {d[5:8]} {d[8:11]}"


def generate_abn(rng: random.Random) -> str:
    """A random ABN that passes the checksum, formatted ``12 345 678 901``."""
    while True:
        tail = [rng.randint(0, 9) for _ in range(10)]
        rest = sum(w * v for w, v in zip(ABN_WEIGHTS[1:], tail, strict=True))
        # 10 * (d0 - 1) + rest = 0 (mod 89); inverse of 10 mod 89 is 9.
        d0 = (-rest * 9) % 89 + 1
        if 1 <= d0 <= 9:
            return format_abn(str(d0) + "".join(str(v) for v in tail))


def tfn_is_valid(tfn: str) -> bool:
    digits = _digits(tfn)
    if len(digits) != 9:
        return False
    return sum(w * int(d) for w, d in zip(TFN_WEIGHTS, digits, strict=True)) % 11 == 0


def generate_tfn(rng: random.Random) -> str:
    """A random TFN that passes the checksum (tests only; never written into the corpus)."""
    while True:
        head = [rng.randint(0, 9) for _ in range(8)]
        rest = sum(w * v for w, v in zip(TFN_WEIGHTS[:8], head, strict=True))
        # rest + 10 * d8 = 0 (mod 11); inverse of 10 mod 11 is 10.
        d8 = (-rest * 10) % 11
        if d8 <= 9:
            digits = "".join(str(v) for v in [*head, d8])
            return f"{digits[0:3]} {digits[3:6]} {digits[6:9]}"


def find_tfn_like(text: str) -> list[str]:
    """Nine-digit groups in ``text`` that pass the TFN checksum. ABN-shaped spans are masked
    first: the last nine digits of an ABN pass the TFN checksum one time in eleven."""
    masked = _ABN_SHAPED.sub(lambda m: " " * len(m.group(0)), text)
    found: list[str] = []
    for m in _TFN_SHAPED.finditer(masked):
        candidate = "".join(m.groups())
        if tfn_is_valid(candidate):
            found.append(m.group(0))
    return found


def find_abn_like(text: str) -> list[str]:
    """Eleven-digit groups in ``text`` in ABN layout (valid or not)."""
    return [m.group(0) for m in _ABN_SHAPED.finditer(text)]
