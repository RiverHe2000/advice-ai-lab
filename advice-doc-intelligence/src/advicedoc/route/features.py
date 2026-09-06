"""Per-field feature records for the review router.

One record per critical field of an extraction (risk profile, each recommendation, the two
advice fees, each replacement) with features that are available at inference time:
agreement with the rules extractor, validator flags, product fuzzy score, JSON repairs,
section-found flag, length / magnitude z-scores against fixed reference statistics, and the
model's self-reported confidence when present. Correctness labels come from the gold.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from advicedoc.eval.matching import compare_extraction, numbers_match, products_match
from advicedoc.extract import ExtractionResult
from advicedoc.schema import SoAExtraction

FieldKind = str
KINDS: tuple[str, ...] = (
    "risk_profile",
    "recommendation",
    "fee_initial",
    "fee_ongoing",
    "replacement",
)
FEATURE_NAMES: tuple[str, ...] = (
    "agree_rules",
    "has_rules",
    "validator_error",
    "validator_warning",
    "fuzzy_score",
    "n_repairs",
    "n_parse_failures",
    "section_found",
    "len_z",
    "amount_log",
    "self_conf",
    "has_self_conf",
    *[f"kind_{k}" for k in KINDS],
)
# Reference statistics (mean, sd) for the length z-score, fixed so that a single document can
# be scored without a batch.
LENGTH_REFERENCE: dict[str, tuple[float, float]] = {
    "risk_profile": (8.0, 4.0),
    "recommendation": (26.0, 6.0),
    "fee_initial": (4.0, 1.0),
    "fee_ongoing": (4.0, 1.0),
    "replacement": (52.0, 10.0),
}
SECTION_OF_KIND: dict[str, str] = {
    "risk_profile": "risk",
    "recommendation": "recommendations",
    "fee_initial": "fees",
    "fee_ongoing": "fees",
    "replacement": "replacement",
}


@dataclass(slots=True)
class FieldRecord:
    doc_id: str
    key: str
    kind: str
    features: dict[str, float]
    correct: bool | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def vector(self) -> list[float]:
        return [self.features.get(name, 0.0) for name in FEATURE_NAMES]


def _z(value: float, kind: str) -> float:
    mean, sd = LENGTH_REFERENCE[kind]
    return (value - mean) / sd


def _amount_log(amount: Decimal | None) -> float:
    return math.log10(float(amount) + 1.0) if amount is not None and amount > 0 else 0.0


def _violation_flags(result: ExtractionResult, prefixes: Sequence[str]) -> tuple[float, float]:
    err = any(
        v.severity == "error" and any(v.field.startswith(p) for p in prefixes)
        for v in result.violations
    )
    warn = any(
        v.severity == "warning" and any(v.field.startswith(p) for p in prefixes)
        for v in result.violations
    )
    return float(err), float(warn)


def _base(result: ExtractionResult, kind: str, prefixes: Sequence[str]) -> dict[str, float]:
    err, warn = _violation_flags(result, prefixes)
    section = SECTION_OF_KIND[kind]
    conf = result.field_confidence.get(section)
    feats = {
        "validator_error": err,
        "validator_warning": warn,
        "n_repairs": float(result.repairs),
        "n_parse_failures": float(result.parse_failures),
        "section_found": float(result.sections_found.get(section, False)),
        "self_conf": conf if conf is not None else 0.5,
        "has_self_conf": float(conf is not None),
        "fuzzy_score": 1.0,
        "amount_log": 0.0,
        "len_z": 0.0,
        "agree_rules": 0.0,
        "has_rules": 0.0,
    }
    for k in KINDS:
        feats[f"kind_{k}"] = float(k == kind)
    return feats


def field_records(
    primary: ExtractionResult,
    rules: ExtractionResult | None = None,
    gold: SoAExtraction | None = None,
) -> list[FieldRecord]:
    """Feature records for every critical field of ``primary``; ``rules`` supplies the
    agreement features and ``gold`` (when known) the correctness labels."""
    x = primary.extraction
    r = rules.extraction if rules is not None else None
    cmp = compare_extraction(x, gold) if gold is not None else None
    records: list[FieldRecord] = []

    feats = _base(primary, "risk_profile", ("risk_profile",))
    feats["len_z"] = _z(len(x.risk_profile or ""), "risk_profile")
    if r is not None:
        feats["has_rules"] = 1.0
        feats["agree_rules"] = float(
            x.risk_profile is not None and x.risk_profile == r.risk_profile
        )
    records.append(
        FieldRecord(
            primary.doc_id,
            "risk_profile",
            "risk_profile",
            feats,
            cmp.fields["risk_profile"] if cmp else None,
        )
    )

    for i, rec in enumerate(x.recommendations):
        feats = _base(primary, "recommendation", (f"recommendations[{i}]", "recommendations"))
        feats["fuzzy_score"] = primary.product_scores.get(f"rec:{i}", 100.0) / 100.0
        feats["len_z"] = _z(len(rec.product_name), "recommendation")
        feats["amount_log"] = _amount_log(rec.amount)
        if r is not None:
            feats["has_rules"] = 1.0
            feats["agree_rules"] = float(
                any(
                    products_match(rec.product_name, o.product_name)
                    and rec.action == o.action
                    and numbers_match(rec.amount, o.amount)
                    for o in r.recommendations
                )
            )
        correct = cmp.recommendations.item_correct[i] if cmp else None
        records.append(FieldRecord(primary.doc_id, f"rec:{i}", "recommendation", feats, correct))
    if not x.recommendations:
        feats = _base(primary, "recommendation", ("recommendations",))
        feats["validator_error"] = 1.0
        records.append(
            FieldRecord(
                primary.doc_id,
                "rec:missing",
                "recommendation",
                feats,
                (cmp.recommendations.exact if cmp else None),
            )
        )

    for key, attr, kind in (
        ("fee:initial", "initial_advice_fee", "fee_initial"),
        ("fee:ongoing", "ongoing_advice_fee_pa", "fee_ongoing"),
    ):
        feats = _base(primary, kind, (f"fees.{attr}", "fees"))
        value = getattr(x.fees, attr) if x.fees is not None else None
        feats["len_z"] = _z(len(str(value)) if value is not None else 0.0, kind)
        feats["amount_log"] = _amount_log(value)
        if x.fees is None:
            feats["validator_error"] = 1.0
        if r is not None:
            feats["has_rules"] = 1.0
            other = getattr(r.fees, attr) if r.fees is not None else None
            feats["agree_rules"] = float(value is not None and numbers_match(value, other))
        records.append(
            FieldRecord(
                primary.doc_id, key, kind, feats, cmp.fields[f"fees.{attr}"] if cmp else None
            )
        )

    for i, rep in enumerate(x.replacements):
        feats = _base(primary, "replacement", (f"replacements[{i}]", "replacements"))
        feats["len_z"] = _z(len(rep.from_product) + len(rep.to_product), "replacement")
        feats["amount_log"] = _amount_log(abs(rep.fee_difference_pa))
        feats["fuzzy_score"] = (
            min(
                primary.product_scores.get(f"repl:{i}:from", 100.0),
                primary.product_scores.get(f"repl:{i}:to", 100.0),
            )
            / 100.0
        )
        if r is not None:
            feats["has_rules"] = 1.0
            feats["agree_rules"] = float(
                any(
                    products_match(rep.from_product, o.from_product)
                    and products_match(rep.to_product, o.to_product)
                    and numbers_match(rep.fee_difference_pa, o.fee_difference_pa)
                    for o in r.replacements
                )
            )
        correct = cmp.replacements.item_correct[i] if cmp else None
        records.append(FieldRecord(primary.doc_id, f"repl:{i}", "replacement", feats, correct))
    if (
        gold is not None
        and cmp is not None
        and not cmp.replacements.exact
        and len(x.replacements) < len(gold.replacements)
    ):
        feats = _base(primary, "replacement", ("replacements",))
        if r is not None:
            feats["has_rules"] = 1.0
            feats["agree_rules"] = float(len(r.replacements) == len(x.replacements))
        records.append(FieldRecord(primary.doc_id, "repl:missing", "replacement", feats, False))
    return records
