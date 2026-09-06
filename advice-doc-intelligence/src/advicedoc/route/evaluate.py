"""Router evaluation: calibration of P(field correct), the risk-coverage curve (review rate
vs residual critical-field error among auto-accepted documents), its area, the tau that
meets a target residual error and the review rate it implies, and three naive policies for
comparison — all with bootstrap CIs over documents."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from advicedoc.route.features import FieldRecord
from advicedoc.stats import (
    CalibrationResult,
    Interval,
    bootstrap_statistic,
    expected_calibration_error,
)


@dataclass(slots=True)
class PolicyPoint:
    name: str
    review_rate: Interval
    residual_error: Interval
    tau: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "review_rate": self.review_rate.to_dict(),
            "residual_error": self.residual_error.to_dict(),
            "tau": self.tau,
        }


@dataclass(slots=True)
class RouterReport:
    n_docs: int
    n_fields: int
    base_field_error: float
    base_doc_error: float
    calibration: CalibrationResult
    curve: list[dict[str, float]]
    aurc: Interval
    target_residual: float
    chosen: PolicyPoint
    naive: list[PolicyPoint]
    coefficients: dict[str, float] | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_docs": self.n_docs,
            "n_fields": self.n_fields,
            "base_field_error": self.base_field_error,
            "base_doc_error": self.base_doc_error,
            "calibration": self.calibration.to_dict(),
            "curve": self.curve,
            "aurc": self.aurc.to_dict(),
            "target_residual": self.target_residual,
            "chosen": self.chosen.to_dict(),
            "naive": [p.to_dict() for p in self.naive],
            "coefficients": self.coefficients,
            "notes": self.notes,
        }


def _doc_arrays(
    records: Sequence[FieldRecord], probs: Sequence[float] | np.ndarray
) -> tuple[list[str], np.ndarray, np.ndarray, np.ndarray]:
    """Per document: min P(correct), any field wrong, any hard validator error."""
    ids: list[str] = []
    min_p: dict[str, float] = {}
    wrong: dict[str, bool] = {}
    flagged: dict[str, bool] = {}
    for rec, p in zip(records, probs, strict=True):
        if rec.doc_id not in min_p:
            ids.append(rec.doc_id)
        min_p[rec.doc_id] = min(min_p.get(rec.doc_id, 1.0), float(p))
        wrong[rec.doc_id] = wrong.get(rec.doc_id, False) or not bool(rec.correct)
        flagged[rec.doc_id] = (
            flagged.get(rec.doc_id, False) or rec.features.get("validator_error", 0.0) > 0
        )
    return (
        ids,
        np.asarray([min_p[i] for i in ids]),
        np.asarray([wrong[i] for i in ids], dtype=bool),
        np.asarray([flagged[i] for i in ids], dtype=bool),
    )


def risk_coverage_curve(min_p: np.ndarray, wrong: np.ndarray) -> list[dict[str, float]]:
    """Accept documents in decreasing order of min P(correct); at each coverage report the
    review rate and the residual error among the accepted."""
    order = np.argsort(-min_p, kind="stable")
    curve: list[dict[str, float]] = [
        {"tau": 1.0, "coverage": 0.0, "review_rate": 1.0, "residual_error": 0.0}
    ]
    cum_wrong = 0
    n = len(min_p)
    for k, idx in enumerate(order, 1):
        cum_wrong += int(wrong[idx])
        curve.append(
            {
                "tau": float(min_p[idx]),
                "coverage": k / n,
                "review_rate": 1.0 - k / n,
                "residual_error": cum_wrong / k,
            }
        )
    return curve


def aurc(min_p: np.ndarray, wrong: np.ndarray) -> float:
    """Area under the risk-coverage curve (mean selective risk over coverage levels)."""
    if len(min_p) == 0:
        return float("nan")
    points = risk_coverage_curve(min_p, wrong)[1:]
    return float(np.mean([p["residual_error"] for p in points]))


def choose_tau(min_p: np.ndarray, wrong: np.ndarray, target: float) -> float:
    """The largest coverage whose residual error is within ``target``; returns the tau
    (min P(correct)) that realises it (1.0 + epsilon when nothing qualifies)."""
    best_tau = float("inf")
    for p in risk_coverage_curve(min_p, wrong)[1:]:
        if p["residual_error"] <= target:
            best_tau = p["tau"]
    return best_tau if np.isfinite(best_tau) else 1.0001


def _policy(
    name: str,
    review: np.ndarray,
    wrong: np.ndarray,
    *,
    tau: float | None,
    seed: int,
    n_boot: int,
) -> PolicyPoint:
    n = len(review)

    def review_rate(idx: np.ndarray) -> float:
        return float(review[idx].mean())

    def residual(idx: np.ndarray) -> float:
        accepted = ~review[idx]
        return float(wrong[idx][accepted].mean()) if accepted.any() else 0.0

    return PolicyPoint(
        name,
        bootstrap_statistic(n, review_rate, n_boot=n_boot, seed=seed),
        bootstrap_statistic(n, residual, n_boot=n_boot, seed=seed + 1),
        tau,
    )


def evaluate_router(
    records: Sequence[FieldRecord],
    probs: Sequence[float] | np.ndarray,
    *,
    target_residual: float = 0.01,
    seed: int = 0,
    n_boot: int = 1000,
    coefficients: dict[str, float] | None = None,
) -> RouterReport:
    labelled = [r for r in records if r.correct is not None]
    p = np.asarray(list(probs), dtype=np.float64)
    if len(labelled) != len(p):
        msg = "one probability per labelled record is required"
        raise ValueError(msg)
    correct = np.asarray([bool(r.correct) for r in labelled])
    calibration = expected_calibration_error(p, correct)
    ids, min_p, wrong, flagged = _doc_arrays(labelled, p)
    n = len(ids)
    curve = risk_coverage_curve(min_p, wrong)
    tau = choose_tau(min_p, wrong, target_residual)
    area = bootstrap_statistic(
        n, lambda idx: aurc(min_p[idx], wrong[idx]), n_boot=n_boot, seed=seed
    )
    chosen = _policy("router@tau", min_p < tau, wrong, tau=tau, seed=seed, n_boot=n_boot)
    naive = [
        _policy("review_all", np.ones(n, dtype=bool), wrong, tau=None, seed=seed, n_boot=n_boot),
        _policy("review_none", np.zeros(n, dtype=bool), wrong, tau=None, seed=seed, n_boot=n_boot),
        _policy("review_if_validator_fails", flagged, wrong, tau=None, seed=seed, n_boot=n_boot),
    ]
    return RouterReport(
        n_docs=n,
        n_fields=len(labelled),
        base_field_error=float(1.0 - correct.mean()) if len(correct) else float("nan"),
        base_doc_error=float(wrong.mean()) if n else float("nan"),
        calibration=calibration,
        curve=curve,
        aurc=area,
        target_residual=target_residual,
        chosen=chosen,
        naive=naive,
        coefficients=coefficients,
    )


def render_router_report(report: RouterReport) -> str:
    lines = [
        "# Review router evaluation",
        "",
        f"{report.n_docs} documents, {report.n_fields} critical fields; base field error "
        f"{report.base_field_error:.3f}, base document error {report.base_doc_error:.3f}; "
        f"probabilities are out-of-fold (GroupKFold by document).",
        "",
        "| Metric | Value [95 % CI] |",
        "|---|---:|",
        f"| ECE of P(field correct) | {report.calibration.ece:.3f} |",
        f"| Area under risk-coverage curve (lower is better) | {report.aurc.fmt()} |",
        f"| Target residual error | {report.target_residual:.3f} |",
        f"| Chosen tau | {report.chosen.tau:.3f} |"
        if report.chosen.tau is not None
        else "| Chosen tau | n/a |",
        f"| Review rate at tau | {report.chosen.review_rate.fmt()} |",
        f"| Residual error at tau | {report.chosen.residual_error.fmt()} |",
        "",
        "## Policies",
        "",
        "| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |",
        "|---|---:|---:|",
        f"| {report.chosen.name} | {report.chosen.review_rate.fmt()} | "
        f"{report.chosen.residual_error.fmt()} |",
    ]
    for p in report.naive:
        lines.append(f"| {p.name} | {p.review_rate.fmt()} | {p.residual_error.fmt()} |")
    lines += ["", "## Reliability table (P(field correct))", "", report.calibration.table_md()]
    lines += [
        "",
        "## Risk-coverage curve (every 5th point)",
        "",
        "| tau | coverage | review rate | residual error |",
        "|---:|---:|---:|---:|",
    ]
    for i, pt in enumerate(report.curve):
        if i % 5 == 0 or i == len(report.curve) - 1:
            lines.append(
                f"| {pt['tau']:.3f} | {pt['coverage']:.3f} | {pt['review_rate']:.3f} | "
                f"{pt['residual_error']:.3f} |"
            )
    if report.coefficients:
        lines += [
            "",
            "## Logistic-regression coefficients (standardised features)",
            "",
            "| Feature | Coefficient |",
            "|---|---:|",
        ]
        for name, c in sorted(report.coefficients.items(), key=lambda kv: -abs(kv[1])):
            lines.append(f"| {name} | {c:+.3f} |")
    if report.notes:
        lines += ["", "## Notes", "", *[f"- {n}" for n in report.notes]]
    return "\n".join(lines) + "\n"


def save_router_report(report: RouterReport, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "router_report.md").write_text(render_router_report(report), encoding="utf-8")
    (out / "router_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
    )
