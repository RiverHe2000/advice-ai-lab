from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from advicedoc.eval.extraction import compare_strategies, run_extractor, summarise
from advicedoc.eval.matching import (
    ListMatch,
    compare_extraction,
    match_recommendations,
    match_replacements,
    name_lists_match,
    names_match,
    numbers_match,
    products_match,
)
from advicedoc.eval.report import (
    ExtractionReport,
    per_doc_table,
    render_extraction_report,
    save_extraction_report,
)
from advicedoc.extract.llm import LLMExtractor
from advicedoc.extract.rules import RulesExtractor
from advicedoc.ingest import Document
from advicedoc.schema import ProductReplacement, Recommendation, SoAExtraction
from conftest import FakeModelFactory


def test_scalar_matchers() -> None:
    assert numbers_match(Decimal(1000), Decimal(1004))
    assert not numbers_match(Decimal(1000), Decimal(1006))
    assert numbers_match(Decimal("0.3"), Decimal("0.30"))
    assert numbers_match(None, None) and not numbers_match(None, Decimal(1))
    assert names_match("  Alice  OAKES", "alice oakes") and not names_match(None, "x")
    assert names_match(None, None)
    assert name_lists_match(["B Vance", "A Vance"], ["a vance", "b vance"])
    assert products_match("Northshore Wealth Super", "northshore wealth supr")
    assert not products_match("Northshore Wealth Super", "Northshore Wealth Pension")


def test_list_matching_precision_recall() -> None:
    gold = [
        Recommendation(
            action="rollover",
            product_name="Northshore Wealth Super",
            product_type="super",
            amount=Decimal(100),
        ),
        Recommendation(
            action="contribute",
            product_name="Northshore Wealth Super",
            product_type="super",
            amount=Decimal(50),
        ),
        Recommendation(
            action="retain",
            product_name="Fernbank Term Deposit",
            product_type="cash",
            amount=Decimal(20),
        ),
    ]
    pred = [
        gold[0],
        gold[1].model_copy(update={"amount": Decimal(75)}),
        Recommendation(action="insure", product_name="Zenith", product_type="insurance"),
    ]
    m = match_recommendations(pred, gold)
    assert (m.n_pred, m.n_gold, m.matched, m.correct) == (3, 3, 2, 1)
    assert m.item_correct == [True, False, False]
    assert m.precision == pytest.approx(1 / 3) and m.recall == pytest.approx(1 / 3)
    assert not m.exact
    empty = ListMatch(0, 0, 0, 0)
    assert empty.precision == empty.recall == 1.0 and empty.f1 == 1.0 and empty.exact
    assert ListMatch(0, 2, 0, 0).recall == 0.0 and ListMatch(2, 0, 0, 0).precision == 0.0
    reps = [
        ProductReplacement(
            from_product="Aurora Super Fund",
            to_product="Northshore Wealth Super",
            fee_difference_pa=Decimal(-10),
            insurance_impact="none",
        )
    ]
    wrong = [reps[0].model_copy(update={"insurance_impact": "cover_lost"})]
    assert match_replacements(wrong, reps).correct == 0 and match_replacements(reps, reps).exact
    assert match_replacements(
        [reps[0].model_copy(update={"to_product": "Other"})], reps
    ).item_correct == [False]


def test_compare_extraction_document_level(soa_golds: list[SoAExtraction]) -> None:
    gold = soa_golds[0]
    same = compare_extraction(gold, gold)
    assert same.doc_correct and same.field_accuracy == 1.0
    changed = gold.model_copy(deep=True)
    changed.advice_date = date(1999, 1, 1)
    assert not compare_extraction(changed, gold).doc_correct
    partial = compare_extraction(SoAExtraction(), gold)
    assert not partial.doc_correct and partial.fields["fees.initial_advice_fee"] is False


def test_summarise_and_compare_and_report(
    tmp_path: Path,
    soa_docs: list[Document],
    soa_golds: list[SoAExtraction],
    fake_model_factory: FakeModelFactory,
) -> None:
    rules = summarise("rules", run_extractor(RulesExtractor(), soa_docs), soa_golds, n_boot=30)
    llm = summarise(
        "llm",
        run_extractor(
            LLMExtractor(fake_model_factory(0.3)), soa_docs, progress=lambda _doc, _result: None
        ),
        soa_golds,
        n_boot=30,
    )
    assert rules.doc_accuracy.point == 1.0 and llm.doc_accuracy.point < 1.0
    comparisons = compare_strategies([rules, llm], n_boot=30)
    assert len(comparisons) == 1 and comparisons[0].doc_correct.n_pairs == len(soa_docs)
    report = ExtractionReport("t", [rules, llm], comparisons, notes=["n"], settings={"k": 1})
    md = render_extraction_report(report)
    assert "## Paired comparisons" in md and "rules vs llm" in md and "- n" in md
    md_path, js_path = save_extraction_report(report, tmp_path, stem="r")
    assert (
        md_path.exists() and json.loads(js_path.read_text())["strategies"][0]["strategy"] == "rules"
    )
    table = per_doc_table([rules, llm])
    assert table.count("\n") == len(soa_docs) + 2
    with pytest.raises(ValueError, match="one gold"):
        summarise("x", [], soa_golds)
    assert (
        compare_strategies(
            [
                rules,
                summarise(
                    "y", run_extractor(RulesExtractor(), soa_docs[:2]), soa_golds[:2], n_boot=5
                ),
            ]
        )
        == []
    )
