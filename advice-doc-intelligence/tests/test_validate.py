from __future__ import annotations

import random
from datetime import date
from decimal import Decimal

from advicedoc.identifiers import generate_tfn
from advicedoc.schema import (
    FeeSchedule,
    ProductReplacement,
    Recommendation,
    SoAExtraction,
)
from advicedoc.validate import (
    check_amounts,
    check_dates,
    check_fees,
    check_identifiers,
    check_products,
    check_replacements,
    check_required_fields,
    hard,
    section_of,
    validate_extraction,
    violations_by_section,
)


def _good() -> SoAExtraction:
    return SoAExtraction(
        client_names=["Alice Oakes"],
        adviser_name="Margaret Thorne",
        licensee="Northshore Financial Advice Pty Ltd",
        advice_date=date(2026, 3, 1),
        risk_profile="Balanced",
        scope=["superannuation"],
        recommendations=[
            Recommendation(
                action="rollover",
                product_name="Northshore Wealth Super",
                product_type="super",
                amount=Decimal(200000),
            ),
            Recommendation(
                action="insure",
                product_name="Northshore Life Cover",
                product_type="insurance",
                amount=Decimal(500000),
            ),
        ],
        fees=FeeSchedule(
            initial_advice_fee=Decimal(2200),
            ongoing_advice_fee_pa=Decimal(1600),
            ongoing_fee_basis="percent",
            ongoing_fee_percent=Decimal("0.80"),
            platform_admin_fee_pct=Decimal("0.30"),
        ),
        replacements=[
            ProductReplacement(
                from_product="Aurora Super Fund",
                to_product="Northshore Wealth Super",
                fee_difference_pa=Decimal(-1100),
                insurance_impact="none",
                reason="lower fees",
            )
        ],
        authority_to_proceed_signed=False,
    )


def _codes(violations: list) -> set[str]:  # type: ignore[type-arg]
    return {v.code for v in violations}


def test_good_extraction_has_no_violations() -> None:
    assert (
        validate_extraction(
            _good(), available_funds=Decimal(250000), document_date=date(2026, 3, 1)
        )
        == []
    )


def test_required_fields() -> None:
    empty = SoAExtraction()
    fields = {v.field for v in check_required_fields(empty)}
    assert fields == {
        "client_names",
        "adviser_name",
        "advice_date",
        "risk_profile",
        "recommendations",
        "fees",
    }
    assert all(v.severity == "error" for v in check_required_fields(empty))


def test_fee_arithmetic_and_basis() -> None:
    x = _good()
    assert check_fees(x) == []
    x.fees.ongoing_advice_fee_pa = Decimal(2400)  # type: ignore[union-attr]
    assert _codes(check_fees(x)) == {"fee_arithmetic"}
    x = _good()
    x.fees.ongoing_fee_percent = None  # type: ignore[union-attr]
    assert _codes(check_fees(x)) == {"fee_basis_inconsistent"}
    x = _good()
    x.fees.ongoing_fee_basis = "flat"  # type: ignore[union-attr]
    warnings = check_fees(x)
    assert _codes(warnings) == {"fee_basis_inconsistent"} and warnings[0].severity == "warning"
    x = _good()
    x.fees.initial_advice_fee = Decimal(-1)  # type: ignore[union-attr]
    x.fees.ongoing_advice_fee_pa = Decimal(-1)  # type: ignore[union-attr]
    assert [v.code for v in check_fees(x)][:2] == ["fee_negative", "fee_negative"]
    assert check_fees(SoAExtraction()) == []
    no_base = _good()
    no_base.recommendations = []
    assert check_fees(no_base) == []


def test_amounts_against_available_funds() -> None:
    x = _good()
    assert check_amounts(x, available_funds=Decimal(250000)) == []
    assert _codes(check_amounts(x, available_funds=Decimal(100000))) == {
        "amount_exceeds_available_funds"
    }
    assert check_amounts(x, available_funds=None) == []
    x.recommendations[0].amount = Decimal(-5)
    assert _codes(check_amounts(x, available_funds=None)) == {"amount_negative"}


def test_product_resolution_and_type() -> None:
    x = _good()
    assert check_products(x) == []
    x.recommendations[0].product_name = "Zenith Alpha Fund"
    assert _codes(check_products(x)) == {"product_unknown"}
    x = _good()
    x.recommendations[0].product_type = "pension"
    assert _codes(check_products(x)) == {"product_type_mismatch"}
    x = _good()
    x.recommendations[0].product_name = "Northshore Wealth Supre"  # OCR-like typo still resolves
    assert check_products(x) == []
    x.replacements[0].to_product = "Unknown Thing"
    assert [v.field for v in check_products(x)] == ["replacements[0].to_product"]


def test_replacement_completeness() -> None:
    x = _good()
    assert check_replacements(x) == []
    x.replacements[0].to_product = " "
    x.replacements[0].reason = ""
    codes = [v.code for v in check_replacements(x)]
    assert codes == ["replacement_incomplete", "replacement_reason_missing"]


def test_date_plausibility() -> None:
    x = _good()
    assert check_dates(x, document_date=date(2027, 12, 1)) == []
    assert _codes(check_dates(x, document_date=date(2030, 1, 1))) == {"date_implausible"}
    assert check_dates(x, document_date=None) == []
    assert check_dates(SoAExtraction(), document_date=date(2026, 1, 1)) == []


def test_identifier_checks_on_document_text() -> None:
    assert check_identifiers("ABN 30 390 977 742") == []
    bad = check_identifiers("ABN 12 345 678 901")
    assert _codes(bad) == {"abn_invalid"} and bad[0].severity == "warning"
    tfn = generate_tfn(random.Random(9))
    leak = check_identifiers(f"TFN {tfn}")
    assert _codes(leak) == {"tfn_present"} and leak[0].severity == "error"


def test_section_grouping_and_hard_filter() -> None:
    x = _good()
    x.recommendations[0].product_name = "Nope"
    x.fees.ongoing_fee_basis = "flat"  # type: ignore[union-attr]
    x.risk_profile = None
    violations = validate_extraction(x)
    grouped = violations_by_section(violations)
    assert set(grouped) == {"recommendations", "fees", "risk"}
    assert [v.code for v in hard(violations)] == ["missing_field", "product_unknown"]
    assert section_of("replacements[2].reason") == "replacement"
    assert section_of("client_names") == "header"
    assert section_of("document") == "document"
    assert section_of("something_else") == "document"
    assert violations[0].to_dict()["severity"] == "error"
