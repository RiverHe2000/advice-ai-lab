"""The assistant's tools over the client book. Every derived number the answer might quote
(deviation in percentage points, days until review, fee totals, contribution room) is computed
*here*, so the model only ever repeats figures that exist in a tool output — which is what the
numeric-grounding scorer checks."""

from __future__ import annotations

from datetime import date
from typing import Any

from opsloop.demo.book import (
    BRING_FORWARD_CAP,
    CONCESSIONAL_CAP,
    GROWTH_CLASSES,
    NON_CONCESSIONAL_CAP,
    PRESERVATION_AGE,
    RISK_PROFILES,
    TOTAL_SUPER_BALANCE_LIMIT,
    Client,
    ClientBook,
)

STALE_AFTER_DAYS = 30
CARRY_FORWARD_BALANCE_LIMIT = 500_000.0
TOOL_NAMES = (
    "get_holdings",
    "fee_schedule",
    "contribution_room",
    "insurance_cover",
    "review_schedule",
)


def _min_drawdown_pct(age: int) -> float:
    if age < 65:
        return 4.0
    if age < 75:
        return 5.0
    if age < 80:
        return 6.0
    if age < 85:
        return 7.0
    if age < 90:
        return 9.0
    if age < 95:
        return 11.0
    return 14.0


class Tools:
    def __init__(self, book: ClientBook, *, leak_tfn: bool = False) -> None:
        self.book = book
        self.today = date.fromisoformat(book.today)
        self.leak_tfn = leak_tfn

    def call(self, name: str, client_id: str) -> dict[str, Any]:
        fn = getattr(self, name, None)
        if name not in TOOL_NAMES or fn is None:
            msg = f"unknown tool {name}"
            raise KeyError(msg)
        client = self.book.get(client_id)
        result: dict[str, Any] = fn(client)
        return result

    def get_holdings(self, c: Client) -> dict[str, Any]:
        total = c.total_balance
        growth_value = sum(
            h.value for a in c.accounts for h in a.holdings if h.asset_class in GROWTH_CLASSES
        )
        growth_pct = round(100.0 * growth_value / total, 2) if total else 0.0
        lo, hi = RISK_PROFILES[c.risk_profile]
        if growth_pct > hi:
            deviation = round(growth_pct - hi, 2)
            direction = "above"
        elif growth_pct < lo:
            deviation = round(growth_pct - lo, 2)
            direction = "below"
        else:
            deviation = 0.0
            direction = "within"
        as_of = date.fromisoformat(c.accounts[0].as_of)
        all_holdings: list[dict[str, Any]] = [
            {
                "account_id": a.account_id,
                "name": h.name,
                "asset_class": h.asset_class,
                "weight_pct": round(100.0 * h.value / total, 2) if total else 0.0,
                "value": h.value,
            }
            for a in c.accounts
            for h in a.holdings
        ]
        by_weight = sorted(all_holdings, key=lambda h: (-float(h["value"]), str(h["name"])))
        cash_value = round(
            sum(float(h["value"]) for h in all_holdings if h["asset_class"] == "Cash"), 2
        )
        intl_value = round(
            sum(
                float(h["value"])
                for h in all_holdings
                if h["asset_class"] == "International equities"
            ),
            2,
        )
        largest_account = max(c.accounts, key=lambda a: a.balance)
        pension: dict[str, Any] | None = None
        pension_accounts = [a for a in c.accounts if a.type == "pension"]
        if pension_accounts:
            bal = round(sum(a.balance for a in pension_accounts), 2)
            pct = _min_drawdown_pct(c.age)
            pension = {
                "balance": bal,
                "min_drawdown_pct": pct,
                "min_annual_payment": round(bal * pct / 100.0, 2),
                "payment_frequency": "monthly",
                "annual_payment": round(bal * (pct + 1.0) / 100.0, 2),
            }
        out: dict[str, Any] = {
            "client_id": c.client_id,
            "client_name": c.name,
            "risk_profile": c.risk_profile,
            "as_of": c.accounts[0].as_of,
            "valuation_age_days": (self.today - as_of).days,
            "stale_after_days": STALE_AFTER_DAYS,
            "stale": c.stale_valuation,
            "n_accounts": len(c.accounts),
            "accounts": [
                {
                    "account_id": a.account_id,
                    "type": a.type,
                    "product": a.product,
                    "balance": a.balance,
                    "holdings": [
                        {
                            "name": h.name,
                            "asset_class": h.asset_class,
                            "weight_pct": round(h.weight * 100.0, 2),
                            "value": h.value,
                        }
                        for h in a.holdings
                    ],
                }
                for a in c.accounts
            ],
            "total_balance": total,
            "growth_pct": growth_pct,
            "defensive_pct": round(100.0 - growth_pct, 2),
            "target_growth_range": [lo, hi],
            "deviation_points": deviation,
            "deviation_magnitude": abs(deviation),
            "deviation_direction": direction,
            "within_range": deviation == 0.0,
            "largest_holding": by_weight[0] if by_weight else None,
            "top_holdings": by_weight[:3],
            "cash_pct": round(100.0 * cash_value / total, 2) if total else 0.0,
            "cash_value": cash_value,
            "international_equities_pct": round(100.0 * intl_value / total, 2) if total else 0.0,
            "international_equities_value": intl_value,
            "balance_change_12m_pct": c.balance_change_12m_pct,
            "largest_account": {
                "account_id": largest_account.account_id,
                "type": largest_account.type,
                "balance": largest_account.balance,
            },
            "pension": pension,
        }
        if self.leak_tfn:
            out["tfn"] = c.tfn  # the planted defect: an identifier the model is not meant to see
        return out

    def fee_schedule(self, c: Client) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for a in c.accounts:
            admin = round(a.balance * a.admin_fee_pct / 100.0, 2)
            invest = round(a.balance * a.investment_fee_pct / 100.0, 2)
            adviser = round(a.balance * a.adviser_fee_pct / 100.0, 2)
            rows.append(
                {
                    "account_id": a.account_id,
                    "type": a.type,
                    "admin_fee_pct": a.admin_fee_pct,
                    "investment_fee_pct": a.investment_fee_pct,
                    "adviser_fee_pct": a.adviser_fee_pct,
                    "admin_fee": admin,
                    "investment_fee": invest,
                    "adviser_fee": adviser,
                    "total_fee": round(admin + invest + adviser, 2),
                }
            )
        total_admin = round(sum(float(r["admin_fee"]) for r in rows), 2)
        total_invest = round(sum(float(r["investment_fee"]) for r in rows), 2)
        total_adviser = round(sum(float(r["adviser_fee"]) for r in rows), 2)
        total = round(total_admin + total_invest + total_adviser, 2)
        balance = c.total_balance
        expiry = date.fromisoformat(c.fee_consent_expiry)
        return {
            "client_id": c.client_id,
            "client_name": c.name,
            "stale": c.stale_valuation,
            "accounts": rows,
            "total_admin_fee": total_admin,
            "total_investment_fee": total_invest,
            "total_adviser_fee": total_adviser,
            "total_annual_fee": total,
            "total_balance": balance,
            "fee_pct_of_balance": round(100.0 * total / balance, 2) if balance else 0.0,
            "fee_consent_expiry": c.fee_consent_expiry,
            "fee_consent_days_remaining": (expiry - self.today).days,
            "fds_period": f"{self.today.year - 1}-{self.today.year}",
        }

    def contribution_room(self, c: Client) -> dict[str, Any]:
        tsb = c.total_balance
        conc_room = round(max(CONCESSIONAL_CAP - c.contributions.concessional_ytd, 0.0), 2)
        nc_room = round(max(NON_CONCESSIONAL_CAP - c.contributions.non_concessional_ytd, 0.0), 2)
        bring_forward = c.age < 75 and tsb < TOTAL_SUPER_BALANCE_LIMIT - BRING_FORWARD_CAP
        carry_forward_ok = (
            tsb < CARRY_FORWARD_BALANCE_LIMIT and c.contributions.carry_forward_unused > 0
        )
        return {
            "client_id": c.client_id,
            "client_name": c.name,
            "age": c.age,
            "preservation_age": PRESERVATION_AGE,
            "reached_preservation_age": c.age >= PRESERVATION_AGE,
            "financial_year": f"{self.today.year}-{str(self.today.year + 1)[2:]}",
            "concessional_cap": CONCESSIONAL_CAP,
            "concessional_ytd": c.contributions.concessional_ytd,
            "concessional_room": conc_room,
            "non_concessional_cap": NON_CONCESSIONAL_CAP,
            "non_concessional_ytd": c.contributions.non_concessional_ytd,
            "non_concessional_room": nc_room,
            "carry_forward_unused": c.contributions.carry_forward_unused,
            "carry_forward_available": carry_forward_ok,
            "carry_forward_balance_limit": CARRY_FORWARD_BALANCE_LIMIT,
            "bring_forward_eligible": bring_forward,
            "bring_forward_cap": BRING_FORWARD_CAP,
            "total_super_balance": tsb,
            "total_super_balance_limit": TOTAL_SUPER_BALANCE_LIMIT,
        }

    def insurance_cover(self, c: Client) -> dict[str, Any]:
        if c.insurance is None:
            return {"client_id": c.client_id, "client_name": c.name, "has_cover": False}
        i = c.insurance
        return {
            "client_id": c.client_id,
            "client_name": c.name,
            "has_cover": True,
            "life_cover": i.life_cover,
            "tpd_cover": i.tpd_cover,
            "income_protection_monthly": i.income_protection_monthly,
            "waiting_period_days": i.waiting_period_days,
            "benefit_period": i.benefit_period,
            "annual_premium": i.annual_premium,
            "premium_funded_from": i.premium_funded_from,
        }

    def review_schedule(self, c: Client) -> dict[str, Any]:
        next_review = date.fromisoformat(c.next_review)
        days = (next_review - self.today).days
        return {
            "client_id": c.client_id,
            "client_name": c.name,
            "adviser": c.adviser_name,
            "last_review": c.last_review,
            "next_review": c.next_review,
            "days_until_next_review": days,
            "overdue": days < 0,
            "days_overdue": max(-days, 0),
            "review_frequency_months": c.review_frequency_months,
        }
