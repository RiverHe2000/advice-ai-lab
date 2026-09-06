"""Field matchers: numbers within 0.5 % or $1, names case/space-insensitive, product names
fuzzy >= 95, enums and dates exact; list fields matched by product name to give precision /
recall / F1; a document is *correct* when every critical field is."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from rapidfuzz import fuzz

from advicedoc.schema import ProductReplacement, Recommendation, SoAExtraction
from advicedoc.textutil import normalise_name

PRODUCT_FUZZ = 95.0


def numbers_match(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(a - b) <= max(Decimal(1), abs(b) * Decimal("0.005"))


def names_match(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return (a or "") == (b or "")
    return normalise_name(a) == normalise_name(b)


def name_lists_match(a: list[str], b: list[str]) -> bool:
    return sorted(normalise_name(x) for x in a) == sorted(normalise_name(x) for x in b)


def products_match(a: str, b: str) -> bool:
    return fuzz.ratio(normalise_name(a), normalise_name(b)) >= PRODUCT_FUZZ


def dates_match(a: date | None, b: date | None) -> bool:
    return a == b


@dataclass(slots=True)
class ListMatch:
    n_pred: int
    n_gold: int
    matched: int  # matched by key
    correct: int  # matched and every compared attribute right
    item_correct: list[bool] = field(default_factory=list)  # per predicted item

    @property
    def precision(self) -> float:
        return self.correct / self.n_pred if self.n_pred else (1.0 if self.n_gold == 0 else 0.0)

    @property
    def recall(self) -> float:
        return self.correct / self.n_gold if self.n_gold else (1.0 if self.n_pred == 0 else 0.0)

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    @property
    def exact(self) -> bool:
        return self.n_pred == self.n_gold == self.correct


def match_recommendations(pred: list[Recommendation], gold: list[Recommendation]) -> ListMatch:
    used: set[int] = set()
    out = ListMatch(len(pred), len(gold), 0, 0)
    for p in pred:
        best: int | None = None
        for j, g in enumerate(gold):
            if j in used or not products_match(p.product_name, g.product_name):
                continue
            if g.action == p.action or best is None:
                best = j
                if g.action == p.action:
                    break
        if best is None:
            out.item_correct.append(False)
            continue
        used.add(best)
        g = gold[best]
        out.matched += 1
        ok = p.action == g.action and numbers_match(p.amount, g.amount)
        out.correct += int(ok)
        out.item_correct.append(ok)
    return out


def match_replacements(pred: list[ProductReplacement], gold: list[ProductReplacement]) -> ListMatch:
    used: set[int] = set()
    out = ListMatch(len(pred), len(gold), 0, 0)
    for p in pred:
        best = next(
            (
                j
                for j, g in enumerate(gold)
                if j not in used
                and products_match(p.from_product, g.from_product)
                and products_match(p.to_product, g.to_product)
            ),
            None,
        )
        if best is None:
            out.item_correct.append(False)
            continue
        used.add(best)
        g = gold[best]
        out.matched += 1
        ok = (
            numbers_match(p.fee_difference_pa, g.fee_difference_pa)
            and p.insurance_impact == g.insurance_impact
        )
        out.correct += int(ok)
        out.item_correct.append(ok)
    return out


SCALAR_FIELDS: tuple[str, ...] = (
    "client_names",
    "adviser_name",
    "licensee",
    "advice_date",
    "risk_profile",
    "scope",
    "fees.initial_advice_fee",
    "fees.ongoing_advice_fee_pa",
    "fees.ongoing_fee_basis",
    "fees.ongoing_fee_percent",
    "fees.platform_admin_fee_pct",
    "fees.insurance_premium_pa",
    "authority_to_proceed_signed",
)
ALL_FIELDS: tuple[str, ...] = (*SCALAR_FIELDS, "recommendations", "replacements")


@dataclass(slots=True)
class ExtractionComparison:
    fields: dict[str, bool]
    recommendations: ListMatch
    replacements: ListMatch
    doc_correct: bool

    @property
    def field_accuracy(self) -> float:
        values = list(self.fields.values())
        return sum(values) / len(values) if values else 0.0


def _fee(x: SoAExtraction, attr: str) -> Decimal | str | None:
    if x.fees is None:
        return None
    value: Decimal | str | None = getattr(x.fees, attr)
    return value


def compare_extraction(pred: SoAExtraction, gold: SoAExtraction) -> ExtractionComparison:
    fields: dict[str, bool] = {
        "client_names": name_lists_match(pred.client_names, gold.client_names),
        "adviser_name": names_match(pred.adviser_name, gold.adviser_name),
        "licensee": names_match(pred.licensee, gold.licensee),
        "advice_date": dates_match(pred.advice_date, gold.advice_date),
        "risk_profile": pred.risk_profile == gold.risk_profile,
        "scope": sorted(pred.scope) == sorted(gold.scope),
        "authority_to_proceed_signed": pred.authority_to_proceed_signed
        == gold.authority_to_proceed_signed,
    }
    for attr in (
        "initial_advice_fee",
        "ongoing_advice_fee_pa",
        "ongoing_fee_percent",
        "platform_admin_fee_pct",
        "insurance_premium_pa",
    ):
        a, b = _fee(pred, attr), _fee(gold, attr)
        fields[f"fees.{attr}"] = numbers_match(
            a if isinstance(a, Decimal) else None, b if isinstance(b, Decimal) else None
        )
    fields["fees.ongoing_fee_basis"] = _fee(pred, "ongoing_fee_basis") == _fee(
        gold, "ongoing_fee_basis"
    )
    recs = match_recommendations(pred.recommendations, gold.recommendations)
    reps = match_replacements(pred.replacements, gold.replacements)
    fields["recommendations"] = recs.exact
    fields["replacements"] = reps.exact
    doc_correct = all(
        fields[f]
        for f in (
            "client_names",
            "adviser_name",
            "advice_date",
            "risk_profile",
            "fees.initial_advice_fee",
            "fees.ongoing_advice_fee_pa",
            "recommendations",
            "replacements",
        )
    )
    return ExtractionComparison(fields, recs, reps, doc_correct)
