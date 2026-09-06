"""Deterministic validators over an ``SoAExtraction``: pure functions returning
``Violation(code, severity, field, message)``. ``error`` violations are *hard* (they block
auto-acceptance and trigger a targeted re-ask in the ``llm_validated`` strategy);
``warning`` violations are recorded and fed to the router as features."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.identifiers import abn_is_valid, find_abn_like, find_tfn_like
from advicedoc.schema import RISK_PROFILES, SoAExtraction

Severity = Literal["error", "warning"]
INVEST_ACTIONS = frozenset({"establish", "contribute", "rollover", "switch", "retain"})
NEW_MONEY_ACTIONS = frozenset({"establish", "contribute", "rollover"})


@dataclass(frozen=True, slots=True)
class Violation:
    code: str
    severity: Severity
    field: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def section_of(field: str) -> str:
    """Which SoA section a violated field belongs to (for targeted re-asks)."""
    head = field.split(".")[0].split("[")[0]
    return {
        "client_names": "header",
        "adviser_name": "header",
        "licensee": "header",
        "advice_date": "header",
        "risk_profile": "risk",
        "scope": "scope",
        "recommendations": "recommendations",
        "fees": "fees",
        "replacements": "replacement",
        "authority_to_proceed_signed": "authority",
        "document": "document",
    }.get(head, "document")


def hard(violations: list[Violation]) -> list[Violation]:
    return [v for v in violations if v.severity == "error"]


def check_required_fields(x: SoAExtraction) -> list[Violation]:
    out: list[Violation] = []
    if not x.client_names:
        out.append(Violation("missing_field", "error", "client_names", "no client names"))
    if not x.adviser_name:
        out.append(Violation("missing_field", "error", "adviser_name", "no adviser name"))
    if x.advice_date is None:
        out.append(Violation("missing_field", "error", "advice_date", "no advice date"))
    if x.risk_profile is None:
        out.append(Violation("missing_field", "error", "risk_profile", "no risk profile"))
    elif x.risk_profile not in RISK_PROFILES:  # pragma: no cover - enforced by pydantic
        out.append(Violation("risk_profile_invalid", "error", "risk_profile", x.risk_profile))
    if not x.recommendations:
        out.append(Violation("missing_field", "error", "recommendations", "no recommendations"))
    if x.fees is None:
        out.append(Violation("missing_field", "error", "fees", "no fee schedule"))
    return out


def invested_total(x: SoAExtraction) -> Decimal:
    return sum(
        (r.amount or Decimal(0))
        for r in x.recommendations
        if r.action in INVEST_ACTIONS and r.product_type != "insurance"
    ) or Decimal(0)


def check_fees(x: SoAExtraction, *, tolerance: float = 0.02) -> list[Violation]:
    out: list[Violation] = []
    fees = x.fees
    if fees is None:
        return out
    if fees.initial_advice_fee < 0:
        out.append(Violation("fee_negative", "error", "fees.initial_advice_fee", "negative fee"))
    if fees.ongoing_advice_fee_pa < 0:
        out.append(Violation("fee_negative", "error", "fees.ongoing_advice_fee_pa", "negative fee"))
    if fees.ongoing_fee_basis == "percent":
        if fees.ongoing_fee_percent is None:
            out.append(
                Violation(
                    "fee_basis_inconsistent",
                    "error",
                    "fees.ongoing_fee_percent",
                    "basis is percent but no percentage given",
                )
            )
        else:
            base = invested_total(x)
            if base > 0:
                implied = fees.ongoing_fee_percent / 100 * base
                gap = abs(implied - fees.ongoing_advice_fee_pa)
                if gap > max(Decimal(1), implied * Decimal(str(tolerance))):
                    out.append(
                        Violation(
                            "fee_arithmetic",
                            "error",
                            "fees.ongoing_advice_fee_pa",
                            f"{fees.ongoing_fee_percent}% of {base} is {implied:.0f}, "
                            f"document says {fees.ongoing_advice_fee_pa}",
                        )
                    )
    elif fees.ongoing_fee_percent is not None:
        out.append(
            Violation(
                "fee_basis_inconsistent",
                "warning",
                "fees.ongoing_fee_percent",
                "basis is flat but a percentage is given",
            )
        )
    return out


def check_amounts(x: SoAExtraction, *, available_funds: Decimal | None) -> list[Violation]:
    out: list[Violation] = []
    for i, r in enumerate(x.recommendations):
        if r.amount is not None and r.amount < 0:
            out.append(
                Violation("amount_negative", "error", f"recommendations[{i}].amount", "negative")
            )
    if available_funds is not None:
        new_money = sum(
            (r.amount or Decimal(0))
            for r in x.recommendations
            if r.action in NEW_MONEY_ACTIONS and r.product_type != "insurance"
        )
        if new_money > available_funds:
            out.append(
                Violation(
                    "amount_exceeds_available_funds",
                    "error",
                    "recommendations",
                    f"recommended {new_money} exceeds available funds {available_funds}",
                )
            )
    return out


def check_products(
    x: SoAExtraction, *, master: ProductMaster = DEFAULT_MASTER, threshold: float = 90.0
) -> list[Violation]:
    out: list[Violation] = []
    for i, r in enumerate(x.recommendations):
        product, score = master.match(r.product_name, threshold=threshold)
        if product is None:
            out.append(
                Violation(
                    "product_unknown",
                    "error",
                    f"recommendations[{i}].product_name",
                    f"'{r.product_name}' does not resolve to the product master (best {score:.0f})",
                )
            )
        elif product.product_type != r.product_type:
            out.append(
                Violation(
                    "product_type_mismatch",
                    "error",
                    f"recommendations[{i}].product_type",
                    f"'{product.name}' is {product.product_type}, extraction says {r.product_type}",
                )
            )
    for i, rep in enumerate(x.replacements):
        for side in ("from_product", "to_product"):
            name = getattr(rep, side)
            if name.strip() and master.match(name, threshold=threshold)[0] is None:
                out.append(
                    Violation(
                        "product_unknown",
                        "error",
                        f"replacements[{i}].{side}",
                        f"'{name}' does not resolve to the product master",
                    )
                )
    return out


def check_replacements(x: SoAExtraction) -> list[Violation]:
    out: list[Violation] = []
    for i, rep in enumerate(x.replacements):
        if not rep.from_product.strip() or not rep.to_product.strip():
            out.append(
                Violation(
                    "replacement_incomplete",
                    "error",
                    f"replacements[{i}]",
                    "both current and recommended product are required",
                )
            )
        if not rep.reason.strip():
            out.append(
                Violation(
                    "replacement_reason_missing",
                    "warning",
                    f"replacements[{i}].reason",
                    "no reason recorded",
                )
            )
    return out


def check_dates(x: SoAExtraction, *, document_date: date | None) -> list[Violation]:
    if x.advice_date is None or document_date is None:
        return []
    if abs(x.advice_date - document_date) > timedelta(days=2 * 365):
        return [
            Violation(
                "date_implausible",
                "error",
                "advice_date",
                f"{x.advice_date} is more than two years from the document date {document_date}",
            )
        ]
    return []


def check_identifiers(document_text: str) -> list[Violation]:
    out: list[Violation] = []
    for candidate in find_abn_like(document_text):
        if not abn_is_valid(candidate):
            out.append(
                Violation("abn_invalid", "warning", "document", f"ABN {candidate} fails checksum")
            )
    if find_tfn_like(document_text):
        out.append(
            Violation("tfn_present", "error", "document", "a TFN-shaped number appears in the text")
        )
    return out


def validate_extraction(
    x: SoAExtraction,
    *,
    master: ProductMaster = DEFAULT_MASTER,
    document_text: str = "",
    available_funds: Decimal | None = None,
    document_date: date | None = None,
    fee_tolerance: float = 0.02,
    product_threshold: float = 90.0,
) -> list[Violation]:
    return [
        *check_required_fields(x),
        *check_fees(x, tolerance=fee_tolerance),
        *check_amounts(x, available_funds=available_funds),
        *check_products(x, master=master, threshold=product_threshold),
        *check_replacements(x),
        *check_dates(x, document_date=document_date),
        *check_identifiers(document_text),
    ]


def violations_by_section(violations: list[Violation]) -> dict[str, list[Violation]]:
    grouped: dict[str, list[Violation]] = {}
    for v in violations:
        grouped.setdefault(section_of(v.field), []).append(v)
    return grouped
