from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from advicedoc.corpus.generator import GeneratedDocument
from advicedoc.corpus.holdings import simulate_holdings
from advicedoc.extract import ExtractionResult
from advicedoc.extract.llm import LLMExtractor
from advicedoc.extract.rules import RulesExtractor
from advicedoc.ingest import Document
from advicedoc.reconcile import (
    evaluate_reconciliation,
    reconcile,
    render_reconcile_evaluation,
    render_reconciliation_md,
    save_reconcile_evaluation,
)
from advicedoc.route.evaluate import (
    aurc,
    choose_tau,
    evaluate_router,
    render_router_report,
    risk_coverage_curve,
    save_router_report,
)
from advicedoc.route.features import FEATURE_NAMES, FieldRecord, field_records
from advicedoc.route.model import (
    ConstantModel,
    ReviewRouter,
    cross_val_probabilities,
    train_router,
)
from advicedoc.schema import Holding, HoldingsSnapshot, SoAExtraction


@pytest.fixture(scope="module")
def routed(
    soa_docs: list[Document], soa_golds: list[SoAExtraction], gold_by_id: dict[str, SoAExtraction]
) -> list[FieldRecord]:
    from advicedoc.extract.fake import make_extraction_responder
    from advicedoc.llm import FakeChatModel

    model = FakeChatModel(default=make_extraction_responder(gold_by_id, corruption=0.4, seed=5))
    primary = LLMExtractor(model)
    rules = RulesExtractor()
    records: list[FieldRecord] = []
    for doc, gold in zip(soa_docs, soa_golds, strict=True):
        records.extend(field_records(primary.extract(doc), rules.extract(doc), gold))
    return records


def test_field_records_cover_every_critical_field(
    soa_docs: list[Document], soa_golds: list[SoAExtraction]
) -> None:
    result = RulesExtractor().extract(soa_docs[0])
    records = field_records(result, None, soa_golds[0])
    keys = [r.key for r in records]
    assert "risk_profile" in keys and "fee:initial" in keys and "fee:ongoing" in keys
    assert sum(k.startswith("rec:") for k in keys) == len(result.extraction.recommendations)
    assert all(r.correct for r in records)
    assert all(len(r.vector()) == len(FEATURE_NAMES) for r in records)
    assert all(r.features["has_rules"] == 0.0 for r in records)
    unlabelled = field_records(result)
    assert all(r.correct is None for r in unlabelled)


def test_field_records_flag_missing_items(soa_golds: list[SoAExtraction]) -> None:
    empty = ExtractionResult(strategy="x", doc_id="d", extraction=SoAExtraction())
    records = field_records(empty, None, soa_golds[0])
    keys = {r.key for r in records}
    assert "rec:missing" in keys and "fee:initial" in keys
    assert next(r for r in records if r.key == "rec:missing").correct is False
    if soa_golds[0].replacements:
        assert "repl:missing" in keys


def test_router_training_prediction_and_persistence(
    tmp_path: Path, routed: list[FieldRecord]
) -> None:
    router = train_router(routed, seed=0, tau=0.5)
    probs = router.predict_proba(routed)
    assert probs.shape == (len(routed),) and np.all((probs >= 0) & (probs <= 1))
    scores = router.doc_scores(routed)
    assert all(0 <= s <= 1 for s in scores.values())
    decisions = router.decide(routed)
    assert set(decisions.values()) <= {"review", "auto"}
    assert router.decide(routed, tau=1.01) == dict.fromkeys(scores, "review")
    coefs = router.coefficients()
    assert coefs is not None and set(coefs) == set(FEATURE_NAMES)
    path = tmp_path / "router.joblib"
    router.save(path)
    loaded = ReviewRouter.load(path)
    assert np.allclose(loaded.predict_proba(routed), probs) and loaded.tau == 0.5
    assert router.predict_proba([]).size == 0


def test_router_falls_back_to_constant_when_labels_are_uniform(routed: list[FieldRecord]) -> None:
    uniform = [FieldRecord(r.doc_id, r.key, r.kind, r.features, True) for r in routed]
    router = train_router(uniform)
    assert isinstance(router.model, ConstantModel)
    assert router.predict_proba(uniform).tolist() == [1.0] * len(uniform)
    assert router.coefficients() is None
    with pytest.raises(ValueError, match="labelled"):
        train_router([FieldRecord("d", "k", "risk_profile", {}, None)])
    single_doc = [r for r in routed if r.doc_id == routed[0].doc_id]
    assert len(cross_val_probabilities(single_doc)) == len(single_doc)


def test_router_evaluation_and_curve(tmp_path: Path, routed: list[FieldRecord]) -> None:
    probs = cross_val_probabilities(routed, seed=0, cv=3)
    report = evaluate_router(
        routed, probs, target_residual=0.01, n_boot=30, coefficients={"a": 1.0}
    )
    coverages = [p["coverage"] for p in report.curve]
    assert coverages == sorted(coverages) and coverages[-1] == 1.0
    assert report.curve[-1]["residual_error"] == pytest.approx(report.base_doc_error)
    assert report.chosen.residual_error.point <= 0.01 or report.chosen.review_rate.point == 1.0
    assert {p.name for p in report.naive} == {
        "review_all",
        "review_none",
        "review_if_validator_fails",
    }
    assert report.naive[0].residual_error.point == 0.0
    md = render_router_report(report)
    assert "risk-coverage" in md and "| a | +1.000 |" in md
    save_router_report(report, tmp_path)
    assert json.loads((tmp_path / "router_report.json").read_text())["n_docs"] == report.n_docs
    with pytest.raises(ValueError, match="one probability"):
        evaluate_router(routed, probs[:-1])


def test_curve_helpers() -> None:
    min_p = np.array([0.9, 0.2, 0.7])
    wrong = np.array([False, True, False])
    curve = risk_coverage_curve(min_p, wrong)
    assert [p["residual_error"] for p in curve] == pytest.approx([0.0, 0.0, 0.0, 1 / 3])
    assert choose_tau(min_p, wrong, 0.0) == 0.7
    assert choose_tau(np.array([0.5]), np.array([True]), 0.0) == 1.0001
    assert aurc(min_p, wrong) == pytest.approx((0 + 0 + 1 / 3) / 3)
    assert np.isnan(aurc(np.array([]), np.array([])))


# ----- reconciliation -----------------------------------------------------------------------


def test_reconcile_detects_each_planted_kind(soa_gens: list[GeneratedDocument]) -> None:
    kinds_detected: set[str] = set()
    for g in soa_gens:
        gold = g.gold.soa
        assert gold is not None
        for seed in range(6):
            holdings = simulate_holdings(
                gold, g.gold.doc_id, random.Random(seed), p_discrepancy=1.0, noise_sd=0.0
            )
            report = reconcile(gold, holdings)
            detected = {(d.kind, d.product_name) for d in report.discrepancies}
            for planted in holdings.planted:
                assert (planted.kind, planted.product_name) in detected
                kinds_detected.add(planted.kind)
            assert "Implementation reconciliation" in render_reconciliation_md(report)
    assert kinds_detected == {
        "not_implemented",
        "amount_mismatch",
        "unexpected_product",
        "fee_mismatch",
    }


def test_reconcile_clean_and_redeem_cases(soa_golds: list[SoAExtraction]) -> None:
    gold = soa_golds[0]
    holdings = simulate_holdings(gold, "x", random.Random(1), p_discrepancy=0.0, noise_sd=0.0)
    report = reconcile(gold, holdings)
    assert (
        report.clean and report.matched and "no discrepancies" in render_reconciliation_md(report)
    )
    assert report.to_dict()["parameters"]["amount_tolerance"] == 0.05
    redeem = gold.model_copy(deep=True)
    redeem.recommendations[0].action = "redeem"
    still_held = HoldingsSnapshot(
        doc_id="x",
        client_names=gold.client_names,
        as_of=holdings.as_of,
        holdings=[
            Holding(
                product_name=gold.recommendations[0].product_name,
                product_code="c",
                product_type=gold.recommendations[0].product_type,
                balance=Decimal(1000),
                account_ref="a",
            )
        ],
        advice_fee_charged_pa=gold.fees.ongoing_advice_fee_pa,  # type: ignore[union-attr]
    )
    kinds = [d.kind for d in reconcile(redeem, still_held).discrepancies]
    assert "not_implemented" in kinds
    no_fees = gold.model_copy(update={"fees": None})
    assert all(d.kind != "fee_mismatch" for d in reconcile(no_fees, holdings).discrepancies)


def test_reconcile_evaluation_reports_rates(
    tmp_path: Path, soa_gens: list[GeneratedDocument]
) -> None:
    cases = [(g.gold.soa, g.holdings) for g in soa_gens if g.gold.soa and g.holdings]
    ev = evaluate_reconciliation(cases, n_boot=20)
    assert ev.n_docs == len(cases) and len(ev.kinds) == 4
    assert all(0 <= k.false_alarm_rate.point <= 1 for k in ev.kinds)
    loose = evaluate_reconciliation(cases, amount_tolerance=0.5, n_boot=20, source="gold")
    assert loose.kinds[1].false_alarm_docs <= ev.kinds[1].false_alarm_docs
    md = render_reconcile_evaluation([ev, loose])
    assert md.count("## Source") == 2
    save_reconcile_evaluation([ev], tmp_path)
    assert (tmp_path / "reconcile_report.json").exists()
