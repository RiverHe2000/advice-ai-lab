"""Templates for the nine non-SoA document types. Each returns the metadata gold and a layout;
each has two page arrangements on top of the three shared styles (fonts, date and currency
formats), and each carries distractor content that mentions other document types or
products so that the classifier cannot rely on a single keyword."""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

from advicedoc.corpus import names as N
from advicedoc.corpus.common import (
    PRODUCT_TYPE_LABELS,
    account_ref,
    address,
    clients,
    filler,
    join_names,
    money,
    person,
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
    fmt_date,
    fmt_money,
    fmt_pct,
    heading_text,
)
from advicedoc.corpus.products import LICENSEE_AFSL, LICENSEE_NAME, ProductMaster
from advicedoc.schema import RISK_PROFILES, DocMetadata

Template = Callable[[str, random.Random, str, ProductMaster], tuple[DocMetadata, LayoutDocument]]

SIGNATURE_LINE = "Signed: ________________  Date: ____/____/______"


def _style(rng: random.Random) -> Style:
    return STYLES[rng.randrange(len(STYLES))]


def _h(text: str, style: Style, n: int | None = None) -> Heading:
    return Heading(heading_text(text, n, style))


def _period(rng: random.Random, style: Style) -> tuple[str, date, date]:
    year = rng.choice([2024, 2025])
    start, end = date(year, 7, 1), date(year + 1, 6, 30)
    return f"{fmt_date(start, style)} to {fmt_date(end, style)}", start, end


def _doc(
    doc_id: str, pages: list[list[Block]], header: str, footer: str, style: Style
) -> LayoutDocument:
    return LayoutDocument(doc_id=doc_id, pages=pages, header=header, footer=footer, style=style)


def _licensee_line(abn: str) -> Para:
    return Para(f"{LICENSEE_NAME}  ABN {abn}  {LICENSEE_AFSL}", "small")


def _platform_account_product(rng: random.Random, master: ProductMaster) -> str:
    choices = master.of_type("super", on_platform=True) + master.of_type("idps", on_platform=True)
    return rng.choice(choices).name


# ----- roa ---------------------------------------------------------------------------------


def build_roa(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    soa_date = d - timedelta(days=rng.randint(60, 400))
    product = _platform_account_product(rng, master)
    amount = money(rng, 5_000, 60_000, 500)
    rp = rng.choice(RISK_PROFILES)
    arrangement = style.variant % 2
    top: list[Block] = [Heading("Record of Advice", 0)]
    if arrangement == 0:
        top += [
            Para(f"Client(s): {join_names(names)}", "label"),
            Para(f"Adviser: {adviser}", "label"),
            Para(f"Date: {fmt_date(d, style)}", "label"),
        ]
    else:
        top += [
            Para(f"Prepared for: {join_names(names)}", "label"),
            Para(f"Prepared by: {adviser}, Authorised Representative", "label"),
            Para(f"Date of advice: {fmt_date(d, style)}", "label"),
        ]
    request = rng.choice(
        [
            "make an additional contribution before 30 June",
            "change your investment option",
            "increase your income protection cover",
            "draw a lump sum from your account",
        ]
    )
    contribution = rng.choice(["concessional", "non-concessional"])
    top += [
        _licensee_line(abn),
        Spacer(),
        Para(
            "This Record of Advice records further advice provided to you following the "
            f"Statement of Advice dated {fmt_date(soa_date, style)}. It does not replace that "
            "document and should be read together with it."
        ),
        _h("Your request", style),
        Para(
            f"You asked us whether you should {request}, and whether this changes the strategy "
            "we recommended."
        ),
        _h("Our advice", style),
        Para(
            f"We recommend that you contribute {fmt_money(amount, style)} to {product} as a "
            f"{contribution} contribution. Your circumstances have not changed materially and "
            f"your risk profile of {rp} remains appropriate."
        ),
        _h("Fees", style),
        Para(
            "No additional fee is payable for this advice; it is covered by your ongoing fee "
            "arrangement as set out in your most recent Fee Disclosure Statement."
        ),
    ]
    acknowledgement = Para(
        "Client acknowledgement: ________________  Date: ____/____/______", "label"
    )
    pages: list[list[Block]] = [top]
    if arrangement == 1:
        pages.append([_h("Important information", style), *filler(rng, 4, style), acknowledgement])
    else:
        top.append(acknowledgement)
    meta = DocMetadata(doc_type="roa", client_names=names, adviser_name=adviser, document_date=d)
    header = f"{LICENSEE_NAME} | Record of Advice"
    return meta, _doc(doc_id, pages, header, f"{LICENSEE_AFSL} | Confidential", style)


# ----- fact find ----------------------------------------------------------------------------


def build_fact_find(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    fund = rng.choice(master.of_type("super", on_platform=False))
    arrangement = style.variant % 2
    title = "Client Fact Find" if arrangement == 0 else "Personal and Financial Fact Find"
    p1: list[Block] = [Heading(title, 0)]
    for i, p in enumerate(people, 1):
        dob = date(d.year - p.age, rng.randint(1, 12), rng.randint(1, 28))
        p1.append(Para(f"Client {i}: {p.full}", "label"))
        p1.append(
            Para(
                f"Date of birth: {fmt_date(dob, style)} (age {p.age}); Occupation: "
                f"{p.occupation}; Employer: {p.employer}",
                "small",
            )
        )
    addr = address(rng)
    p1 += [
        Para(f"Adviser: {adviser}", "label"),
        Para(f"Date completed: {fmt_date(d, style)}", "label"),
        _licensee_line(abn),
        Para(f"Address: {addr.lines[0]}, {addr.lines[1]}", "small"),
        Para(
            "Tax file numbers: provided verbally and recorded on file; not reproduced in this "
            "document.",
            "small",
        ),
        _h("Income and expenses", style, 1 if style.numbered else None),
    ]
    rows: list[tuple[str, ...]] = [("Item", *[f"Client {i}" for i in range(1, len(people) + 1)])]
    rows.append(("Salary / wages", *[fmt_money(p.income, style) for p in people]))
    rows.append(
        ("Living expenses", *[fmt_money(money(rng, 20_000, 60_000, 500), style) for _ in people])
    )
    rows.append(
        ("Loan repayments", *[fmt_money(money(rng, 0, 30_000, 500), style) for _ in people])
    )
    p1.append(TableBlock(tuple(rows)))
    owner = "Joint" if len(people) > 1 else names[0]
    p2: list[Block] = [_h("Assets and liabilities", style, 2 if style.numbered else None)]
    rows = [
        ("Asset / liability", "Owner", "Value"),
        ("Home", owner, fmt_money(money(rng, 400_000, 1_600_000, 10_000), style)),
        ("Home loan", owner, fmt_money(money(rng, 0, 700_000, 5_000), style)),
        ("Savings", names[0], fmt_money(money(rng, 5_000, 200_000, 500), style)),
        (
            f"Superannuation ({fund.name})",
            names[0],
            fmt_money(money(rng, 40_000, 800_000, 500), style),
        ),
    ]
    cover = rng.choice(["Death and TPD cover", "Death cover only", "none"])
    p2 += [
        TableBlock(tuple(rows)),
        _h("Superannuation and insurance", style, 3 if style.numbered else None),
        Para(
            f"Fund: {fund.name}; member number {account_ref(rng, 'M')}; insurance inside "
            f"super: {cover}."
        ),
        _h("Risk questionnaire", style, 4 if style.numbered else None),
    ]
    questions = (
        (
            "How would you react to a 20% fall in the value of your investments?",
            rng.choice(["hold and wait for recovery", "sell part of the portfolio", "invest more"]),
        ),
        (
            "What is your investment time frame?",
            rng.choice(["less than 3 years", "3 to 7 years", "more than 7 years"]),
        ),
        (
            "Which best describes your investment knowledge?",
            rng.choice(["limited", "moderate", "extensive"]),
        ),
    )
    for q, a in questions:
        p2.append(Para(f"Q: {q}  A: {a}", "small"))
    p2.append(
        Para("A Statement of Advice will be prepared on the basis of this information.", "small")
    )
    pages = [p1, p2]
    if arrangement == 1:
        pages.append(
            [
                _h("Declaration", style),
                Para(
                    "I/We declare that the information provided in this fact find is complete "
                    "and accurate to the best of my/our knowledge."
                ),
                Para(SIGNATURE_LINE, "label"),
            ]
        )
    else:
        p2.append(Para(SIGNATURE_LINE, "label"))
    meta = DocMetadata(
        doc_type="fact_find", client_names=names, adviser_name=adviser, document_date=d
    )
    header = f"{LICENSEE_NAME} | Fact Find"
    return meta, _doc(doc_id, pages, header, f"{LICENSEE_AFSL} | Confidential", style)


# ----- fee disclosure statement -------------------------------------------------------------


def build_fds(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    period, start, end = _period(rng, style)
    d = end + timedelta(days=rng.randint(10, 40))
    fee = money(rng, 2_200, 6_600, 110)
    arrangement = style.variant % 2
    top: list[Block] = [Heading("Fee Disclosure Statement", 0)]
    if arrangement == 0:
        top += [
            Para(f"Client(s): {join_names(names)}", "label"),
            Para(f"Adviser: {adviser}", "label"),
            Para(f"Date issued: {fmt_date(d, style)}", "label"),
        ]
    else:
        top += [
            Para(f"Prepared for: {join_names(names)}", "label"),
            Para(f"Prepared by: {adviser}", "label"),
            Para(f"Date: {fmt_date(d, style)}", "label"),
        ]
    review_date = start + timedelta(days=rng.randint(30, 300))
    commenced = start - timedelta(days=rng.randint(100, 1000))
    product = _platform_account_product(rng, master)
    top += [
        _licensee_line(abn),
        Para(f"Disclosure period: {period}", "label"),
        Para(
            "This statement sets out the fees you paid under your ongoing fee arrangement, the "
            "services you were entitled to receive and the services you received, as required "
            "by section 962G of the Corporations Act."
        ),
        _h("Fees you paid", style),
        TableBlock(
            (
                ("Fee", "Amount paid"),
                ("Ongoing advice fee", fmt_money(fee, style)),
                ("Review meeting fee", fmt_money(Decimal(0), style)),
                ("Total", fmt_money(fee, style)),
            )
        ),
        _h("Services you were entitled to", style),
        Para("An annual review meeting with your adviser", "bullet"),
        Para("Portfolio monitoring and rebalancing recommendations", "bullet"),
        Para("Telephone and email access to your adviser", "bullet"),
        _h("Services you received", style),
        Para(f"Annual review meeting held on {fmt_date(review_date, style)}", "bullet"),
        Para("Portfolio reports issued quarterly", "bullet"),
        Para(
            f"Fees were deducted from your {product} account. Your ongoing fee arrangement "
            f"commenced on {fmt_date(commenced, style)}; your Statement of Advice sets out the "
            "basis of our advice.",
            "small",
        ),
    ]
    pages = [top]
    if arrangement == 1:
        pages.append(
            [
                _h("Renewal notice", style),
                Para(
                    "Your ongoing fee arrangement must be renewed each year. If you do not sign "
                    "the consent form within 150 days of the anniversary date the arrangement "
                    "will terminate."
                ),
                *filler(rng, 2, style),
            ]
        )
    meta = DocMetadata(doc_type="fds", client_names=names, adviser_name=adviser, document_date=d)
    header = f"{LICENSEE_NAME} | Fee Disclosure Statement"
    return meta, _doc(doc_id, pages, header, LICENSEE_AFSL, style)


# ----- fee consent --------------------------------------------------------------------------


def build_fee_consent(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    fee = money(rng, 2_200, 6_600, 110)
    product = _platform_account_product(rng, master)
    arrangement = style.variant % 2
    title = (
        "Ongoing Fee Arrangement - Consent to Deduct Fees"
        if arrangement == 0
        else "Consent to Ongoing Advice Fees"
    )
    monthly = (fee / 12).quantize(Decimal("0.01"))
    top: list[Block] = [
        Heading(title, 0),
        Para(f"Client(s): {join_names(names)}", "label"),
        Para(f"Adviser: {adviser}", "label"),
        Para(f"Account: {product}, account number {account_ref(rng)}", "label"),
        Para(f"Date signed: {fmt_date(d, style)}", "label"),
        _licensee_line(abn),
        Spacer(),
        Para(
            f"I/We consent to the deduction of ongoing advice fees of {fmt_money(fee, style)} "
            "per annum from the account named above for the period "
            f"{fmt_date(d, style)} to {fmt_date(d + timedelta(days=365), style)}."
        ),
        Para(
            f"Fee frequency: monthly ({fmt_money(monthly, style)} per month). The fee may be "
            "indexed in line with CPI."
        ),
        Para(
            "Services covered by the fee: annual review meeting, portfolio monitoring, access "
            "to your adviser, and a Fee Disclosure Statement each year."
        ),
        Para(
            "This consent ceases to have effect 150 days after the anniversary day of the "
            "arrangement unless a new consent is given."
        ),
        Spacer(),
        Para("Client signature: ________________________", "label"),
    ]
    if arrangement == 1:
        top.append(
            Para(
                f"Adviser declaration: I, {adviser}, confirm that the fee above is consistent "
                "with the ongoing fee arrangement.",
                "small",
            )
        )
    meta = DocMetadata(
        doc_type="fee_consent", client_names=names, adviser_name=adviser, document_date=d
    )
    header = f"{LICENSEE_NAME} | Ongoing fee consent"
    return meta, _doc(doc_id, [top], header, LICENSEE_AFSL, style)


# ----- super statement ----------------------------------------------------------------------


def build_super_statement(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    del abn
    style = _style(rng)
    member = person(rng)
    fund = rng.choice(master.of_type("super", on_platform=False))
    period, _start, end = _period(rng, style)
    d = end + timedelta(days=rng.randint(15, 60))
    opening = money(rng, 30_000, 700_000, 500)
    sg = money(rng, 3_000, 25_000, 100)
    personal = money(rng, 0, 20_000, 500)
    earnings = money(rng, -20_000, 60_000, 100)
    fees = (opening * fund.admin_fee_pct / 100).quantize(Decimal("1"))
    premiums = money(rng, 0, 2_400, 10)
    closing = opening + sg + personal + earnings - fees - premiums
    arrangement = style.variant % 2
    fund_abn = (
        f"{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)} "
        f"{rng.randint(100, 999)}"
    )
    summary: tuple[tuple[str, ...], ...] = (
        ("Item", "Amount"),
        ("Opening balance", fmt_money(opening, style)),
        ("Employer contributions (concessional)", fmt_money(sg, style)),
        ("Personal contributions (non-concessional)", fmt_money(personal, style)),
        ("Investment earnings", fmt_money(earnings, style)),
        ("Administration fees", fmt_money(-fees, style)),
        ("Insurance premiums", fmt_money(-premiums, style)),
        ("Closing balance", fmt_money(closing, style)),
    )
    p1: list[Block] = [
        Heading(f"{fund.name} - Annual Member Statement", 0),
        Para(f"Member: {member.full}", "label"),
        Para(f"Member number: {account_ref(rng, 'M')}", "label"),
        Para(f"Statement date: {fmt_date(d, style)}", "label"),
        Para(f"Statement period: {period}", "label"),
        Para(f"USI: {fund.usi}  Fund ABN: {fund_abn}", "small"),
        _h("Your account summary", style),
        TableBlock(summary),
        Para(
            f"Your concessional contributions for the year were {fmt_money(sg, style)} against "
            f"a cap of {fmt_money(Decimal(30000), style)}. Non-concessional contributions of "
            f"{fmt_money(personal, style)} count towards the "
            f"{fmt_money(Decimal(120000), style)} cap.",
            "small",
        ),
    ]
    cover: list[tuple[str, ...]] = [("Cover", "Sum insured", "Premium p.a.")]
    if premiums > 0:
        death = money(rng, 100_000, 800_000, 10_000)
        tpd = money(rng, 100_000, 800_000, 10_000)
        cover.append(
            ("Death", fmt_money(death, style), fmt_money(premiums * Decimal("0.6"), style))
        )
        cover.append(
            (
                "Total and permanent disablement",
                fmt_money(tpd, style),
                fmt_money(premiums * Decimal("0.4"), style),
            )
        )
    else:
        cover.append(("None", "-", "-"))
    option = rng.choice(["Balanced", "Growth", "Conservative", "High Growth"])
    nomination = rng.choice(
        [
            "valid until " + fmt_date(d + timedelta(days=rng.randint(100, 1000)), style),
            "none recorded",
        ]
    )
    p2: list[Block] = [
        _h("Insurance cover", style),
        TableBlock(tuple(cover)),
        _h("Investment option", style),
        Para(
            f"Your account is invested in the {option} option. Investment earnings are shown "
            "net of investment fees and tax."
        ),
        Para(
            "Preservation: your benefit is preserved until you reach your preservation age of "
            "60 and satisfy a condition of release. Binding death benefit nomination: "
            f"{nomination}.",
            "small",
        ),
        Para(
            f"Administration fee: {fmt_pct(fund.admin_fee_pct, style)} per annum of your "
            "account balance.",
            "small",
        ),
    ]
    pages = [p1, p2] if arrangement == 0 else [[*p1, Spacer(), *p2]]
    meta = DocMetadata(
        doc_type="super_statement", client_names=[member.full], adviser_name=None, document_date=d
    )
    return meta, _doc(doc_id, pages, f"{fund.name} | Member statement", f"USI {fund.usi}", style)


# ----- insurance schedule -------------------------------------------------------------------


def build_insurance_schedule(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    del abn
    style = _style(rng)
    owner = person(rng)
    insurer = rng.choice(N.INSURERS)
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    commence = d + timedelta(days=rng.randint(1, 30))
    arrangement = style.variant % 2
    life = money(rng, 250_000, 1_500_000, 50_000)
    tpd = money(rng, 100_000, 1_000_000, 50_000)
    ip = money(rng, 3_000, 12_000, 250)
    rows: list[tuple[str, ...]] = [
        ("Benefit", "Sum insured", "Premium p.a."),
        ("Life cover", fmt_money(life, style), fmt_money(life * Decimal("0.0015"), style)),
        (
            "Total and permanent disablement",
            fmt_money(tpd, style),
            fmt_money(tpd * Decimal("0.0012"), style),
        ),
    ]
    if rng.random() < 0.6:
        rows.append(
            (
                "Income protection (monthly benefit)",
                fmt_money(ip, style),
                fmt_money(ip * Decimal("0.35"), style),
            )
        )
    frequency = rng.choice(["monthly", "annual"])
    premium_type = rng.choice(["stepped", "level"])
    replaced = rng.choice(master.of_type("insurance")).name
    top: list[Block] = [
        Heading(f"{insurer} - Policy Schedule", 0),
        Para(f"Policy number: POL-{rng.randint(100000, 999999)}", "label"),
        Para(f"Policy owner: {owner.full}", "label"),
        Para(f"Life insured: {owner.full}", "label"),
        Para(f"Adviser: {adviser} ({LICENSEE_NAME})", "label"),
        Para(f"Issue date: {fmt_date(d, style)}", "label"),
        Para(f"Commencement date: {fmt_date(commence, style)}", "label"),
        _h("Benefits", style),
        TableBlock(tuple(rows)),
        Para(
            f"Premium frequency: {frequency}. Premium type: {premium_type}. Waiting period: "
            "30 days. Benefit period: to age 65.",
            "small",
        ),
        Para(
            f"This policy replaces the cover previously held under {replaced}, as recommended "
            "in your Statement of Advice.",
            "small",
        ),
    ]
    pages = [top]
    if arrangement == 1:
        pages.append([_h("Policy conditions", style), *filler(rng, 4, style)])
    else:
        top.extend(filler(rng, 2, style))
    meta = DocMetadata(
        doc_type="insurance_schedule",
        client_names=[owner.full],
        adviser_name=adviser,
        document_date=d,
    )
    return meta, _doc(doc_id, pages, f"{insurer} | Policy schedule", "Policy schedule", style)


# ----- authority to proceed -----------------------------------------------------------------


def build_authority_to_proceed(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    soa_date = d - timedelta(days=rng.randint(3, 30))
    arrangement = style.variant % 2
    top: list[Block] = [
        Heading("Authority to Proceed", 0),
        Para(f"Client(s): {join_names(names)}", "label"),
        Para(f"Adviser: {adviser}", "label"),
        Para(f"Date signed: {fmt_date(d, style)}", "label"),
        _licensee_line(abn),
        Para(
            "I/We have received and read the Statement of Advice dated "
            f"{fmt_date(soa_date, style)} prepared by {adviser} and authorise "
            f"{LICENSEE_NAME} to implement the following "
            "recommendations:"
        ),
    ]
    products = rng.sample([p for p in master.products if p.on_platform], k=rng.randint(2, 4))
    for p in products:
        verb = rng.choice(["Establish", "Contribute to", "Rollover to", "Insure under"])
        top.append(
            Para(f"{verb} {p.name} ({PRODUCT_TYPE_LABELS[p.product_type].lower()})", "bullet")
        )
    initial_fee = fmt_money(money(rng, 1_100, 4_400, 110), style)
    top.append(
        Para(
            f"I/We understand that an initial advice fee of {initial_fee} is payable on "
            "implementation."
        )
    )
    if arrangement == 1:
        top.append(
            Para(
                "I/We acknowledge that the product disclosure statements for each recommended "
                "product have been provided to me/us."
            )
        )
    top.append(Spacer())
    for nm in names:
        top.append(Para(f"Signed: {nm}    Date: {fmt_date(d, style)}", "label"))
    meta = DocMetadata(
        doc_type="authority_to_proceed", client_names=names, adviser_name=adviser, document_date=d
    )
    header = f"{LICENSEE_NAME} | Authority to proceed"
    return meta, _doc(doc_id, [top], header, LICENSEE_AFSL, style)


# ----- bank statement -----------------------------------------------------------------------

DESCRIPTIONS = (
    "GROCER MARKET", "DIRECT DEBIT ELECTRICITY", "ATM WITHDRAWAL", "TRANSFER TO SAVINGS",
    "FUEL STATION", "PHARMACY", "ONLINE RETAIL", "COUNCIL RATES", "INSURANCE PREMIUM",
    "MOBILE PHONE", "RESTAURANT", "TRAIN FARE",
)  # fmt: skip


def build_bank_statement(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    del abn
    style = _style(rng)
    holder = person(rng)
    bank = rng.choice(N.BANKS)
    end = random_date(rng)
    start = end - timedelta(days=30)
    d = end + timedelta(days=rng.randint(1, 5))
    arrangement = style.variant % 2
    fund = rng.choice(master.of_type("super", on_platform=False))
    bsb = f"06{rng.randint(1, 9)}-{rng.randint(100, 999)}"
    account_no = f"{rng.randint(1000, 9999)} {rng.randint(1000, 9999)}"
    balance = money(rng, 1_000, 30_000, 10)
    opening = balance
    rows: list[tuple[str, ...]] = [("Date", "Description", "Debit", "Credit", "Balance")]
    n_rows = rng.randint(10, 18)
    for i in range(n_rows):
        when = start + timedelta(days=int(30 * i / n_rows))
        roll = rng.random()
        if roll < 0.12:
            desc = f"SALARY {holder.employer.upper()}"
            credit, debit = money(rng, 2_000, 8_000, 10), Decimal(0)
        elif roll < 0.2:
            desc, credit, debit = "NORTHSHORE ADVICE FEE", Decimal(0), money(rng, 150, 550, 10)
        elif roll < 0.28:
            desc = f"{fund.name.upper()} CONTRIBUTION"
            credit, debit = Decimal(0), money(rng, 200, 2_000, 50)
        else:
            desc, credit, debit = rng.choice(DESCRIPTIONS), Decimal(0), money(rng, 10, 600, 5)
        balance = balance + credit - debit
        rows.append(
            (
                fmt_date(when, style),
                desc,
                fmt_money(debit, style) if debit else "",
                fmt_money(credit, style) if credit else "",
                fmt_money(balance, style),
            )
        )
    top: list[Block] = [
        Heading(f"{bank} - Account Statement", 0),
        Para(f"Account holder: {holder.full}", "label"),
        Para(f"Account: Everyday Account  BSB {bsb}  Account number {account_no}", "label"),
        Para(f"Statement date: {fmt_date(d, style)}", "label"),
        Para(f"Statement period: {fmt_date(start, style)} to {fmt_date(end, style)}", "label"),
        _h("Transactions", style),
        TableBlock(tuple(rows)),
        Para(
            f"Opening balance {fmt_money(opening, style)}; closing balance "
            f"{fmt_money(balance, style)}.",
            "small",
        ),
    ]
    pages = [top]
    if arrangement == 1:
        pages.append(
            [
                _h("Important information", style),
                Para(
                    "Please check the entries on this statement and report any discrepancy "
                    "within 30 days. Interest is calculated daily and credited monthly. Fees "
                    "are described in the account terms and conditions."
                ),
            ]
        )
    meta = DocMetadata(
        doc_type="bank_statement", client_names=[holder.full], adviser_name=None, document_date=d
    )
    return meta, _doc(doc_id, pages, f"{bank} | Account statement", "Statement", style)


# ----- correspondence -----------------------------------------------------------------------


def build_correspondence(
    doc_id: str, rng: random.Random, abn: str, master: ProductMaster
) -> tuple[DocMetadata, LayoutDocument]:
    style = _style(rng)
    people = clients(rng)
    names = [p.full for p in people]
    adviser = rng.choice(N.ADVISERS)
    d = random_date(rng)
    topic = rng.choice(N.LETTER_TOPICS)
    product = rng.choice(master.products).name
    needed = rng.choice(
        ["bank statement", "insurance policy schedule", "superannuation member statement"]
    )
    arrangement = style.variant % 2
    first_names = " and ".join(p.first for p in people)
    body = [
        Para(
            f"Thank you for your time regarding {topic}. I have set out below the points we "
            "discussed and what happens next."
        ),
        Para(
            rng.choice(
                [
                    f"As discussed, the {product} remains appropriate for your circumstances "
                    "and no change is recommended at this stage. If you would like us to "
                    "reconsider this, we can prepare a Record of Advice.",
                    f"I have requested the latest statement for your {product} and will confirm "
                    "the balance once it arrives. Please let me know if your contact details "
                    "have changed.",
                    f"Before we can proceed we need a copy of your most recent {needed}. Once "
                    "received I will update your file and confirm the next steps.",
                ]
            )
        ),
        Para("Please do not hesitate to contact me if you have any questions."),
    ]
    if arrangement == 0:
        addr = address(rng)
        top: list[Block] = [
            Para(LICENSEE_NAME, "label"),
            Para(f"ABN {abn}  {LICENSEE_AFSL}", "small"),
            Para(f"Date: {fmt_date(d, style)}", "label"),
            Spacer(),
            Para(join_names(names)),
            Para(addr.lines[0]),
            Para(addr.lines[1]),
            Spacer(),
            Para(f"Dear {first_names},"),
            *body,
            Para("Kind regards,"),
            Para(adviser),
            Para(f"Financial Adviser, {LICENSEE_NAME}", "small"),
        ]
    else:
        email = adviser.lower().replace(" ", ".")
        top = [
            Para(f"From: {adviser} <{email}@northshore-advice.example>", "label"),
            Para(f"To: {'; '.join(names)}", "label"),
            Para(f"Date: {fmt_date(d, style)}", "label"),
            Para(f"Subject: Re: {topic}", "label"),
            Spacer(),
            Para(f"Hi {first_names},"),
            *body,
            Para("Regards,"),
            Para(adviser),
            Para(f"{LICENSEE_NAME} | ABN {abn} | {LICENSEE_AFSL}", "small"),
        ]
    meta = DocMetadata(
        doc_type="correspondence", client_names=names, adviser_name=adviser, document_date=d
    )
    return meta, _doc(doc_id, [top], LICENSEE_NAME, "Private and confidential", style)


TEMPLATES: dict[str, Template] = {
    "roa": build_roa,
    "fact_find": build_fact_find,
    "fds": build_fds,
    "fee_consent": build_fee_consent,
    "super_statement": build_super_statement,
    "insurance_schedule": build_insurance_schedule,
    "authority_to_proceed": build_authority_to_proceed,
    "bank_statement": build_bank_statement,
    "correspondence": build_correspondence,
}
