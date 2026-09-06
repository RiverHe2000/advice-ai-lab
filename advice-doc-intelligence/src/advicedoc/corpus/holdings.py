"""Platform holdings simulator: what the platform shows for an SoA client 90 days after the
advice date, with discrepancies planted at a known rate and recorded as ground truth.

Market movement is modelled as multiplicative noise on each implemented amount (sd 2.5 %,
unclamped), so a small share of *faithfully implemented* recommendations drift past a 5 %
tolerance: that is the false-alarm source the reconciliation evaluation measures.
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.corpus.soa import INVEST_ACTIONS
from advicedoc.schema import (
    DiscrepancyKind,
    Holding,
    HoldingsSnapshot,
    PlantedDiscrepancy,
    SoAExtraction,
)

FEE_KEY = "advice_fee"


def expected_holdings(gold: SoAExtraction) -> dict[str, Decimal]:
    """Expected balance per product implied by the recommendations (aggregated per product)."""
    expected: dict[str, Decimal] = {}
    for r in gold.recommendations:
        if r.amount is None:
            continue
        if r.action in INVEST_ACTIONS or r.action == "insure":
            expected[r.product_name] = expected.get(r.product_name, Decimal(0)) + r.amount
    return expected


def _money(x: Decimal) -> Decimal:
    return x.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def simulate_holdings(
    gold: SoAExtraction,
    doc_id: str,
    rng: random.Random,
    *,
    p_discrepancy: float = 0.35,
    noise_sd: float = 0.025,
    master: ProductMaster = DEFAULT_MASTER,
) -> HoldingsSnapshot:
    assert gold.advice_date is not None
    assert gold.fees is not None
    holdings: list[Holding] = []
    for name, amount in expected_holdings(gold).items():
        product = master.get(name)
        assert product is not None
        factor = Decimal(str(round(1.0 + rng.gauss(0.0, noise_sd), 4)))
        holdings.append(
            Holding(
                product_name=name,
                product_code=product.code,
                product_type=product.product_type,
                balance=_money(amount * factor),
                account_ref=f"NW{rng.randint(100000, 999999)}",
            )
        )
    fee_charged = gold.fees.ongoing_advice_fee_pa + Decimal(rng.randint(-1, 1))
    planted: list[PlantedDiscrepancy] = []

    expected_names = set(expected_holdings(gold))

    def implemented() -> list[Holding]:
        # Only holdings the advice expects can be "not implemented" or "mismatched"; an
        # unexpected product planted earlier in the same document is never the victim.
        return [h for h in holdings if h.product_name in expected_names]

    if holdings and rng.random() < p_discrepancy:
        kinds: list[DiscrepancyKind] = [
            "not_implemented",
            "amount_mismatch",
            "unexpected_product",
            "fee_mismatch",
        ]
        rng.shuffle(kinds)
        n_plant = 1 if rng.random() < 0.7 else 2
        for kind in kinds[:n_plant]:
            if kind == "not_implemented" and implemented():
                victim = rng.choice(implemented())
                holdings.remove(victim)
                planted.append(
                    PlantedDiscrepancy(
                        kind=kind,
                        product_name=victim.product_name,
                        expected=str(victim.balance),
                        observed="absent",
                    )
                )
            elif kind == "amount_mismatch" and implemented():
                victim = rng.choice(implemented())
                factor = Decimal(str(rng.choice([0.65, 0.75, 0.85, 0.92, 1.08, 1.15, 1.25, 1.35])))
                new_balance = _money(victim.balance * factor)
                planted.append(
                    PlantedDiscrepancy(
                        kind=kind,
                        product_name=victim.product_name,
                        expected=str(victim.balance),
                        observed=str(new_balance),
                    )
                )
                victim.balance = new_balance
            elif kind == "unexpected_product":
                # Never a product the advice expects: a not_implemented product put back
                # with a random balance would read as an amount mismatch, not as unexpected.
                present = {h.product_name for h in holdings} | set(expected_holdings(gold))
                candidates = [
                    p
                    for p in master.products
                    if p.on_platform
                    and p.product_type in {"super", "idps", "managed_portfolio", "cash"}
                    and p.name not in present
                ]
                extra = rng.choice(candidates)
                balance = Decimal(rng.randrange(5_000, 80_000, 500))
                holdings.append(
                    Holding(
                        product_name=extra.name,
                        product_code=extra.code,
                        product_type=extra.product_type,
                        balance=balance,
                        account_ref=f"NW{rng.randint(100000, 999999)}",
                    )
                )
                planted.append(
                    PlantedDiscrepancy(
                        kind=kind, product_name=extra.name, expected="absent", observed=str(balance)
                    )
                )
            elif kind == "fee_mismatch":
                agreed = gold.fees.ongoing_advice_fee_pa
                wrong = (
                    _money(agreed * Decimal(str(rng.choice([1.15, 1.3, 1.6, 0.7]))))
                    if rng.random() < 0.7
                    else agreed + Decimal(1200)
                )
                planted.append(
                    PlantedDiscrepancy(
                        kind=kind, product_name=FEE_KEY, expected=str(agreed), observed=str(wrong)
                    )
                )
                fee_charged = wrong
    return HoldingsSnapshot(
        doc_id=doc_id,
        client_names=list(gold.client_names),
        as_of=gold.advice_date + timedelta(days=90),
        holdings=holdings,
        advice_fee_charged_pa=fee_charged,
        planted=planted,
    )
