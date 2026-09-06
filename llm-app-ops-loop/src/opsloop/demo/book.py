"""A seeded synthetic client book for the fictional Northshore Wealth platform. Every name,
identifier, TFN and product is generated; the same seed gives the same book."""

from __future__ import annotations

import random
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from opsloop.pii import generate_tfn

AccountType = Literal["super", "pension", "idps", "managed_portfolio"]

FIRST_NAMES = [
    "Amelia", "Benjamin", "Charlotte", "Daniel", "Eleanor", "Finn", "Grace", "Harrison",
    "Isla", "Jack", "Kiara", "Liam", "Mei", "Noah", "Olivia", "Patrick", "Quinn", "Ruby",
    "Samuel", "Tahlia", "Uma", "Vincent", "Willow", "Xavier", "Yasmin", "Zachary", "Aroha",
    "Bao", "Cormac", "Dilnoza", "Esperanza", "Fatima", "Giulia", "Hamish", "Ines", "Jorge",
]  # fmt: skip
LAST_NAMES = [
    "Abbott", "Barlow", "Cavanagh", "Delacroix", "Eriksen", "Fairweather", "Goldsmith",
    "Hartigan", "Ivanova", "Jephson", "Kowalski", "Lindqvist", "Marchetti", "Nakamura",
    "Okonkwo", "Papadopoulos", "Quilty", "Rasmussen", "Stavros", "Thorne", "Underwood",
    "Vasquez", "Whitlam", "Xu", "Yilmaz", "Zielinski", "Nguyen", "Fitzgerald", "Mbeki", "Ostrowski",
]  # fmt: skip
ADVISERS = [
    ("A01", "Priya Raman"), ("A02", "Tom Halloran"), ("A03", "Lucy Bennett"),
    ("A04", "Marcus Oduya"), ("A05", "Hannah Kirsch"), ("A06", "Wei Zhang"),
    ("A07", "Callum Reid"), ("A08", "Sofia Marin"),
]  # fmt: skip

RISK_PROFILES: dict[str, tuple[float, float]] = {
    "Conservative": (20.0, 35.0),
    "Moderately Conservative": (35.0, 50.0),
    "Balanced": (50.0, 70.0),
    "Growth": (70.0, 85.0),
    "High Growth": (85.0, 100.0),
}
RISK_WEIGHTS = [0.10, 0.20, 0.40, 0.22, 0.08]

GROWTH_CLASSES = [
    "Australian equities",
    "International equities",
    "Property and infrastructure",
    "Alternatives",
]
DEFENSIVE_CLASSES = ["Australian fixed interest", "International fixed interest", "Cash"]
HOLDINGS: dict[str, list[str]] = {
    "Australian equities": [
        "Northshore Australian Shares Index",
        "Southern Cross Active Australian Equities",
        "Harbour Small Companies",
    ],
    "International equities": [
        "Northshore Global Shares Index (hedged)",
        "Meridian Global Quality Equities",
        "Pacific Emerging Markets",
    ],
    "Property and infrastructure": [
        "Northshore Listed Property",
        "Coastline Global Infrastructure",
    ],
    "Alternatives": ["Ridgeline Diversified Alternatives"],
    "Australian fixed interest": ["Northshore Australian Bond Index", "Tidewater Credit Income"],
    "International fixed interest": ["Northshore Global Bond Index (hedged)"],
    "Cash": ["Northshore Cash Account"],
}
PRODUCTS: dict[AccountType, list[str]] = {
    "super": ["Northshore Super Wrap", "Northshore Super Essentials"],
    "pension": ["Northshore Account-Based Pension"],
    "idps": ["Northshore Investment Wrap (IDPS)"],
    "managed_portfolio": [
        "Northshore Managed Portfolio - Balanced",
        "Northshore Managed Portfolio - Growth",
    ],
}

# Illustrative caps and ages for the demo year (not tax advice).
CONCESSIONAL_CAP = 30_000.0
NON_CONCESSIONAL_CAP = 120_000.0
BRING_FORWARD_CAP = 360_000.0
TOTAL_SUPER_BALANCE_LIMIT = 2_000_000.0
PRESERVATION_AGE = 60


class Holding(BaseModel):
    name: str
    asset_class: str
    weight: float
    value: float


class Account(BaseModel):
    account_id: str
    type: AccountType
    product: str
    balance: float
    holdings: list[Holding]
    admin_fee_pct: float
    investment_fee_pct: float
    adviser_fee_pct: float
    as_of: str
    usi: str | None = None


class Insurance(BaseModel):
    life_cover: float
    tpd_cover: float
    income_protection_monthly: float
    waiting_period_days: int
    benefit_period: str
    annual_premium: float
    premium_funded_from: Literal["super", "cash"]


class Contributions(BaseModel):
    concessional_ytd: float
    non_concessional_ytd: float
    carry_forward_unused: float


class Client(BaseModel):
    client_id: str
    name: str
    adviser_id: str
    adviser_name: str
    age: int
    risk_profile: str
    accounts: list[Account]
    insurance: Insurance | None
    contributions: Contributions
    last_review: str
    next_review: str
    review_frequency_months: int
    fee_consent_expiry: str
    stale_valuation: bool
    balance_change_12m_pct: float
    tfn: str
    email: str
    phone: str

    @property
    def total_balance(self) -> float:
        return round(sum(a.balance for a in self.accounts), 2)

    def has(self, account_type: AccountType) -> bool:
        return any(a.type == account_type for a in self.accounts)


class ClientBook(BaseModel):
    seed: int
    today: str
    clients: list[Client] = Field(default_factory=list)

    def get(self, client_id: str) -> Client:
        for c in self.clients:
            if c.client_id == client_id:
                return c
        msg = f"unknown client {client_id}"
        raise KeyError(msg)

    @classmethod
    def generate(
        cls, *, seed: int = 7, n_clients: int = 200, today: str = "2026-09-01"
    ) -> ClientBook:
        rng = random.Random(f"book:{seed}")
        today_d = date.fromisoformat(today)
        clients = [_make_client(rng, i, today_d) for i in range(n_clients)]
        return cls(seed=seed, today=today, clients=clients)


def _money(rng: random.Random, median: float, sigma: float) -> float:
    return round(rng.lognormvariate(0.0, sigma) * median, 2)


def _holdings(rng: random.Random, balance: float, growth_pct: float) -> list[Holding]:
    n_growth = rng.randint(2, 3)
    n_def = rng.randint(1, 2)
    growth_classes = rng.sample(GROWTH_CLASSES, n_growth)
    def_classes = rng.sample(DEFENSIVE_CLASSES, n_def)
    g_w = [rng.random() + 0.3 for _ in growth_classes]
    d_w = [rng.random() + 0.3 for _ in def_classes]
    g_total, d_total = sum(g_w), sum(d_w)
    weights: list[tuple[str, str, float]] = []
    for cls_name, w in zip(growth_classes, g_w, strict=True):
        weights.append((rng.choice(HOLDINGS[cls_name]), cls_name, growth_pct / 100.0 * w / g_total))
    for cls_name, w in zip(def_classes, d_w, strict=True):
        weights.append(
            (rng.choice(HOLDINGS[cls_name]), cls_name, (1.0 - growth_pct / 100.0) * w / d_total)
        )
    rounded = [round(w, 4) for _, _, w in weights]
    rounded[-1] = round(1.0 - sum(rounded[:-1]), 4)
    return [
        Holding(name=name, asset_class=cls_name, weight=w, value=round(balance * w, 2))
        for (name, cls_name, _), w in zip(weights, rounded, strict=True)
    ]


def _make_account(
    rng: random.Random, client_idx: int, k: int, kind: AccountType, growth_pct: float, as_of: date
) -> Account:
    medians = {
        "super": 320_000.0,
        "pension": 540_000.0,
        "idps": 210_000.0,
        "managed_portfolio": 150_000.0,
    }
    balance = _money(rng, medians[kind], 0.55)
    return Account(
        account_id=f"NS{kind[:2].upper()}{client_idx:04d}{k}",
        type=kind,
        product=rng.choice(PRODUCTS[kind]),
        balance=balance,
        holdings=_holdings(rng, balance, growth_pct),
        admin_fee_pct=round(rng.uniform(0.15, 0.35), 2),
        investment_fee_pct=round(rng.uniform(0.25, 0.85), 2),
        adviser_fee_pct=round(rng.uniform(0.50, 1.10), 2),
        as_of=as_of.isoformat(),
        usi=f"NSW{rng.randint(1000, 9999)}AU" if kind in ("super", "pension") else None,
    )


def _make_client(rng: random.Random, i: int, today: date) -> Client:
    first, last = rng.choice(FIRST_NAMES), rng.choice(LAST_NAMES)
    adviser_id, adviser_name = ADVISERS[i % len(ADVISERS)]
    age = rng.randint(28, 78)
    profile = rng.choices(list(RISK_PROFILES), weights=RISK_WEIGHTS, k=1)[0]
    lo, hi = RISK_PROFILES[profile]
    if rng.random() < 0.22:  # a fifth of clients sit outside their target range
        growth = (
            round(rng.uniform(hi + 3.0, min(hi + 15.0, 100.0)), 1)
            if rng.random() < 0.6
            else round(max(lo - 12.0, 0.0), 1)
        )
    else:
        growth = round(rng.uniform(lo + 1.0, hi - 1.0), 1)
    stale = rng.random() < 0.15
    as_of = today - timedelta(days=rng.randint(35, 90) if stale else rng.randint(2, 25))
    kinds: list[AccountType] = []
    if age >= 65 and rng.random() < 0.6:
        kinds.append("pension")
    else:
        kinds.append("super")
    if rng.random() < 0.4:
        kinds.append("idps")
    if rng.random() < 0.25:
        kinds.append("managed_portfolio")
    accounts = [_make_account(rng, i, k, kind, growth, as_of) for k, kind in enumerate(kinds)]
    insurance: Insurance | None = None
    if "super" in kinds and age < 65 and rng.random() < 0.7:
        insurance = Insurance(
            life_cover=float(rng.choice([250_000, 500_000, 750_000, 1_000_000, 1_500_000])),
            tpd_cover=float(rng.choice([0, 250_000, 500_000, 750_000])),
            income_protection_monthly=float(rng.choice([0, 4_000, 6_500, 8_000, 12_000])),
            waiting_period_days=rng.choice([30, 60, 90]),
            benefit_period=rng.choice(["2 years", "5 years", "to age 65"]),
            annual_premium=round(rng.uniform(900, 6_500), 2),
            premium_funded_from=rng.choice(["super", "cash"]),
        )
    total = sum(a.balance for a in accounts)
    contributions = Contributions(
        concessional_ytd=round(rng.uniform(0, CONCESSIONAL_CAP * 0.9), 2),
        non_concessional_ytd=round(rng.choice([0.0, 0.0, 0.0, 25_000.0, 60_000.0]), 2),
        carry_forward_unused=round(rng.uniform(0, 45_000), 2) if total < 500_000 else 0.0,
    )
    last_review = today - timedelta(days=rng.randint(30, 400))
    next_review = last_review + timedelta(days=365)
    return Client(
        client_id=f"C{i + 1:04d}",
        name=f"{first} {last}",
        adviser_id=adviser_id,
        adviser_name=adviser_name,
        age=age,
        risk_profile=profile,
        accounts=accounts,
        insurance=insurance,
        contributions=contributions,
        last_review=last_review.isoformat(),
        next_review=next_review.isoformat(),
        review_frequency_months=12,
        fee_consent_expiry=(last_review + timedelta(days=rng.randint(300, 420))).isoformat(),
        stale_valuation=stale,
        balance_change_12m_pct=round(rng.gauss(6.0, 8.0), 2),
        tfn=generate_tfn(rng),
        email=f"{first.lower()}.{last.lower()}{i}@example.com",
        phone=f"04{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
    )
