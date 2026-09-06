"""The fake tool-using model behind the demo.

It is a caricature of a real model that is *honest about how it is driven*: the answer is a
deterministic function of (system prompt, question, tool results). It obeys a handful of
directives it finds in the system prompt — "quote figures exactly", "round figures",
"under N words", "cannot answer" on stale data, "percentage points", "date and days remaining
only", "offer to help" — so a prompt change changes behaviour the way it would with a real
model, and trace replay reproduces a recorded answer exactly. ``Corruption`` adds seeded
failure modes (ungrounded numbers, refusals, invalid JSON, verbosity) for failure injection
and for exercising evaluation code paths on wrong outputs.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from opsloop.demo.questions import QuestionType, classify
from opsloop.jsonrepair import repair_json
from opsloop.llm import ChatMessage, ChatResponse, estimate_tokens

MODEL_NAME = "northshore-assistant-4b"
CLOSER = " Let me know if you would like the full breakdown."
OUT_OF_SCOPE = (
    "I can only help with questions about {client}'s platform holdings, fees, contributions, "
    "insurance and reviews. This question is outside what I can answer from the platform data, "
    "so please use your own tools for it."
)
STALE_REFUSAL = (
    "I cannot answer this for {client}: the valuation on file is stale, so the figures may be "
    "incomplete. Please refresh the valuation and ask again."
)
FILLER = (
    "As always, these figures come directly from the platform records and should be read "
    "alongside the client's current fact-find and any recent instructions.",
    "If anything looks inconsistent with the client's file, the platform data is the source of "
    "truth for balances and fees, while insurance and contribution details depend on the fund.",
    "Please treat this as factual information for the adviser rather than a recommendation, and "
    "confirm any figure before it goes into client-facing correspondence.",
    "For completeness, the valuation date shown reflects the most recent unit pricing applied to "
    "the client's holdings, and intraday market movements are not included.",
    "Should the client's circumstances have changed since the last review, it may be worth "
    "revisiting the fact-find so that the platform data and the advice record stay aligned.",
    "You can ask me for any of the underlying account-level figures, and I will return them "
    "exactly as the platform reports them.",
)
_FENCE = re.compile(r"```json\s*(.*?)```", flags=re.DOTALL)
_QUESTION = re.compile(r"^Question:\s*(.+?)\s*$", flags=re.MULTILINE)
_WORD_CAP = re.compile(r"under (\d+) words", flags=re.IGNORECASE)
_MONEY = re.compile(r"\$(\d[\d,]*)(?:\.(\d+))?")
_PCT = re.compile(r"(\d+)\.(\d+)\s?%")


@dataclass(frozen=True, slots=True)
class Directives:
    exact_figures: bool = False
    round_figures: bool = False
    word_cap: int | None = None
    decline_stale: bool = False
    deviation_points: bool = False
    terse_reviews: bool = False
    offer_help: bool = False

    @classmethod
    def from_system_prompt(cls, text: str) -> Directives:
        lowered = text.lower()
        cap = _WORD_CAP.search(text)
        return cls(
            exact_figures="quote figures exactly" in lowered,
            round_figures="round figures" in lowered,
            word_cap=int(cap.group(1)) if cap else None,
            decline_stale="stale" in lowered and "cannot answer" in lowered,
            deviation_points="percentage points" in lowered,
            terse_reviews="date and days remaining only" in lowered,
            offer_help="offer to help" in lowered,
        )


@dataclass
class Corruption:
    ungrounded_rate: float = 0.0
    refusal_rate: float = 0.0
    invalid_json_rate: float = 0.0
    verbosity: float = 1.0

    def active(self) -> bool:
        return (
            self.ungrounded_rate > 0
            or self.refusal_rate > 0
            or self.invalid_json_rate > 0
            or self.verbosity != 1.0
        )


@dataclass(slots=True)
class AnswerContext:
    qt: QuestionType
    client: str
    tools: dict[str, Any]
    directives: Directives

    @property
    def h(self) -> dict[str, Any]:
        return dict(self.tools.get("get_holdings") or {})

    @property
    def f(self) -> dict[str, Any]:
        return dict(self.tools.get("fee_schedule") or {})

    @property
    def c(self) -> dict[str, Any]:
        return dict(self.tools.get("contribution_room") or {})

    @property
    def i(self) -> dict[str, Any]:
        return dict(self.tools.get("insurance_cover") or {})

    @property
    def r(self) -> dict[str, Any]:
        return dict(self.tools.get("review_schedule") or {})


def money(v: Any) -> str:
    return f"${float(v):,.2f}"


def pct(v: Any) -> str:
    return f"{float(v):.2f}%"


def _acct(h: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for a in h.get("accounts", []):
        if a.get("type") == kind:
            return dict(a)
    return None


def _fee_pct_phrase(ctx: AnswerContext) -> str:
    # v1's defect: without "quote figures exactly" the model rounds the fee percentage.
    value = float(ctx.f.get("fee_pct_of_balance", 0.0))
    if ctx.directives.exact_figures:
        return pct(value)
    return f"about {value:.1f}%"


def _balances(ctx: AnswerContext) -> str:
    h = ctx.h
    parts = ", ".join(f"{a['type']} {a['account_id']} {money(a['balance'])}" for a in h["accounts"])
    return (
        f"{ctx.client}'s total balance is {money(h['total_balance'])} across "
        f"{h['n_accounts']} accounts ({parts}), valued as of {h['as_of']}."
    )


def _super_balance(ctx: AnswerContext) -> str:
    a = _acct(ctx.h, "super")
    if a is None:
        return f"{ctx.client} does not hold a super account on the platform."
    return f"{ctx.client}'s super account {a['account_id']} ({a['product']}) has a balance of {money(a['balance'])} as of {ctx.h['as_of']}."


def _pension_balance(ctx: AnswerContext) -> str:
    a = _acct(ctx.h, "pension")
    if a is None:
        return f"{ctx.client} does not hold an account-based pension on the platform."
    return f"{ctx.client}'s account-based pension {a['account_id']} has a balance of {money(a['balance'])} as of {ctx.h['as_of']}."


def _idps_balance(ctx: AnswerContext) -> str:
    a = _acct(ctx.h, "idps")
    if a is None:
        return f"{ctx.client} does not hold an IDPS investment account on the platform."
    return f"{ctx.client} holds {money(a['balance'])} in the IDPS investment account {a['account_id']} as of {ctx.h['as_of']}."


def _account_list(ctx: AnswerContext) -> str:
    rows = "; ".join(
        f"{a['product']} ({a['type']}, {a['account_id']}, {money(a['balance'])})"
        for a in ctx.h["accounts"]
    )
    return f"{ctx.client} holds {ctx.h['n_accounts']} accounts on the platform: {rows}."


def _largest_account(ctx: AnswerContext) -> str:
    la = ctx.h["largest_account"]
    return f"{ctx.client}'s largest account is the {la['type']} account {la['account_id']} with a balance of {money(la['balance'])}."


def _balance_change(ctx: AnswerContext) -> str:
    return f"{ctx.client}'s total balance moved by {pct(ctx.h['balance_change_12m_pct'])} over the last 12 months to {money(ctx.h['total_balance'])} (valued {ctx.h['as_of']})."


def _valuation_date(ctx: AnswerContext) -> str:
    stale = (
        f" The valuation is {ctx.h['valuation_age_days']} days old, past the "
        f"{ctx.h['stale_after_days']}-day freshness rule."
        if ctx.h.get("stale")
        else ""
    )
    return f"{ctx.client}'s holdings were last valued on {ctx.h['as_of']}.{stale}"


def _split(ctx: AnswerContext) -> str:
    return f"{ctx.client}'s portfolio is {pct(ctx.h['growth_pct'])} growth and {pct(ctx.h['defensive_pct'])} defensive assets as of {ctx.h['as_of']}."


def _allocation_vs_profile(ctx: AnswerContext) -> str:
    h = ctx.h
    lo, hi = h["target_growth_range"]
    base = f"{ctx.client}'s growth allocation is {pct(h['growth_pct'])} against a {h['risk_profile']} target range of {pct(lo)} to {pct(hi)}."
    if h["within_range"]:
        return base + " The allocation is within the target range."
    if ctx.directives.deviation_points:
        return (
            base + f" It sits {pct(h['deviation_magnitude'])[:-1]} percentage points "
            f"{h['deviation_direction']} the range."
        )
    return base + " The allocation is outside the target range."


def _largest_holding(ctx: AnswerContext) -> str:
    lh = ctx.h["largest_holding"]
    return f"{ctx.client}'s largest holding is {lh['name']} ({lh['asset_class']}) at {pct(lh['weight_pct'])} of the portfolio, worth {money(lh['value'])}."


def _top_holdings(ctx: AnswerContext) -> str:
    rows = "; ".join(
        f"{t['name']} {money(t['value'])} ({pct(t['weight_pct'])})" for t in ctx.h["top_holdings"]
    )
    return f"{ctx.client}'s top holdings by value are: {rows}."


def _cash_weight(ctx: AnswerContext) -> str:
    return f"{ctx.client} holds {money(ctx.h['cash_value'])} in cash, which is {pct(ctx.h['cash_pct'])} of the portfolio."


def _international(ctx: AnswerContext) -> str:
    return f"{ctx.client}'s international equities exposure is {pct(ctx.h['international_equities_pct'])} of the portfolio ({money(ctx.h['international_equities_value'])})."


def _allocation_json(ctx: AnswerContext) -> str:
    h = ctx.h
    return json.dumps(
        {
            "client_id": h["client_id"],
            "as_of": h["as_of"],
            "growth_pct": h["growth_pct"],
            "defensive_pct": h["defensive_pct"],
            "target_growth_range": h["target_growth_range"],
            "within_range": h["within_range"],
            "holdings": [
                {
                    "name": t["name"],
                    "asset_class": t["asset_class"],
                    "weight_pct": t["weight_pct"],
                    "value": t["value"],
                }
                for t in h["top_holdings"]
            ],
        }
    )


def _total_fees(ctx: AnswerContext) -> str:
    f = ctx.f
    return f"{ctx.client}'s total annual fees are {money(f['total_annual_fee'])} ({_fee_pct_phrase(ctx)} of the {money(f['total_balance'])} balance): administration {money(f['total_admin_fee'])}, investment {money(f['total_investment_fee'])}, adviser service {money(f['total_adviser_fee'])}."


def _admin_fee(ctx: AnswerContext) -> str:
    rows = "; ".join(
        f"{a['account_id']} {pct(a['admin_fee_pct'])} = {money(a['admin_fee'])}"
        for a in ctx.f["accounts"]
    )
    return f"The platform administration fee for {ctx.client} totals {money(ctx.f['total_admin_fee'])} a year: {rows}."


def _investment_fee(ctx: AnswerContext) -> str:
    rows = "; ".join(
        f"{a['account_id']} {pct(a['investment_fee_pct'])} = {money(a['investment_fee'])}"
        for a in ctx.f["accounts"]
    )
    return f"{ctx.client}'s investment management fees total {money(ctx.f['total_investment_fee'])} a year: {rows}."


def _adviser_fee(ctx: AnswerContext) -> str:
    rows = "; ".join(
        f"{a['account_id']} {pct(a['adviser_fee_pct'])} = {money(a['adviser_fee'])}"
        for a in ctx.f["accounts"]
    )
    return f"{ctx.client} pays an ongoing adviser service fee of {money(ctx.f['total_adviser_fee'])} a year: {rows}."


def _fee_pct(ctx: AnswerContext) -> str:
    return f"{ctx.client}'s total fees are {_fee_pct_phrase(ctx)} of the balance: {money(ctx.f['total_annual_fee'])} on {money(ctx.f['total_balance'])}."


def _fds_summary(ctx: AnswerContext) -> str:
    f = ctx.f
    return f"Fee Disclosure Statement summary for {ctx.client}, period {f['fds_period']}: adviser service fee {money(f['total_adviser_fee'])}, platform administration {money(f['total_admin_fee'])}, investment fees {money(f['total_investment_fee'])}, total {money(f['total_annual_fee'])} ({_fee_pct_phrase(ctx)} of balance). Ongoing fee consent expires {f['fee_consent_expiry']}."


def _fee_consent(ctx: AnswerContext) -> str:
    f = ctx.f
    return f"{ctx.client}'s ongoing fee consent expires on {f['fee_consent_expiry']}, {f['fee_consent_days_remaining']} days from today."


def _fees_json(ctx: AnswerContext) -> str:
    f = ctx.f
    return json.dumps(
        {
            "client_id": f["client_id"],
            "period": f["fds_period"],
            "adviser_fee": f["total_adviser_fee"],
            "admin_fee": f["total_admin_fee"],
            "investment_fee": f["total_investment_fee"],
            "total_fee": f["total_annual_fee"],
            "fee_pct_of_balance": f["fee_pct_of_balance"],
            "consent_expiry": f["fee_consent_expiry"],
        }
    )


def _concessional(ctx: AnswerContext) -> str:
    c = ctx.c
    return f"{ctx.client} has {money(c['concessional_room'])} of concessional contribution room left in {c['financial_year']}: {money(c['concessional_ytd'])} contributed against the {money(c['concessional_cap'])} cap."


def _non_concessional(ctx: AnswerContext) -> str:
    c = ctx.c
    return f"{ctx.client} can still make {money(c['non_concessional_room'])} of non-concessional contributions this year ({money(c['non_concessional_ytd'])} used of the {money(c['non_concessional_cap'])} cap)."


def _ytd(ctx: AnswerContext) -> str:
    c = ctx.c
    return f"Year to date {ctx.client} has contributed {money(c['concessional_ytd'])} concessional and {money(c['non_concessional_ytd'])} non-concessional."


def _carry_forward(ctx: AnswerContext) -> str:
    c = ctx.c
    if c["carry_forward_available"]:
        return f"Yes. {ctx.client} has {money(c['carry_forward_unused'])} of unused carry-forward concessional cap, and the total super balance of {money(c['total_super_balance'])} is under the {money(c['carry_forward_balance_limit'])} threshold."
    return f"No. {ctx.client}'s unused carry-forward amount is {money(c['carry_forward_unused'])} and the total super balance is {money(c['total_super_balance'])}, so carry-forward is not available."


def _bring_forward(ctx: AnswerContext) -> str:
    c = ctx.c
    if c["bring_forward_eligible"]:
        return f"Yes. At age {c['age']} with a total super balance of {money(c['total_super_balance'])}, {ctx.client} can trigger the bring-forward rule up to {money(c['bring_forward_cap'])}."
    return f"No. At age {c['age']} with a total super balance of {money(c['total_super_balance'])}, {ctx.client} is not eligible for the bring-forward rule."


def _contribution_json(ctx: AnswerContext) -> str:
    c = ctx.c
    keys = (
        "financial_year",
        "concessional_cap",
        "concessional_ytd",
        "concessional_room",
        "non_concessional_cap",
        "non_concessional_ytd",
        "non_concessional_room",
        "carry_forward_unused",
        "bring_forward_eligible",
    )
    return json.dumps({"client_id": c["client_id"], **{k: c[k] for k in keys}})


def _life(ctx: AnswerContext) -> str:
    i = ctx.i
    if not i.get("has_cover"):
        return f"{ctx.client} has no insurance cover recorded on the platform."
    return f"{ctx.client} holds {money(i['life_cover'])} of life cover inside super, with premiums of {money(i['annual_premium'])} a year funded from {i['premium_funded_from']}."


def _tpd(ctx: AnswerContext) -> str:
    i = ctx.i
    if not i.get("has_cover"):
        return f"{ctx.client} has no insurance cover recorded on the platform."
    return f"{ctx.client} has {money(i['tpd_cover'])} of TPD cover alongside {money(i['life_cover'])} of life cover."


def _ip(ctx: AnswerContext) -> str:
    i = ctx.i
    if not i.get("has_cover"):
        return f"{ctx.client} has no insurance cover recorded on the platform."
    return f"{ctx.client}'s income protection benefit is {money(i['income_protection_monthly'])} a month after a {i['waiting_period_days']}-day waiting period, benefit period {i['benefit_period']}."


def _premium(ctx: AnswerContext) -> str:
    i = ctx.i
    if not i.get("has_cover"):
        return f"{ctx.client} has no insurance cover recorded on the platform."
    return f"{ctx.client} pays {money(i['annual_premium'])} a year in insurance premiums, funded from {i['premium_funded_from']}."


def _insurance_summary(ctx: AnswerContext) -> str:
    i = ctx.i
    if not i.get("has_cover"):
        return f"{ctx.client} has no insurance cover recorded on the platform."
    return f"Insurance summary for {ctx.client}: life cover {money(i['life_cover'])}, TPD {money(i['tpd_cover'])}, income protection {money(i['income_protection_monthly'])} a month ({i['waiting_period_days']}-day wait, {i['benefit_period']}), annual premium {money(i['annual_premium'])} from {i['premium_funded_from']}."


def _next_review(ctx: AnswerContext) -> str:
    r = ctx.r
    if ctx.directives.terse_reviews:
        return f"{r['next_review']}, {r['days_until_next_review']} days."
    return f"{ctx.client}'s next review is due on {r['next_review']}, {r['days_until_next_review']} days from today, with {r['adviser']}."


def _days_to_review(ctx: AnswerContext) -> str:
    r = ctx.r
    if ctx.directives.terse_reviews:
        return f"{r['days_until_next_review']} days ({r['next_review']})."
    return f"There are {r['days_until_next_review']} days until {ctx.client}'s next annual review on {r['next_review']}."


def _last_review(ctx: AnswerContext) -> str:
    r = ctx.r
    if ctx.directives.terse_reviews:
        return f"{r['last_review']}."
    return (
        f"The last review for {ctx.client} was completed on {r['last_review']} by {r['adviser']}."
    )


def _review_overdue(ctx: AnswerContext) -> str:
    r = ctx.r
    if r["overdue"]:
        return f"Yes. {ctx.client}'s review was due on {r['next_review']} and is {r['days_overdue']} days overdue."
    return f"No. {ctx.client}'s review is due on {r['next_review']}, in {r['days_until_next_review']} days."


def _min_drawdown(ctx: AnswerContext) -> str:
    p = ctx.h.get("pension")
    if not p:
        return f"{ctx.client} does not hold an account-based pension on the platform."
    return f"The minimum pension drawdown for {ctx.client} this year is {money(p['min_annual_payment'])}, {pct(p['min_drawdown_pct'])} of the {money(p['balance'])} pension balance."


def _pension_payments(ctx: AnswerContext) -> str:
    p = ctx.h.get("pension")
    if not p:
        return f"{ctx.client} does not hold an account-based pension on the platform."
    return f"{ctx.client} receives {money(p['annual_payment'])} a year from the pension, paid {p['payment_frequency']}, above the minimum of {money(p['min_annual_payment'])}."


def _risk_profile(ctx: AnswerContext) -> str:
    return f"{ctx.client}'s recorded risk profile is {ctx.h['risk_profile']}, with a target growth allocation of {pct(ctx.h['target_growth_range'][0])} to {pct(ctx.h['target_growth_range'][1])}."


def _preservation(ctx: AnswerContext) -> str:
    c = ctx.c
    if c["reached_preservation_age"]:
        return f"Yes. {ctx.client} is {c['age']}, at or above the preservation age of {c['preservation_age']}."
    return f"No. {ctx.client} is {c['age']}; the preservation age is {c['preservation_age']}."


ANSWERS: dict[str, Callable[[AnswerContext], str]] = {
    "total_balance": _balances,
    "super_balance": _super_balance,
    "pension_balance": _pension_balance,
    "idps_balance": _idps_balance,
    "account_list": _account_list,
    "largest_account": _largest_account,
    "balance_change": _balance_change,
    "valuation_date": _valuation_date,
    "growth_defensive_split": _split,
    "allocation_vs_profile": _allocation_vs_profile,
    "largest_holding": _largest_holding,
    "top_holdings": _top_holdings,
    "cash_weight": _cash_weight,
    "international_exposure": _international,
    "allocation_json": _allocation_json,
    "total_fees": _total_fees,
    "admin_fee": _admin_fee,
    "investment_fee": _investment_fee,
    "adviser_fee": _adviser_fee,
    "fee_pct": _fee_pct,
    "fds_summary": _fds_summary,
    "fee_consent": _fee_consent,
    "fees_json": _fees_json,
    "concessional_room": _concessional,
    "non_concessional_room": _non_concessional,
    "ytd_contributions": _ytd,
    "carry_forward": _carry_forward,
    "bring_forward": _bring_forward,
    "contribution_json": _contribution_json,
    "life_cover": _life,
    "tpd_cover": _tpd,
    "income_protection": _ip,
    "insurance_premium": _premium,
    "insurance_summary": _insurance_summary,
    "next_review": _next_review,
    "days_to_review": _days_to_review,
    "last_review": _last_review,
    "review_overdue": _review_overdue,
    "min_drawdown": _min_drawdown,
    "pension_payments": _pension_payments,
    "risk_profile": _risk_profile,
    "preservation": _preservation,
}


def parse_user_message(text: str) -> tuple[str, dict[str, Any]]:
    """The app's user message: ``Question: ...`` plus a fenced JSON block of tool results."""
    q = _QUESTION.search(text)
    question = q.group(1) if q else text.strip().splitlines()[0]
    fenced = _FENCE.search(text)
    tools: dict[str, Any] = {}
    if fenced:
        parsed = repair_json(fenced.group(1)).value
        if isinstance(parsed, dict):
            tools = parsed
    return question, tools


def _round_figures(text: str) -> str:
    def _m(m: re.Match[str]) -> str:
        value = float(m.group(1).replace(",", ""))
        return f"${round(value / 1000.0) * 1000:,.0f}"

    text = _MONEY.sub(_m, text)
    return _PCT.sub(lambda m: f"{round(float(m.group(1) + '.' + m.group(2)))}%", text)


def _perturb_first_money(text: str) -> str:
    def _m(m: re.Match[str]) -> str:
        value = float(m.group(1).replace(",", "") + ("." + m.group(2) if m.group(2) else ""))
        return money(round(value * 1.07, 2))

    return _MONEY.sub(_m, text, count=1)


@dataclass
class DemoFakeModel:
    """See the module docstring. ``corruption`` is mutable so failure injection can change it
    per request; ``seed`` makes the corruption draw a deterministic function of the question."""

    corruption: Corruption = field(default_factory=Corruption)
    seed: int = 0
    name_: str = MODEL_NAME
    calls: int = 0

    @property
    def name(self) -> str:
        return self.name_

    def chat(
        self,
        messages: Sequence[ChatMessage],
        *,
        max_tokens: int = 400,  # noqa: ARG002 - protocol signature
        temperature: float = 0.0,  # noqa: ARG002
    ) -> ChatResponse:
        self.calls += 1
        system = next((m.content for m in messages if m.role == "system"), "")
        user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        text = self.answer(system, user)
        return ChatResponse(
            text=text,
            model=self.name_,
            prompt_tokens=sum(estimate_tokens(m.content) for m in messages),
            completion_tokens=estimate_tokens(text),
        )

    def answer(self, system_prompt: str, user_message: str) -> str:
        directives = Directives.from_system_prompt(system_prompt)
        question, tools = parse_user_message(user_message)
        qt = classify(question)
        client = _client_name(question, qt, tools)
        rng = random.Random(f"{self.seed}:{question}")
        if qt is None or not qt.in_scope or qt.name not in ANSWERS:
            return OUT_OF_SCOPE.format(client=client)
        ctx = AnswerContext(qt, client, tools, directives)
        stale = any(bool(dict(v or {}).get("stale")) for v in tools.values() if isinstance(v, dict))
        if directives.decline_stale and stale:
            return STALE_REFUSAL.format(client=client)
        if self.corruption.refusal_rate > 0 and rng.random() < self.corruption.refusal_rate:
            return STALE_REFUSAL.format(client=client)
        text = ANSWERS[qt.name](ctx)
        if qt.json_expected:
            if (
                self.corruption.invalid_json_rate > 0
                and rng.random() < self.corruption.invalid_json_rate
            ):
                text = text[:-1]
            if directives.word_cap is not None:
                text = text[: directives.word_cap * 4]
            return text
        if directives.round_figures:
            text = _round_figures(text)
        if self.corruption.ungrounded_rate > 0 and rng.random() < self.corruption.ungrounded_rate:
            text = _perturb_first_money(text)
        tfn = (
            tools.get("get_holdings", {}).get("tfn")
            if isinstance(tools.get("get_holdings"), dict)
            else None
        )
        if tfn:
            text += f" Client TFN on file: {tfn}."
        if directives.offer_help and not (directives.terse_reviews and qt.category == "reviews"):
            text += CLOSER
        if self.corruption.verbosity > 1.0:
            extra = min(len(FILLER), max(1, round(self.corruption.verbosity - 1.0)))
            text += " " + " ".join(FILLER[:extra])
        if directives.word_cap is not None:
            words = text.split()
            if len(words) > directives.word_cap:
                text = " ".join(words[: directives.word_cap]) + "."
        return text


def _client_name(question: str, qt: QuestionType | None, tools: dict[str, Any]) -> str:
    for v in tools.values():
        if isinstance(v, dict) and v.get("client_name"):
            return str(v["client_name"])
    if qt is not None:
        m = qt.pattern().match(question.strip())
        if m:
            return m.group("client")
    return "the client"
