"""Templated adviser questions (42 in-scope types over 8 categories, 6 out-of-scope types that
appear in the topic-shift incident) and a seeded sampler over the client book."""

from __future__ import annotations

import random
import re
from collections.abc import Callable
from dataclasses import dataclass

from opsloop.demo.book import Client, ClientBook

Predicate = Callable[[Client], bool]


@dataclass(frozen=True, slots=True)
class QuestionType:
    name: str
    category: str
    text: str
    tools: tuple[str, ...]
    json_expected: bool = False
    in_scope: bool = True
    requires: Predicate | None = None

    def pattern(self) -> re.Pattern[str]:
        escaped = re.escape(self.text)
        escaped = escaped.replace(re.escape("{client}"), r"(?P<client>.+?)")
        escaped = escaped.replace(re.escape("{risk_profile}"), r"(?P<risk_profile>.+?)")
        return re.compile("^" + escaped + "$")


def _has_pension(c: Client) -> bool:
    return c.has("pension")


def _has_super(c: Client) -> bool:
    return c.has("super")


def _has_idps(c: Client) -> bool:
    return c.has("idps")


def _has_insurance(c: Client) -> bool:
    return c.insurance is not None


H = ("get_holdings",)
F = ("fee_schedule",)
C = ("contribution_room",)
I = ("insurance_cover",)  # noqa: E741 - short table aliases
R = ("review_schedule",)

QUESTION_TYPES: tuple[QuestionType, ...] = (
    # balances
    QuestionType("total_balance", "balances", "What is {client}'s total balance across all accounts?", H),
    QuestionType("super_balance", "balances", "What is the current balance of {client}'s super account?", H, requires=_has_super),
    QuestionType("pension_balance", "balances", "What is the balance in {client}'s account-based pension?", H, requires=_has_pension),
    QuestionType("idps_balance", "balances", "How much does {client} hold in the IDPS investment account?", H, requires=_has_idps),
    QuestionType("account_list", "balances", "Which accounts does {client} hold on the platform?", H),
    QuestionType("largest_account", "balances", "Which of {client}'s accounts has the largest balance?", H),
    QuestionType("balance_change", "balances", "How has {client}'s total balance moved over the last 12 months?", H),
    QuestionType("valuation_date", "balances", "When were {client}'s holdings last valued?", H),
    # allocation
    QuestionType("growth_defensive_split", "allocation", "What is {client}'s growth versus defensive split?", H),
    QuestionType("allocation_vs_profile", "allocation", "Is {client}'s asset allocation consistent with their {risk_profile} risk profile?", H),
    QuestionType("largest_holding", "allocation", "What is the largest holding in {client}'s portfolio?", H),
    QuestionType("top_holdings", "allocation", "List {client}'s top three holdings by value.", H),
    QuestionType("cash_weight", "allocation", "How much cash is {client} holding?", H),
    QuestionType("international_exposure", "allocation", "What is {client}'s international equities exposure?", H),
    QuestionType("allocation_json", "allocation", "Give me {client}'s asset allocation as JSON.", H, json_expected=True),
    # fees
    QuestionType("total_fees", "fees", "What are the total annual fees on {client}'s accounts?", F),
    QuestionType("admin_fee", "fees", "What is the platform administration fee for {client}?", F),
    QuestionType("investment_fee", "fees", "What are {client}'s investment management fees?", F),
    QuestionType("adviser_fee", "fees", "What ongoing adviser service fee is {client} paying?", F),
    QuestionType("fee_pct", "fees", "What are {client}'s total fees as a percentage of balance?", F),
    QuestionType("fds_summary", "fees", "Summarise the fees for {client}'s Fee Disclosure Statement.", F),
    QuestionType("fee_consent", "fees", "When does {client}'s ongoing fee consent expire?", F),
    QuestionType("fees_json", "fees", "Export {client}'s fee summary as JSON.", F, json_expected=True),
    # contributions
    QuestionType("concessional_room", "contributions", "How much concessional contribution room does {client} have this financial year?", C),
    QuestionType("non_concessional_room", "contributions", "What non-concessional contributions can {client} still make this year?", C),
    QuestionType("ytd_contributions", "contributions", "What has {client} contributed year to date?", C),
    QuestionType("carry_forward", "contributions", "Does {client} have unused carry-forward concessional cap available?", C),
    QuestionType("bring_forward", "contributions", "Is {client} eligible to trigger the bring-forward rule?", C),
    QuestionType("contribution_json", "contributions", "Give me {client}'s contribution position as JSON.", C, json_expected=True),
    # insurance
    QuestionType("life_cover", "insurance", "How much life cover does {client} hold inside super?", I, requires=_has_insurance),
    QuestionType("tpd_cover", "insurance", "What TPD cover does {client} have?", I, requires=_has_insurance),
    QuestionType("income_protection", "insurance", "What is {client}'s income protection benefit?", I, requires=_has_insurance),
    QuestionType("insurance_premium", "insurance", "What is {client} paying in insurance premiums each year?", I, requires=_has_insurance),
    QuestionType("insurance_summary", "insurance", "Summarise {client}'s insurance cover.", I),
    # reviews
    QuestionType("next_review", "reviews", "When is {client}'s next review due?", R),
    QuestionType("days_to_review", "reviews", "How many days until {client}'s next annual review?", R),
    QuestionType("last_review", "reviews", "When did we last complete a review for {client}?", R),
    QuestionType("review_overdue", "reviews", "Is {client}'s review overdue?", R),
    # pension
    QuestionType("min_drawdown", "pension", "What is the minimum pension drawdown for {client} this year?", H, requires=_has_pension),
    QuestionType("pension_payments", "pension", "What pension payments is {client} receiving and how often?", H, requires=_has_pension),
    # profile
    QuestionType("risk_profile", "profile", "What is {client}'s recorded risk profile?", H),
    QuestionType("preservation", "profile", "Has {client} reached preservation age?", C),
    # out of scope (appear in the topic-shift incident)
    QuestionType("age_pension_estimate", "out_of_scope", "What Centrelink Age Pension would {client} be entitled to?", (), in_scope=False),
    QuestionType("bdbn_status", "out_of_scope", "Does {client} have a binding death benefit nomination in place?", (), in_scope=False),
    QuestionType("cgt_estimate", "out_of_scope", "What capital gains tax would {client} pay if they sold the IDPS holdings?", (), in_scope=False),
    QuestionType("smsf_rollover", "out_of_scope", "Can {client} roll their super into an SMSF and what is involved?", (), in_scope=False),
    QuestionType("soa_draft", "out_of_scope", "Draft a Statement of Advice recommending a product switch for {client}.", (), in_scope=False),
    QuestionType("product_switch", "out_of_scope", "Should {client} switch from their current super fund to our managed portfolio?", (), in_scope=False),
)  # fmt: skip

BY_NAME: dict[str, QuestionType] = {q.name: q for q in QUESTION_TYPES}
CATEGORY_WEIGHTS: dict[str, float] = {
    "balances": 0.20,
    "allocation": 0.15,
    "fees": 0.18,
    "contributions": 0.14,
    "insurance": 0.10,
    "reviews": 0.13,
    "pension": 0.05,
    "profile": 0.05,
}
_PATTERNS: list[tuple[QuestionType, re.Pattern[str]]] = [(q, q.pattern()) for q in QUESTION_TYPES]


def classify(text: str) -> QuestionType | None:
    """Which template produced this question (what the fake model does instead of reading)."""
    stripped = text.strip()
    for q, pattern in _PATTERNS:
        if pattern.match(stripped):
            return q
    return None


@dataclass(frozen=True, slots=True)
class Question:
    type: QuestionType
    client_id: str
    text: str


class QuestionSampler:
    def __init__(self, book: ClientBook, rng: random.Random) -> None:
        self.book = book
        self.rng = rng
        self._in_scope = [q for q in QUESTION_TYPES if q.in_scope]
        self._out_of_scope = [q for q in QUESTION_TYPES if not q.in_scope]
        self._by_category: dict[str, list[QuestionType]] = {}
        for q in self._in_scope:
            self._by_category.setdefault(q.category, []).append(q)

    def sample(self, *, out_of_scope_share: float = 0.03, client: Client | None = None) -> Question:
        if self.rng.random() < out_of_scope_share:
            qt = self.rng.choice(self._out_of_scope)
            c = client or self.rng.choice(self.book.clients)
        else:
            category = self.rng.choices(
                list(CATEGORY_WEIGHTS), weights=list(CATEGORY_WEIGHTS.values()), k=1
            )[0]
            qt = self.rng.choice(self._by_category[category])
            c = client or self._pick_client(qt)
        return Question(qt, c.client_id, render_question(qt, c))

    def _pick_client(self, qt: QuestionType) -> Client:
        for _ in range(50):
            c = self.rng.choice(self.book.clients)
            if qt.requires is None or qt.requires(c):
                return c
        return next(c for c in self.book.clients if qt.requires is None or qt.requires(c))


def render_question(qt: QuestionType, client: Client) -> str:
    return qt.text.format(client=client.name, risk_profile=client.risk_profile)
