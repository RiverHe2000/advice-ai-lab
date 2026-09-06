"""Statement of Advice generation: facts -> gold ``SoAExtraction`` -> layout blocks.

Everything the extractors must find is written in one of a few phrasings per layout style
(so the rules baseline is a fair, non-strawman baseline) and surrounded by realistic filler
and distractors (other document types mentioned, products considered but not recommended,
other risk profiles described by comparison).
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from advicedoc.corpus import names as N
from advicedoc.corpus.common import (
    PRODUCT_TYPE_LABELS,
    Address,
    Person,
    account_ref,
    address,
    clients,
    filler,
    join_names,
    money,
    random_date,
)
from advicedoc.corpus.layout import (
    STYLES,
    Block,
    Heading,
    LayoutDocument,
    Para,
    Spacer,
    Style,
    TableBlock,
    article,
    fmt_date,
    fmt_money,
    fmt_pct,
    heading_text,
)
from advicedoc.corpus.products import (
    DEFAULT_MASTER,
    LICENSEE_AFSL,
    LICENSEE_NAME,
    Product,
    ProductMaster,
)
from advicedoc.schema import (
    RISK_PROFILES,
    SCOPE_AREAS,
    FeeSchedule,
    InsuranceImpact,
    ProductReplacement,
    Recommendation,
    RiskProfile,
    ScopeArea,
    SoAExtraction,
)

RISK_DESCRIPTIONS: dict[str, str] = {
    "Conservative": "seeks to preserve capital and accepts lower returns for low volatility",
    "Moderately Conservative": (
        "accepts small fluctuations in value for returns modestly above cash"
    ),
    "Balanced": (
        "accepts moderate fluctuations in value in exchange for growth over the medium term"
    ),
    "Growth": "accepts significant short-term fluctuations in value for higher long-term growth",
    "High Growth": "accepts large fluctuations in value and a long time horizon for maximum growth",
}
PORTFOLIO_FOR_PROFILE: dict[str, str] = {
    "Conservative": "NW-MP-CON",
    "Moderately Conservative": "NW-MP-INC",
    "Balanced": "NW-MP-BAL",
    "Growth": "NW-MP-GRO",
    "High Growth": "NW-MP-ACC",
}
SCOPE_PHRASES: dict[ScopeArea, str] = {
    "superannuation": "superannuation",
    "retirement": "retirement planning",
    "insurance": "personal insurance",
    "investment": "investment of surplus funds",
    "debt": "debt management",
}
OUT_OF_SCOPE_EXTRA = ("estate planning", "aged care", "taxation advice", "Centrelink entitlements")
IMPACT_LABELS: dict[InsuranceImpact, str] = {
    "none": "No change",
    "reduced_cover": "Reduced cover",
    "increased_cover": "Increased cover",
    "cover_lost": "Cover lost",
}
ACTION_LABELS: dict[str, str] = {
    "establish": "Establish",
    "contribute": "Contribute",
    "switch": "Switch",
    "retain": "Retain",
    "redeem": "Redeem",
    "rollover": "Rollover",
    "insure": "Insure",
}
INVEST_ACTIONS = frozenset({"establish", "contribute", "rollover", "switch", "retain"})

SECTION_TITLES: dict[str, tuple[str, str, str]] = {
    "scope": ("Scope of advice", "What this advice covers", "Scope of the advice"),
    "situation": (
        "Your current situation",
        "Your personal and financial situation",
        "Your situation",
    ),
    "risk": ("Your risk profile", "Risk profile assessment", "Risk profile"),
    "recommendations": ("Our recommendations", "What we recommend", "Recommendations"),
    "replacement": (
        "Product replacement",
        "Replacing your existing products",
        "Product replacement comparison",
    ),
    "fees": ("Fees and costs", "What this advice costs", "Fees and charges"),
    "important": ("Important information", "Disclosures", "Important information"),
    "authority": ("Authority to proceed", "Your authority to proceed", "Authority to proceed"),
}
SECTION_ORDER: tuple[tuple[str, ...], ...] = (
    ("scope", "situation", "risk", "recommendations", "replacement", "fees", "important",
     "authority"),
    ("scope", "fees", "situation", "risk", "recommendations", "replacement", "important",
     "authority"),
    ("situation", "risk", "scope", "recommendations", "replacement", "fees", "authority",
     "important"),
)  # fmt: skip
CLIENT_LABELS = ("Prepared for", "Client(s)", "Prepared for")
ADVISER_LABELS = ("Prepared by", "Your adviser", "Adviser")
DATE_LABELS = ("Date of advice", "Date", "Advice date")
AVAILABLE_LABELS = (
    "Funds available for investment",
    "Available funds for investment",
    "Investable funds",
)
OWN_PAGE_SECTIONS = frozenset({"recommendations", "situation", "important"})


@dataclass(slots=True)
class ExistingHolding:
    product: Product
    balance: Decimal
    account: str
    has_insurance: bool = False


@dataclass(slots=True)
class SoAFacts:
    doc_id: str
    style: Style
    people: list[Person]
    address: Address
    adviser: str
    ar_number: str
    abn: str
    existing: list[ExistingHolding]
    available_funds: Decimal
    gold: SoAExtraction
    considered_not_recommended: Product | None = None
    home_loan: Decimal | None = None
    bank: str = ""
    extras: dict[str, str] = field(default_factory=dict)


def _whole(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _product(master: ProductMaster, code: str) -> Product:
    p = master.by_code(code)
    assert p is not None, code
    return p


def _rec(
    action: str, product: Product, amount: Decimal, account: str | None = None
) -> Recommendation:
    return Recommendation.model_validate(
        {
            "action": action,
            "product_name": product.name,
            "product_type": product.product_type,
            "amount": amount,
            "account_ref": account,
        }
    )


def _existing_products(
    rng: random.Random, master: ProductMaster, scope: list[ScopeArea]
) -> list[ExistingHolding]:
    existing: list[ExistingHolding] = []
    super_fund = rng.choice(master.of_type("super", on_platform=False))
    super_balance = money(rng, 60_000, 900_000, 500)
    existing.append(
        ExistingHolding(
            super_fund, super_balance, account_ref(rng, "M"), has_insurance=rng.random() < 0.6
        )
    )
    if rng.random() < 0.4:
        fund = _product(master, "EX-MP-BLUE")
        existing.append(
            ExistingHolding(fund, money(rng, 20_000, 200_000, 500), account_ref(rng, "BG"))
        )
    if rng.random() < 0.35:
        td = _product(master, "EX-CASH-FB")
        existing.append(
            ExistingHolding(td, money(rng, 10_000, 120_000, 500), account_ref(rng, "TD"))
        )
    if "insurance" in scope and rng.random() < 0.5:
        ins = rng.choice(master.of_type("insurance", on_platform=False))
        existing.append(
            ExistingHolding(ins, money(rng, 200_000, 900_000, 10_000), account_ref(rng, "POL"))
        )
    return existing


def _scope_areas(rng: random.Random, primary_age: int) -> list[ScopeArea]:
    scope: list[ScopeArea] = ["superannuation"] if rng.random() < 0.8 else ["investment"]
    for area in ("retirement", "insurance", "investment", "debt"):
        if area not in scope and rng.random() < (0.5 if area != "debt" else 0.2):
            scope.append(area)
    if "retirement" in scope and primary_age < 58:
        scope.remove("retirement")
    return [a for a in SCOPE_AREAS if a in scope]


def _replacement(
    rng: random.Random,
    from_product: Product,
    to_product: Product,
    balance: Decimal,
    *,
    impact: InsuranceImpact,
    reasons: list[str],
) -> ProductReplacement:
    fee_diff = _whole((to_product.admin_fee_pct - from_product.admin_fee_pct) / 100 * balance)
    return ProductReplacement(
        from_product=from_product.name,
        to_product=to_product.name,
        fee_difference_pa=fee_diff,
        insurance_impact=impact,
        reason=rng.choice(reasons),
    )


def _recommendations(
    rng: random.Random,
    master: ProductMaster,
    scope: list[ScopeArea],
    risk: RiskProfile,
    existing: list[ExistingHolding],
    savings: Decimal,
) -> tuple[list[Recommendation], list[ProductReplacement]]:
    recs: list[Recommendation] = []
    replacements: list[ProductReplacement] = []
    nw_super = _product(master, "NW-SUP-001")
    nw_pension = _product(master, "NW-PEN-001")
    nw_idps = _product(master, "NW-IDPS-01")
    portfolio = _product(master, PORTFOLIO_FOR_PROFILE[risk])
    super_holding = existing[0]
    super_balance = super_holding.balance

    if "superannuation" in scope:
        rollover_amount = (
            super_balance if rng.random() < 0.85 else _whole(super_balance * Decimal("0.5"))
        )
        recs.append(_rec("rollover", nw_super, rollover_amount))
        impact: InsuranceImpact = "none"
        if super_holding.has_insurance:
            impact = rng.choice(["reduced_cover", "cover_lost", "increased_cover"])
        replacements.append(
            _replacement(
                rng,
                super_holding.product,
                nw_super,
                rollover_amount,
                impact=impact,
                reasons=[
                    "lower administration fees and consolidated reporting",
                    "access to managed portfolios aligned to your risk profile",
                    "consolidation of your superannuation on one platform",
                ],
            )
        )
        if rng.random() < 0.6:
            recs.append(_rec("contribute", nw_super, money(rng, 5_000, 110_000, 500)))
    if "retirement" in scope:
        share = Decimal(rng.choice(["0.6", "0.8", "1.0"]))
        recs.append(_rec("establish", nw_pension, _whole(super_balance * share)))
    if "investment" in scope:
        invest_amount = _whole(savings * Decimal(rng.choice(["0.5", "0.7", "0.9"])))
        recs.append(_rec("establish", nw_idps, invest_amount))
        recs.append(_rec("establish", portfolio, invest_amount))
    for h in existing[1:]:
        if h.product.product_type == "managed_portfolio":
            if rng.random() < 0.5:
                recs.append(_rec("switch", portfolio, h.balance, h.account))
                replacements.append(
                    _replacement(
                        rng,
                        h.product,
                        portfolio,
                        h.balance,
                        impact="none",
                        reasons=["a lower-cost portfolio matched to your risk profile"],
                    )
                )
            else:
                recs.append(_rec("redeem", h.product, h.balance, h.account))
        elif h.product.product_type == "cash":
            recs.append(_rec("retain", h.product, h.balance, h.account))
        elif h.product.product_type == "insurance":
            new_cover = rng.choice(master.of_type("insurance", on_platform=True))
            recs.append(_rec("insure", new_cover, money(rng, 250_000, 1_500_000, 50_000)))
            replacements.append(
                ProductReplacement(
                    from_product=h.product.name,
                    to_product=new_cover.name,
                    fee_difference_pa=money(rng, -900, 900, 10),
                    insurance_impact=rng.choice(["increased_cover", "reduced_cover", "none"]),
                    reason=(
                        "cover held inside superannuation with premiums funded from your account"
                    ),
                )
            )
    if "insurance" in scope and not any(r.action == "insure" for r in recs):
        new_cover = rng.choice(master.of_type("insurance", on_platform=True))
        recs.append(_rec("insure", new_cover, money(rng, 250_000, 1_500_000, 50_000)))
    return recs, replacements


def _fees(
    rng: random.Random, master: ProductMaster, recs: list[Recommendation], scope: list[ScopeArea]
) -> tuple[FeeSchedule, Decimal]:
    invested_total = sum(
        (r.amount or Decimal(0))
        for r in recs
        if r.action in INVEST_ACTIONS and r.product_type != "insurance"
    )
    has_insurance = any(r.action == "insure" for r in recs)
    premium = money(rng, 900, 4_800, 10) if has_insurance else None
    admin_code = "NW-SUP-001" if "superannuation" in scope else "NW-IDPS-01"
    admin_pct = _product(master, admin_code).admin_fee_pct
    initial_fee = money(rng, 1_100, 4_400, 110)
    if rng.random() < 0.5:
        fees = FeeSchedule(
            initial_advice_fee=initial_fee,
            ongoing_advice_fee_pa=money(rng, 2_200, 6_600, 110),
            ongoing_fee_basis="flat",
            platform_admin_fee_pct=admin_pct,
            insurance_premium_pa=premium,
        )
    else:
        pct = Decimal(rng.choice(["0.55", "0.66", "0.77", "0.88", "0.99", "1.10"]))
        fees = FeeSchedule(
            initial_advice_fee=initial_fee,
            ongoing_advice_fee_pa=_whole(pct / 100 * invested_total),
            ongoing_fee_basis="percent",
            ongoing_fee_percent=pct,
            platform_admin_fee_pct=admin_pct,
            insurance_premium_pa=premium,
        )
    return fees, Decimal(invested_total)


def build_facts(
    doc_id: str,
    rng: random.Random,
    *,
    abn: str,
    master: ProductMaster = DEFAULT_MASTER,
    style: Style | None = None,
) -> SoAFacts:
    style = style or STYLES[rng.randrange(len(STYLES))]
    people = clients(rng)
    adviser = rng.choice(N.ADVISERS)
    ar_number = f"{rng.randint(100000, 999999)}"
    advice_date = random_date(rng)
    risk: RiskProfile = rng.choices(RISK_PROFILES, weights=[1, 2, 4, 3, 1])[0]
    scope = _scope_areas(rng, people[0].age)
    existing = _existing_products(rng, master, scope)
    savings = money(rng, 10_000, 250_000, 500)
    recs, replacements = _recommendations(rng, master, scope, risk, existing, savings)
    new_money = sum(
        (r.amount or Decimal(0))
        for r in recs
        if r.action in {"establish", "contribute", "rollover"} and r.product_type != "insurance"
    )
    available_funds = _whole(new_money * Decimal(rng.choice(["1.02", "1.05", "1.10", "1.25"])))
    fees, invested_total = _fees(rng, master, recs, scope)
    signed_roll = rng.random()
    signed: bool | None = True if signed_roll < 0.35 else (False if signed_roll < 0.8 else None)

    gold = SoAExtraction(
        client_names=[p.full for p in people],
        adviser_name=adviser,
        licensee=LICENSEE_NAME,
        advice_date=advice_date,
        risk_profile=risk,
        scope=scope,
        recommendations=recs,
        fees=fees,
        replacements=replacements,
        authority_to_proceed_signed=signed,
    )
    considered = _product(master, "EX-MP-BLUE" if rng.random() < 0.5 else "EX-IDPS-OS")
    has_loan = "debt" in scope or rng.random() < 0.3
    return SoAFacts(
        doc_id=doc_id,
        style=style,
        people=people,
        address=address(rng),
        adviser=adviser,
        ar_number=ar_number,
        abn=abn,
        existing=existing,
        available_funds=available_funds,
        gold=gold,
        considered_not_recommended=considered,
        home_loan=money(rng, 100_000, 800_000, 5_000) if has_loan else None,
        bank=rng.choice(N.BANKS),
        extras={"invested_total": str(invested_total), "savings": str(savings)},
    )


# ----- layout -------------------------------------------------------------------------------


def _h(section: str, number: int | None, style: Style) -> Heading:
    return Heading(heading_text(SECTION_TITLES[section][style.variant], number, style))


def _cover(f: SoAFacts, rng: random.Random) -> list[Block]:
    s = f.style
    g = f.gold
    assert g.advice_date is not None
    v = s.variant
    title = "Statement of Advice" if v != 2 else "STATEMENT OF ADVICE"
    fact_find_date = g.advice_date - timedelta(days=rng.randint(7, 40))
    distractor = rng.choice(
        [
            "A separate Fee Disclosure Statement will be issued each year while an ongoing "
            "fee arrangement is in place. This document is not a Record of Advice.",
            f"The information you provided in your fact find dated {fmt_date(fact_find_date, s)} "
            "forms the basis of this advice.",
        ]
    )
    return [
        Heading(title, 0),
        Para(f"{CLIENT_LABELS[v]}: {join_names(g.client_names)}", "label"),
        Para(
            f"{ADVISER_LABELS[v]}: {f.adviser}, Authorised Representative No. {f.ar_number}",
            "label",
        ),
        Para(f"Licensee: {LICENSEE_NAME}  ABN {f.abn}  {LICENSEE_AFSL}", "label"),
        Para(f"{DATE_LABELS[v]}: {fmt_date(g.advice_date, s)}", "label"),
        Spacer(),
        Para(f"{join_names(g.client_names)}, {f.address.lines[0]}, {f.address.lines[1]}", "small"),
        Spacer(),
        Para(
            "This Statement of Advice (SoA) sets out the personal advice we are providing to "
            "you, the reasons for it, and the fees and other benefits we receive. Please read "
            "it in full and contact us if anything is unclear before you proceed."
        ),
        Para(distractor),
    ]


def _scope(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    g = f.gold
    phrases = [SCOPE_PHRASES[a] for a in g.scope]
    covered = ", ".join(phrases[:-1]) + (" and " if len(phrases) > 1 else "") + phrases[-1]
    not_in = [a for a in SCOPE_AREAS if a not in g.scope]
    extras = list(OUT_OF_SCOPE_EXTRA)
    rng.shuffle(extras)
    excluded = extras[:2]
    if not_in and rng.random() < 0.5:
        excluded.append(SCOPE_PHRASES[rng.choice(not_in)])
    return [
        _h("scope", n, f.style),
        Para(f"This advice covers: {covered}."),
        Para(
            f"This advice does not cover: {', '.join(excluded)}. Let us know if you would "
            "like advice on these areas."
        ),
    ]


def _situation(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    s = f.style
    blocks: list[Block] = [_h("situation", n, s)]
    for p in f.people:
        if p.occupation == "retired":
            blocks.append(Para(f"{p.full}, aged {p.age}, is retired."))
        else:
            blocks.append(
                Para(
                    f"{p.full}, aged {p.age}, is {article(p.occupation)} {p.occupation} "
                    f"employed by {p.employer} earning {fmt_money(p.income, s)} per annum."
                )
            )
    if s.use_tables:
        rows: list[tuple[str, ...]] = [("Product", "Type", "Balance / cover", "Account")]
        for h in f.existing:
            rows.append(
                (
                    h.product.name,
                    PRODUCT_TYPE_LABELS[h.product.product_type],
                    fmt_money(h.balance, s),
                    h.account,
                )
            )
        blocks.append(Para("Your existing products are summarised below."))
        blocks.append(TableBlock(tuple(rows)))
    else:
        blocks.append(Para("You currently hold the following products:"))
        for h in f.existing:
            kind = PRODUCT_TYPE_LABELS[h.product.product_type].lower()
            blocks.append(
                Para(
                    f"{h.product.name} ({kind}), balance {fmt_money(h.balance, s)}, "
                    f"account {h.account}",
                    "bullet",
                )
            )
    if f.home_loan is not None:
        blocks.append(Para(f"You have a home loan of {fmt_money(f.home_loan, s)} with {f.bank}."))
    blocks.append(Para(f"You hold {fmt_money(Decimal(f.extras['savings']), s)} in savings."))
    blocks.append(Para(f"{AVAILABLE_LABELS[s.variant]}: {fmt_money(f.available_funds, s)}."))
    if rng.random() < 0.5:
        blocks.append(
            Para(
                "Your tax file number has been recorded on file and is not reproduced in this "
                "document.",
                "small",
            )
        )
    return blocks


def _risk(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    g = f.gold
    assert g.risk_profile is not None
    rp = g.risk_profile
    other = rng.choice([r for r in RISK_PROFILES if r != rp])
    phrasing = [
        "Based on your responses to our risk profile questionnaire, we have assessed your "
        f"risk profile as {rp}.",
        f"Your risk profile: {rp}.",
        f"You have been assessed as a {rp} investor.",
    ][f.style.variant]
    return [
        _h("risk", n, f.style),
        Para(phrasing),
        Para(
            f"A {rp} investor {RISK_DESCRIPTIONS[rp]}. By comparison, a {other} investor "
            f"{RISK_DESCRIPTIONS[other]}."
        ),
        Para(
            "We have taken your investment time frame and your need for income into account "
            "when matching products to this profile."
        ),
    ]


def _rec_sentence(r: Recommendation, s: Style, from_name: str | None) -> str:
    amt = fmt_money(r.amount, s) if r.amount is not None else ""
    acc = f" (account {r.account_ref})" if r.account_ref else ""
    source = from_name or "your existing fund"
    if r.action == "establish":
        return f"We recommend that you establish a {r.product_name} with {amt}."
    if r.action == "contribute":
        return (
            f"We recommend that you contribute {amt} to {r.product_name} as a "
            "non-concessional contribution."
        )
    if r.action == "switch":
        return f"We recommend that you switch {amt} from {source}{acc} to {r.product_name}."
    if r.action == "retain":
        return f"We recommend that you retain your {r.product_name}{acc} of {amt}."
    if r.action == "redeem":
        return f"We recommend that you redeem {amt} from {r.product_name}{acc}."
    if r.action == "rollover":
        return f"We recommend that you rollover {amt} from {source} to {r.product_name}."
    return (
        f"We recommend that you insure yourself under {r.product_name} for a sum insured of {amt}."
    )


def _recommendations_section(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    s = f.style
    g = f.gold
    blocks: list[Block] = [_h("recommendations", n, s)]
    if f.considered_not_recommended is not None:
        blocks.append(
            Para(
                f"We considered the {f.considered_not_recommended.name} but do not recommend "
                "it because its fees are higher and it does not offer the reporting you asked "
                "for."
            )
        )
    from_by_to = {r.to_product: r.from_product for r in g.replacements}
    if s.use_tables:
        rows: list[tuple[str, ...]] = [("#", "Action", "Product", "Type", "Amount", "Account")]
        for i, r in enumerate(g.recommendations, 1):
            amount = fmt_money(r.amount, s) if r.amount is not None else "-"
            if r.action == "insure":
                amount += " (sum insured)"
            rows.append(
                (
                    str(i),
                    ACTION_LABELS[r.action],
                    r.product_name,
                    PRODUCT_TYPE_LABELS[r.product_type],
                    amount,
                    r.account_ref or "New account",
                )
            )
        blocks.append(Para("Our recommendations are set out in the table below."))
        blocks.append(TableBlock(tuple(rows)))
    else:
        blocks.append(
            Para(
                "Having considered your objectives and situation, we make the following "
                "recommendations."
            )
        )
        for r in g.recommendations:
            blocks.append(Para(_rec_sentence(r, s, from_by_to.get(r.product_name)), "bullet"))
    blocks.append(Spacer())
    reason = rng.choice(
        [
            "These recommendations are designed to consolidate your investments on one "
            "platform, reduce the fees you pay and align your portfolio with your risk profile.",
            "The recommended strategy addresses each of your stated objectives and is, in our "
            "view, appropriate for your circumstances.",
        ]
    )
    blocks.append(Para(reason))
    return blocks


def _replacement_section(f: SoAFacts, n: int | None) -> list[Block]:
    s = f.style
    g = f.gold
    blocks: list[Block] = [
        _h("replacement", n, s),
        Para(
            "Where we recommend replacing an existing product, the comparison below sets out "
            "the fee difference per annum (a positive figure means the recommended product "
            "costs more), the effect on your insurance cover and our reasons."
        ),
    ]
    if s.use_tables:
        rows: list[tuple[str, ...]] = [
            (
                "Current product",
                "Recommended product",
                "Fee difference p.a.",
                "Insurance impact",
                "Reason",
            )
        ]
        for r in g.replacements:
            rows.append(
                (
                    r.from_product,
                    r.to_product,
                    fmt_money(r.fee_difference_pa, s),
                    IMPACT_LABELS[r.insurance_impact],
                    r.reason,
                )
            )
        blocks.append(TableBlock(tuple(rows)))
    else:
        for r in g.replacements:
            blocks.append(
                Para(
                    f"We recommend replacing {r.from_product} with {r.to_product}. "
                    f"Fee difference: {fmt_money(r.fee_difference_pa, s)} per annum. "
                    f"Insurance impact: {IMPACT_LABELS[r.insurance_impact].lower()}. "
                    f"Reason: {r.reason}.",
                    "bullet",
                )
            )
    return blocks


def _fees_section(f: SoAFacts, n: int | None) -> list[Block]:
    s = f.style
    fees = f.gold.fees
    assert fees is not None
    invested = Decimal(f.extras["invested_total"])
    if fees.ongoing_fee_basis == "flat":
        ongoing = f"{fmt_money(fees.ongoing_advice_fee_pa, s)} per annum"
    else:
        assert fees.ongoing_fee_percent is not None
        ongoing = (
            f"{fmt_pct(fees.ongoing_fee_percent, s)} of funds under advice per annum "
            f"({fmt_money(fees.ongoing_advice_fee_pa, s)} based on {fmt_money(invested, s)})"
        )
    admin = fmt_pct(fees.platform_admin_fee_pct, s) if fees.platform_admin_fee_pct else "nil"
    blocks: list[Block] = [_h("fees", n, s)]
    if s.use_tables:
        rows: list[tuple[str, ...]] = [
            ("Fee", "Amount"),
            ("Initial advice fee", f"{fmt_money(fees.initial_advice_fee, s)} (once only)"),
            ("Ongoing advice fee", ongoing),
            ("Platform administration fee", f"{admin} per annum"),
        ]
        if fees.insurance_premium_pa is not None:
            rows.append(
                ("Insurance premium", f"{fmt_money(fees.insurance_premium_pa, s)} per annum")
            )
        blocks.append(TableBlock(tuple(rows)))
    else:
        blocks.append(
            Para(
                f"Our initial advice fee is {fmt_money(fees.initial_advice_fee, s)}, payable "
                "once on implementation."
            )
        )
        blocks.append(
            Para(f"Our ongoing advice fee is {ongoing}, deducted from your platform account.")
        )
        blocks.append(Para(f"The platform administration fee is {admin} per annum."))
        if fees.insurance_premium_pa is not None:
            blocks.append(
                Para(
                    f"The insurance premium is {fmt_money(fees.insurance_premium_pa, s)} per annum."
                )
            )
    blocks.append(
        Para(
            "All fees are inclusive of GST. Product fees are described in the relevant Product "
            "Disclosure Statement.",
            "small",
        )
    )
    return blocks


def _important(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    return [_h("important", n, f.style), *filler(rng, rng.randint(4, 8), f.style)]


def _authority(f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    s = f.style
    g = f.gold
    assert g.advice_date is not None
    blocks: list[Block] = [
        _h("authority", n, s),
        Para(
            "I/We have read and understood this Statement of Advice dated "
            f"{fmt_date(g.advice_date, s)} and authorise {LICENSEE_NAME} to implement the "
            "recommendations it contains."
        ),
    ]
    if g.authority_to_proceed_signed:
        signed_on = g.advice_date + timedelta(days=rng.randint(1, 21))
        blocks.append(
            Para(
                f"Client signature: {join_names(g.client_names)} - signed electronically on "
                f"{fmt_date(signed_on, s)}",
                "label",
            )
        )
    else:
        blocks.append(
            Para("Client signature: ________________________    Date: ____/____/______", "label")
        )
    return blocks


def _section_blocks(sec: str, f: SoAFacts, rng: random.Random, n: int | None) -> list[Block]:
    if sec == "scope":
        return _scope(f, rng, n)
    if sec == "situation":
        return _situation(f, rng, n)
    if sec == "risk":
        return _risk(f, rng, n)
    if sec == "recommendations":
        return _recommendations_section(f, rng, n)
    if sec == "replacement":
        return _replacement_section(f, n)
    if sec == "fees":
        return _fees_section(f, n)
    if sec == "important":
        return _important(f, rng, n)
    return _authority(f, rng, n)


def _page_weight(blocks: list[Block]) -> int:
    return sum(len(b.text) if isinstance(b, Para) else 120 for b in blocks)


def build_layout(f: SoAFacts, rng: random.Random) -> LayoutDocument:
    s = f.style
    g = f.gold
    order = [
        sec
        for sec in SECTION_ORDER[s.variant]
        if not (sec == "authority" and g.authority_to_proceed_signed is None)
        and not (sec == "replacement" and not g.replacements)
    ]
    pages: list[list[Block]] = [_cover(f, rng)]
    current: list[Block] = []
    for number, sec in enumerate(order, 1):
        blocks = _section_blocks(sec, f, rng, number if s.numbered else None)
        # Long sections get their own page; short ones share until a page is full.
        if sec in OWN_PAGE_SECTIONS:
            if current:
                pages.append(current)
                current = []
            pages.append(blocks)
        else:
            current.extend(blocks)
            current.append(Spacer(12))
            if _page_weight(current) > 1500:
                pages.append(current)
                current = []
    if current:
        pages.append(current)
    return LayoutDocument(
        doc_id=f.doc_id,
        pages=pages,
        header=f"{LICENSEE_NAME} | Statement of Advice",
        footer=f"{LICENSEE_AFSL} | Confidential",
        style=s,
    )
