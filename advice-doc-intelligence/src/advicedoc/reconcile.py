"""Advice-vs-implementation reconciliation: match an ``SoAExtraction`` to a platform
holdings snapshot, compute discrepancies (not implemented, amount mismatch, unexpected
product, fee mismatch) with tolerance parameters, render a per-client markdown report, and
evaluate detection / false-alarm rates against the simulator's planted discrepancies."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from advicedoc.corpus.products import DEFAULT_MASTER, ProductMaster
from advicedoc.eval.matching import products_match
from advicedoc.schema import DISCREPANCY_KINDS, DiscrepancyKind, HoldingsSnapshot, SoAExtraction
from advicedoc.stats import Interval, bootstrap_statistic

Severity = Literal["high", "medium", "low"]
INVEST_ACTIONS = frozenset({"establish", "contribute", "rollover", "switch", "retain", "insure"})
FEE_KEY = "advice_fee"


@dataclass(frozen=True, slots=True)
class Discrepancy:
    kind: DiscrepancyKind
    product_name: str
    expected: str
    observed: str
    severity: Severity
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReconciliationReport:
    doc_id: str
    client_names: list[str]
    as_of: str
    discrepancies: list[Discrepancy]
    matched: list[dict[str, str]] = field(default_factory=list)
    parameters: dict[str, float] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        return not self.discrepancies

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "client_names": self.client_names,
            "as_of": self.as_of,
            "discrepancies": [d.to_dict() for d in self.discrepancies],
            "matched": self.matched,
            "parameters": self.parameters,
        }


def expected_positions(
    extraction: SoAExtraction, master: ProductMaster
) -> tuple[dict[str, Decimal], set[str]]:
    """Expected balance per (canonical) product and the products to be redeemed."""
    expected: dict[str, Decimal] = {}
    redeemed: set[str] = set()
    for r in extraction.recommendations:
        product, _ = master.match(r.product_name, threshold=85.0)
        name = product.name if product else r.product_name
        if r.action == "redeem":
            redeemed.add(name)
            continue
        if r.action in INVEST_ACTIONS and r.amount is not None:
            expected[name] = expected.get(name, Decimal(0)) + r.amount
    return expected, redeemed


def _pct(a: Decimal, b: Decimal) -> str:
    return f"{float((a - b) / b) * 100:+.1f} %" if b else "n/a"


def reconcile(
    extraction: SoAExtraction,
    holdings: HoldingsSnapshot,
    *,
    master: ProductMaster = DEFAULT_MASTER,
    amount_tolerance: float = 0.05,
    fee_tolerance: float = 0.05,
) -> ReconciliationReport:
    expected, redeemed = expected_positions(extraction, master)
    found: list[Discrepancy] = []
    matched: list[dict[str, str]] = []
    used: set[int] = set()
    tol = Decimal(str(amount_tolerance))
    for name, amount in expected.items():
        idx = next(
            (
                i
                for i, h in enumerate(holdings.holdings)
                if i not in used and products_match(h.product_name, name)
            ),
            None,
        )
        if idx is None:
            found.append(
                Discrepancy(
                    "not_implemented",
                    name,
                    str(amount),
                    "absent",
                    "high",
                    "recommended product not held on the platform",
                )
            )
            continue
        used.add(idx)
        h = holdings.holdings[idx]
        if amount > 0 and abs(h.balance - amount) > amount * tol:
            found.append(
                Discrepancy(
                    "amount_mismatch",
                    name,
                    str(amount),
                    str(h.balance),
                    "medium",
                    f"balance differs from the recommended amount by "
                    f"{_pct(h.balance, amount)} (tolerance {amount_tolerance:.0%})",
                )
            )
        else:
            matched.append({"product": name, "expected": str(amount), "observed": str(h.balance)})
    for i, h in enumerate(holdings.holdings):
        if i in used:
            continue
        if any(products_match(h.product_name, r) for r in redeemed):
            found.append(
                Discrepancy(
                    "not_implemented",
                    h.product_name,
                    "redeemed",
                    str(h.balance),
                    "high",
                    "product recommended for redemption is still held",
                )
            )
        else:
            found.append(
                Discrepancy(
                    "unexpected_product",
                    h.product_name,
                    "absent",
                    str(h.balance),
                    "medium",
                    "held on the platform but not in the advice",
                )
            )
    if extraction.fees is not None:
        agreed = extraction.fees.ongoing_advice_fee_pa
        charged = holdings.advice_fee_charged_pa
        if abs(charged - agreed) > max(Decimal(1), agreed * Decimal(str(fee_tolerance))):
            found.append(
                Discrepancy(
                    "fee_mismatch",
                    FEE_KEY,
                    str(agreed),
                    str(charged),
                    "high",
                    "ongoing advice fee charged differs from the fee agreed by "
                    f"{_pct(charged, agreed)}",
                )
            )
    return ReconciliationReport(
        doc_id=holdings.doc_id,
        client_names=list(holdings.client_names),
        as_of=holdings.as_of.isoformat(),
        discrepancies=found,
        matched=matched,
        parameters={"amount_tolerance": amount_tolerance, "fee_tolerance": fee_tolerance},
    )


def render_reconciliation_md(report: ReconciliationReport) -> str:
    lines = [
        f"# Implementation reconciliation - {', '.join(report.client_names)}",
        "",
        f"Document `{report.doc_id}`; platform snapshot as of {report.as_of}; amount tolerance "
        f"{report.parameters.get('amount_tolerance', 0.05):.0%}, fee tolerance "
        f"{report.parameters.get('fee_tolerance', 0.05):.0%}.",
        "",
        "## Result: "
        + ("no discrepancies" if report.clean else f"{len(report.discrepancies)} discrepancies"),
        "",
    ]
    if report.discrepancies:
        lines += [
            "| Kind | Product | Expected | Observed | Severity | Detail |",
            "|---|---|---:|---:|---|---|",
        ]
        for d in report.discrepancies:
            lines.append(
                f"| {d.kind} | {d.product_name} | {d.expected} | {d.observed} | "
                f"{d.severity} | {d.detail} |"
            )
        lines.append("")
    if report.matched:
        lines += [
            "## Implemented as advised",
            "",
            "| Product | Recommended | Platform balance |",
            "|---|---:|---:|",
        ]
        for m in report.matched:
            lines.append(f"| {m['product']} | {m['expected']} | {m['observed']} |")
        lines.append("")
    return "\n".join(lines)


# ----- evaluation against the simulator -----------------------------------------------------


@dataclass(slots=True)
class KindResult:
    kind: str
    planted: int
    detected: int
    false_alarm_docs: int
    detection_rate: Interval
    false_alarm_rate: Interval

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "planted": self.planted,
            "detected": self.detected,
            "false_alarm_docs": self.false_alarm_docs,
            "detection_rate": self.detection_rate.to_dict(),
            "false_alarm_rate": self.false_alarm_rate.to_dict(),
        }


@dataclass(slots=True)
class ReconcileEvaluation:
    n_docs: int
    amount_tolerance: float
    fee_tolerance: float
    kinds: list[KindResult]
    overall_detection: Interval
    clean_docs_flagged: Interval
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_docs": self.n_docs,
            "amount_tolerance": self.amount_tolerance,
            "fee_tolerance": self.fee_tolerance,
            "source": self.source,
            "kinds": [k.to_dict() for k in self.kinds],
            "overall_detection": self.overall_detection.to_dict(),
            "clean_docs_flagged": self.clean_docs_flagged.to_dict(),
        }


def evaluate_reconciliation(
    cases: Sequence[tuple[SoAExtraction, HoldingsSnapshot]],
    *,
    master: ProductMaster = DEFAULT_MASTER,
    amount_tolerance: float = 0.05,
    fee_tolerance: float = 0.05,
    seed: int = 0,
    n_boot: int = 1000,
    source: str = "gold",
) -> ReconcileEvaluation:
    per_doc: list[dict[str, tuple[int, int, int]]] = []  # kind -> (planted, detected, false alarm)
    clean_flagged: list[float] = []
    for extraction, holdings in cases:
        report = reconcile(
            extraction,
            holdings,
            master=master,
            amount_tolerance=amount_tolerance,
            fee_tolerance=fee_tolerance,
        )
        detected = [(d.kind, d.product_name) for d in report.discrepancies]
        counts: dict[str, tuple[int, int, int]] = {}
        for kind in DISCREPANCY_KINDS:
            planted = [p for p in holdings.planted if p.kind == kind]
            hits = 0
            for p in planted:
                if any(k == kind and products_match(name, p.product_name) for k, name in detected):
                    hits += 1
            extra = sum(
                1
                for k, name in detected
                if k == kind and not any(products_match(name, p.product_name) for p in planted)
            )
            counts[kind] = (len(planted), hits, int(extra > 0))
        per_doc.append(counts)
        if not holdings.planted:
            clean_flagged.append(float(bool(report.discrepancies)))
    n = len(per_doc)
    kinds: list[KindResult] = []
    for kind in DISCREPANCY_KINDS:
        n_planted = sum(c[kind][0] for c in per_doc)
        n_detected = sum(c[kind][1] for c in per_doc)
        fa_docs = sum(c[kind][2] for c in per_doc)

        def det(idx: Any, k: str = kind) -> float:
            p = sum(per_doc[i][k][0] for i in idx)
            d = sum(per_doc[i][k][1] for i in idx)
            return d / p if p else float("nan")

        def fa(idx: Any, k: str = kind) -> float:
            return float(sum(per_doc[i][k][2] for i in idx) / max(1, len(idx)))

        kinds.append(
            KindResult(
                kind,
                n_planted,
                n_detected,
                fa_docs,
                bootstrap_statistic(n, det, n_boot=n_boot, seed=seed),
                bootstrap_statistic(n, fa, n_boot=n_boot, seed=seed + 1),
            )
        )

    def overall(idx: Any) -> float:
        p = sum(per_doc[i][k][0] for i in idx for k in DISCREPANCY_KINDS)
        d = sum(per_doc[i][k][1] for i in idx for k in DISCREPANCY_KINDS)
        return d / p if p else float("nan")

    return ReconcileEvaluation(
        n_docs=n,
        amount_tolerance=amount_tolerance,
        fee_tolerance=fee_tolerance,
        kinds=kinds,
        overall_detection=bootstrap_statistic(n, overall, n_boot=n_boot, seed=seed + 2),
        clean_docs_flagged=bootstrap_statistic(
            len(clean_flagged),
            lambda idx: float(sum(clean_flagged[i] for i in idx) / max(1, len(idx))),
            n_boot=n_boot,
            seed=seed + 3,
        ),
        source=source,
    )


def render_reconcile_evaluation(evaluations: Sequence[ReconcileEvaluation]) -> str:
    lines = ["# Reconciliation evaluation against planted discrepancies", ""]
    for ev in evaluations:
        lines += [
            f"## Source `{ev.source}`, amount tolerance {ev.amount_tolerance:.0%}, fee "
            f"tolerance {ev.fee_tolerance:.0%} ({ev.n_docs} documents)",
            "",
            "| Kind | Planted | Detected | Detection rate [95 % CI] | Docs with a false alarm | "
            "False-alarm rate per doc [95 % CI] |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for k in ev.kinds:
            lines.append(
                f"| {k.kind} | {k.planted} | {k.detected} | {k.detection_rate.fmt()} | "
                f"{k.false_alarm_docs} | {k.false_alarm_rate.fmt()} |"
            )
        lines += [
            "",
            f"Overall detection {ev.overall_detection.fmt()}; share of clean documents "
            f"(nothing planted) that raised any discrepancy: {ev.clean_docs_flagged.fmt()}.",
            "",
        ]
    return "\n".join(lines)


def save_reconcile_evaluation(
    evaluations: Sequence[ReconcileEvaluation], out_dir: str | Path
) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "reconcile_report.md").write_text(
        render_reconcile_evaluation(evaluations), encoding="utf-8"
    )
    (out / "reconcile_report.json").write_text(
        json.dumps([e.to_dict() for e in evaluations], indent=2, default=str), encoding="utf-8"
    )
