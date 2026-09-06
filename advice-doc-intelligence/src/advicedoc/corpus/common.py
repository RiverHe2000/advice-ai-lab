"""Seeded helpers shared by the document templates: people, addresses, dates, amounts."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from advicedoc.corpus import names as N
from advicedoc.corpus.layout import Para, Style
from advicedoc.schema import ProductType

DATE_START = date(2025, 1, 15)
DATE_END = date(2026, 8, 30)

PRODUCT_TYPE_LABELS: dict[ProductType, str] = {
    "super": "Superannuation",
    "pension": "Account-based pension",
    "idps": "Investment (IDPS)",
    "managed_portfolio": "Managed portfolio",
    "insurance": "Insurance",
    "cash": "Cash",
}


@dataclass(frozen=True, slots=True)
class Person:
    first: str
    surname: str
    age: int
    occupation: str
    employer: str
    income: Decimal

    @property
    def full(self) -> str:
        return f"{self.first} {self.surname}"


@dataclass(frozen=True, slots=True)
class Address:
    street: str
    suburb: str
    state: str
    postcode: str

    @property
    def lines(self) -> tuple[str, str]:
        return (self.street, f"{self.suburb} {self.state} {self.postcode}")


def doc_rng(seed: int, doc_id: str) -> random.Random:
    """One generator per document, so adding documents never changes existing ones."""
    return random.Random(f"{seed}:{doc_id}")


def random_date(rng: random.Random, start: date = DATE_START, end: date = DATE_END) -> date:
    return start + timedelta(days=rng.randint(0, (end - start).days))


def money(rng: random.Random, low: int, high: int, step: int = 100) -> Decimal:
    return Decimal(rng.randrange(low, high + 1, step))


def person(rng: random.Random, *, surname: str | None = None, min_age: int = 27) -> Person:
    age = rng.randint(min_age, 72)
    occupation = "retired" if age >= 66 and rng.random() < 0.7 else rng.choice(N.OCCUPATIONS)
    income = (
        money(rng, 30_000, 210_000, 1_000)
        if occupation != "retired"
        else money(rng, 0, 40_000, 1_000)
    )
    return Person(
        first=rng.choice(N.FIRST_NAMES),
        surname=surname or rng.choice(N.SURNAMES),
        age=age,
        occupation=occupation,
        employer=rng.choice(N.EMPLOYERS),
        income=income,
    )


def clients(rng: random.Random, *, p_couple: float = 0.4) -> list[Person]:
    first = person(rng)
    if rng.random() >= p_couple:
        return [first]
    shared = rng.random() < 0.7
    partner = person(rng, surname=first.surname if shared else None, min_age=max(27, first.age - 8))
    while partner.first == first.first:
        partner = person(rng, surname=partner.surname, min_age=max(27, first.age - 8))
    return [first, partner]


def address(rng: random.Random) -> Address:
    suburb, state, postcode = rng.choice(N.SUBURBS)
    return Address(f"{rng.randint(1, 240)} {rng.choice(N.STREETS)}", suburb, state, postcode)


def account_ref(rng: random.Random, prefix: str = "") -> str:
    # Eight digits in two groups: never nine digits, so nothing is TFN-shaped.
    return f"{prefix}{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}"


def join_names(names: list[str]) -> str:
    return " and ".join(names)


def filler(rng: random.Random, n: int, style: Style) -> list[Para]:
    sentences = list(N.DISCLOSURE_SENTENCES)
    rng.shuffle(sentences)
    per_para = max(1, n // max(1, style.filler_paragraphs))
    paras: list[Para] = []
    for i in range(style.filler_paragraphs):
        chunk = sentences[i * per_para : (i + 1) * per_para]
        if chunk:
            paras.append(Para(" ".join(chunk)))
    return paras
