"""Typed records shared by every component: document types, the Statement-of-Advice
extraction target, the metadata gold for the other document types, and the platform
holdings snapshot used for reconciliation.

The extraction models keep scalar fields *optional* so that a partial extraction is still a
typed object: the corpus generator always fills every field, and a ``None`` in an extraction
is a recorded miss (see ``extract/``), never a silent default.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

DocType = Literal[
    "soa",
    "roa",
    "fact_find",
    "fds",
    "fee_consent",
    "super_statement",
    "insurance_schedule",
    "authority_to_proceed",
    "bank_statement",
    "correspondence",
]
DOC_TYPES: tuple[DocType, ...] = get_args(DocType)
DOC_TYPE_LABELS: dict[str, str] = {
    "soa": "Statement of Advice",
    "roa": "Record of Advice",
    "fact_find": "Fact Find",
    "fds": "Fee Disclosure Statement",
    "fee_consent": "Ongoing Fee Consent",
    "super_statement": "Superannuation Member Statement",
    "insurance_schedule": "Insurance Policy Schedule",
    "authority_to_proceed": "Authority to Proceed",
    "bank_statement": "Bank Statement",
    "correspondence": "Correspondence",
}
DOC_TYPE_DEFINITIONS: dict[str, str] = {
    "soa": "a Statement of Advice: personal advice with recommendations, fees and disclosures",
    "roa": "a Record of Advice: a short record of further advice referring to an earlier SoA",
    "fact_find": "a fact-find questionnaire capturing a client's personal and financial details",
    "fds": "a Fee Disclosure Statement listing fees paid and services provided over a period",
    "fee_consent": "an ongoing fee arrangement consent form the client signs",
    "super_statement": "a superannuation fund's annual member statement (balances, contributions)",
    "insurance_schedule": "an insurance policy schedule (life insured, cover amounts, premiums)",
    "authority_to_proceed": "a signed authority to proceed with the recommendations of an SoA",
    "bank_statement": "a bank account statement with a transaction listing",
    "correspondence": "a general letter or email print-out between adviser and client",
}

RiskProfile = Literal[
    "Conservative", "Moderately Conservative", "Balanced", "Growth", "High Growth"
]
RISK_PROFILES: tuple[RiskProfile, ...] = get_args(RiskProfile)

Action = Literal["establish", "contribute", "switch", "retain", "redeem", "rollover", "insure"]
ACTIONS: tuple[Action, ...] = get_args(Action)

ProductType = Literal["super", "pension", "idps", "managed_portfolio", "insurance", "cash"]
PRODUCT_TYPES: tuple[ProductType, ...] = get_args(ProductType)

InsuranceImpact = Literal["none", "reduced_cover", "increased_cover", "cover_lost"]
INSURANCE_IMPACTS: tuple[InsuranceImpact, ...] = get_args(InsuranceImpact)

FeeBasis = Literal["flat", "percent"]

ScopeArea = Literal["superannuation", "retirement", "insurance", "investment", "debt"]
SCOPE_AREAS: tuple[ScopeArea, ...] = get_args(ScopeArea)


class Recommendation(BaseModel):
    action: Action
    product_name: str = Field(min_length=1)
    product_type: ProductType
    amount: Decimal | None = None
    account_ref: str | None = None


class FeeSchedule(BaseModel):
    initial_advice_fee: Decimal
    ongoing_advice_fee_pa: Decimal
    ongoing_fee_basis: FeeBasis
    ongoing_fee_percent: Decimal | None = None
    platform_admin_fee_pct: Decimal | None = None
    insurance_premium_pa: Decimal | None = None


class ProductReplacement(BaseModel):
    from_product: str
    to_product: str
    fee_difference_pa: Decimal
    insurance_impact: InsuranceImpact
    reason: str = ""


class SoAExtraction(BaseModel):
    """What a Statement of Advice recommends. Gold records fill every field."""

    client_names: list[str] = Field(default_factory=list)
    adviser_name: str | None = None
    licensee: str | None = None
    advice_date: date | None = None
    risk_profile: RiskProfile | None = None
    scope: list[ScopeArea] = Field(default_factory=list)
    recommendations: list[Recommendation] = Field(default_factory=list)
    fees: FeeSchedule | None = None
    replacements: list[ProductReplacement] = Field(default_factory=list)
    authority_to_proceed_signed: bool | None = None


# Fields whose correctness decides whether a document may be auto-accepted.
CRITICAL_FIELDS: tuple[str, ...] = (
    "client_names",
    "adviser_name",
    "advice_date",
    "risk_profile",
    "recommendations",
    "fees.initial_advice_fee",
    "fees.ongoing_advice_fee_pa",
    "replacements",
)


class DocMetadata(BaseModel):
    """The classifier's metadata target for every document type."""

    doc_type: DocType
    client_names: list[str] = Field(default_factory=list)
    adviser_name: str | None = None
    document_date: date | None = None


class Holding(BaseModel):
    product_name: str
    product_code: str
    product_type: ProductType
    balance: Decimal
    account_ref: str


DiscrepancyKind = Literal[
    "not_implemented", "amount_mismatch", "unexpected_product", "fee_mismatch"
]
DISCREPANCY_KINDS: tuple[DiscrepancyKind, ...] = get_args(DiscrepancyKind)


class PlantedDiscrepancy(BaseModel):
    kind: DiscrepancyKind
    product_name: str
    expected: str
    observed: str


class HoldingsSnapshot(BaseModel):
    """What the platform shows for the client 90 days after the advice date."""

    doc_id: str
    client_names: list[str]
    as_of: date
    holdings: list[Holding]
    advice_fee_charged_pa: Decimal
    planted: list[PlantedDiscrepancy] = Field(default_factory=list)


class GoldRecord(BaseModel):
    """One corpus document: its type, layout variant, metadata gold, and (for an SoA) the
    extraction gold and the path of its holdings snapshot."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    doc_type: DocType
    variant: int
    n_pages: int
    metadata: DocMetadata
    soa: SoAExtraction | None = None
    available_funds: Decimal | None = None
    pdf_path: str
    holdings_path: str | None = None
