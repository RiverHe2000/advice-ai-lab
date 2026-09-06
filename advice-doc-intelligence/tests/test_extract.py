from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from advicedoc.corpus.generator import GeneratedDocument
from advicedoc.corpus.products import DEFAULT_MASTER
from advicedoc.eval.matching import compare_extraction
from advicedoc.extract import SECTION_NAMES
from advicedoc.extract.fake import CORRUPTIONS, corrupt, gold_section, make_extraction_responder
from advicedoc.extract.llm import (
    SECTION_SPECS,
    LLMExtractor,
    build_section_prompt,
    merge_sections,
    section_text,
)
from advicedoc.extract.rules import RulesExtractor, find_products
from advicedoc.extract.sections import detect_sections, heading_of, table_section
from advicedoc.extract.validated import ValidatedLLMExtractor
from advicedoc.ingest import Document, apply_noise
from advicedoc.llm import ChatMessage, FakeChatModel
from advicedoc.schema import SoAExtraction
from advicedoc.textutil import find_dates, find_money, parse_percent, split_names
from conftest import FakeModelFactory

# ----- text utilities -----------------------------------------------------------------------


def test_date_money_percent_parsers() -> None:
    text = "Dated 12 March 2026, also 12/03/2026 and 2026-03-12, not 31/02/2026."
    assert [d for _, d in find_dates(text)] == [date(2026, 3, 12)] * 3
    money = [m for _, m in find_money("$1,250.00, AUD 1250, 1,250 dollars, -$10.50, AUD -20")]
    assert money == [
        Decimal("1250.00"),
        Decimal(1250),
        Decimal(1250),
        Decimal("-10.50"),
        Decimal(-20),
    ]
    assert parse_percent("0.85% of funds") == Decimal("0.85")
    assert parse_percent("1 per cent") == Decimal(1)
    assert parse_percent("none") is None
    assert split_names("Ann Vance and Bob Vance") == ["Ann Vance", "Bob Vance"]
    assert split_names("Ann Vance; Bob Vance <bob@example.com>") == ["Ann Vance", "Bob Vance"]


# ----- sections -----------------------------------------------------------------------------


def test_section_detection_handles_numbering_and_case(soa_docs: list[Document]) -> None:
    assert heading_of("4. Our recommendations") == "recommendations"
    assert heading_of("WHAT WE RECOMMEND") == "recommendations"
    assert heading_of("Your risk profile: Balanced.") is None
    assert heading_of("4. 0ur recommendatlons") == "recommendations"  # OCR-like corruption
    assert heading_of("FEES AND C0STS") == "fees"
    assert heading_of("Fees are payable monthly from your account") is None
    assert heading_of("aligned to your risk profile.") is None  # wrapped sentence tail
    assert heading_of("") is None
    assert table_section([["Current product", "Recommended product"], ["a", "b"]]) == "replacement"
    assert table_section([["x"]]) is None and table_section([]) is None
    for doc in soa_docs:
        sections = detect_sections(doc)
        assert {"header", "risk", "recommendations", "fees", "scope"} <= set(sections)
        assert sections["recommendations"].text and sections["risk"].pages


# ----- rules --------------------------------------------------------------------------------


def test_rules_extractor_matches_gold_on_clean_text(
    soa_docs: list[Document], soa_golds: list[SoAExtraction]
) -> None:
    rules = RulesExtractor()
    for doc, gold in zip(soa_docs, soa_golds, strict=True):
        result = rules.extract(doc)
        cmp = compare_extraction(result.extraction, gold)
        assert cmp.doc_correct, [k for k, v in cmp.fields.items() if not v]
        assert result.strategy == "rules" and result.available_funds is not None
        assert result.hard_violations == []
        assert result.to_dict()["extraction"]["client_names"] == gold.client_names


def test_rules_extractor_degrades_gracefully_under_noise(
    soa_docs: list[Document], soa_golds: list[SoAExtraction]
) -> None:
    rules = RulesExtractor()
    doc = apply_noise(soa_docs[0], 0.2, seed=1)
    result = rules.extract(doc)
    assert isinstance(result.extraction, SoAExtraction)
    assert result.violations or not compare_extraction(result.extraction, soa_golds[0]).doc_correct
    empty = rules.extract(Document.from_text("nothing to see"))
    assert empty.extraction.recommendations == [] and empty.extraction.fees is None
    assert set(empty.missing) == set(SECTION_NAMES) - {"header"}


def test_find_products_prefers_the_destination() -> None:
    hits = find_products(
        "switch AUD 1000 from Bluegum Diversified Fund to Northshore Balanced Portfolio",
        DEFAULT_MASTER,
    )
    assert [h.product.name for h in hits] == [
        "Bluegum Diversified Fund",
        "Northshore Balanced Portfolio",
    ]
    assert find_products("nothing", DEFAULT_MASTER) == []
    overlapping = find_products("Northshore Wealth Super Northshore Wealth Pension", DEFAULT_MASTER)
    assert {h.product.name for h in overlapping} <= {
        "Northshore Wealth Super",
        "Northshore Wealth Pension",
    }


def test_rules_helpers_cover_fallbacks() -> None:
    from advicedoc.extract.rules import _to_type
    from advicedoc.extract.sections import Section
    from advicedoc.textutil import parse_money

    assert _to_type("Managed portfolio", None) == "managed_portfolio"
    assert _to_type("some idps thing", None) == "idps"
    assert _to_type("mystery", None) is None
    assert RulesExtractor._canon_risk("balanced") == "Balanced"
    assert RulesExtractor._canon_risk("aggressive") is None
    assert parse_money("no money here") is None
    rules = RulesExtractor()
    scores: dict[str, float] = {}
    table = [
        ["#", "Action", "Product", "Type", "Amount", "Account"],
        ["1", "Dance", "x", "y", "z", "w"],
        ["2", "Retain", "Unknown Product", "Mystery", "$5", "A1"],
    ]
    assert rules._recs_from_table(table, scores) == []
    prose = Section(
        "recommendations",
        ["We recommend that you sing. We recommend that you retain nothing of note."],
    )
    assert rules._recs_from_prose(prose, scores) == []
    rep_table = Section("replacement", [], [[["Something", "Else"], ["a", "b"]]])
    assert rules._replacements({"replacement": rep_table}, scores) == []
    assert (
        rules._fees(
            {"fees": Section("fees", ["Initial advice fee is unknown"])}, Document.from_text("")
        )
        is None
    )
    assert (
        rules._fees(
            {"fees": Section("fees", ["Initial advice fee $1 and ongoing advice fee is unclear"])},
            Document.from_text(""),
        )
        is None
    )
    assert rules._authority({"authority": Section("authority", ["nothing decisive"])}) is None
    assert rules._scope({"scope": Section("scope", ["no scope sentence here"])}) == []
    assert (
        RulesExtractor._licensee(Document.from_text("Licensee: Example Advice Pty Ltd"))
        == "Example Advice Pty Ltd"
    )


# ----- llm ----------------------------------------------------------------------------------


def test_llm_extractor_exact_at_zero_corruption(
    soa_docs: list[Document], soa_golds: list[SoAExtraction], fake_model_factory: FakeModelFactory
) -> None:
    extractor = LLMExtractor(fake_model_factory(0.0))
    for doc, gold in zip(soa_docs, soa_golds, strict=True):
        result = extractor.extract(doc)
        assert compare_extraction(result.extraction, gold).doc_correct
        assert result.parse_failures == 0 and result.n_calls >= 6
        assert result.hard_violations == []
        assert "recommendations" in result.field_confidence
    assert extractor.name == "llm" and extractor.model.name == "fake"


def test_llm_extractor_never_silently_accepts_corruption(
    soa_docs: list[Document], soa_golds: list[SoAExtraction], fake_model_factory: FakeModelFactory
) -> None:
    extractor = LLMExtractor(fake_model_factory(0.3, seed=1), max_parse_retries=1)
    wrong = 0
    for doc, gold in zip(soa_docs, soa_golds, strict=True):
        result = extractor.extract(doc)
        cmp = compare_extraction(result.extraction, gold)
        if not cmp.doc_correct:
            wrong += 1
        assert result.retries <= len(SECTION_NAMES)
        for name, reason in result.missing.items():
            assert name in SECTION_NAMES and reason
    assert wrong > 0


def test_parse_retry_is_bounded_and_recorded(soa_docs: list[Document]) -> None:
    model = FakeChatModel(default="not json at all")
    extractor = LLMExtractor(model, max_parse_retries=2)
    result = extractor.extract(soa_docs[0])
    assert set(result.missing) >= {"header", "risk", "recommendations", "fees"}
    assert result.retries == 2 * sum(result.sections_found.values())
    assert result.parse_failures == result.n_calls
    assert result.extraction.risk_profile is None
    assert "unparseable after 3 attempts" in result.missing["risk"]
    assert any("PARSE FEEDBACK" in m.content for call in model.calls for m in call)


def test_validation_failure_triggers_retry(soa_docs: list[Document]) -> None:
    model = FakeChatModel(default='{"risk_profile": "Aggressive"}')
    outcome = LLMExtractor(model, max_parse_retries=1).ask_section(
        "soa_0001", SECTION_SPECS["risk"], "Your risk profile: Aggressive."
    )
    assert (
        outcome.value is None
        and outcome.parse_failures == 2
        and "risk_profile" in (outcome.reason or "")
    )


def test_validated_extractor_reasks_once_per_failing_section(
    soa_docs: list[Document], soa_golds: list[SoAExtraction], fake_model_factory: FakeModelFactory
) -> None:
    plain = LLMExtractor(fake_model_factory(0.4, seed=2))
    validated = ValidatedLLMExtractor(fake_model_factory(0.4, seed=2))
    assert validated.name == "llm_validated"
    total_reasks = 0
    for doc, gold in zip(soa_docs, soa_golds, strict=True):
        before = plain.extract(doc)
        after = validated.extract(doc)
        assert after.reasks <= len(SECTION_NAMES)
        assert after.reasks_fixed <= after.reasks
        assert after.n_calls >= before.n_calls
        total_reasks += after.reasks
        cmp = compare_extraction(after.extraction, gold)
        assert isinstance(cmp.doc_correct, bool)
    assert total_reasks > 0


def test_reask_that_still_fails_keeps_counters(soa_docs: list[Document]) -> None:
    class Flaky:
        def __init__(self) -> None:
            self.n = 0

        def __call__(self, messages: list[ChatMessage]) -> str:
            self.n += 1
            if any("VALIDATION FEEDBACK" in m.content for m in messages):
                return "garbage"
            return '{"risk_profile": null, "recommendations": [], "fees": null, "client_names": [], "replacements": [], "scope": [], "authority_to_proceed_signed": null}'

    model = FakeChatModel(default=Flaky())  # type: ignore[arg-type]
    result = ValidatedLLMExtractor(model, max_parse_retries=0).extract(soa_docs[0])
    assert result.reasks >= 1 and result.reasks_fixed == 0
    assert result.extraction.fees is None


def test_prompt_and_merge_helpers(soa_docs: list[Document]) -> None:
    messages = build_section_prompt("soa_0001", SECTION_SPECS["fees"], "text", max_chars=100)
    assert messages[1].content.startswith("Document: soa_0001\n[section: fees]")
    sections = detect_sections(soa_docs[0])
    assert section_text(sections, SECTION_SPECS["header"], soa_docs[0]) == soa_docs[0].pages[0].text
    assert section_text({}, SECTION_SPECS["fees"], soa_docs[0]) is None
    merged = merge_sections({"risk": SECTION_SPECS["risk"].model(risk_profile="Growth"), "x": None})
    assert merged.risk_profile == "Growth" and merged.recommendations == []


# ----- fake responder -----------------------------------------------------------------------


@pytest.mark.parametrize("section", list(CORRUPTIONS))
def test_every_corruption_mode_produces_text(section: str, soa_golds: list[SoAExtraction]) -> None:
    import random

    for gold in soa_golds[:3]:
        payload = gold_section(gold, section)
        for mode in CORRUPTIONS[section]:
            text = corrupt(dict(payload), section, mode, random.Random(0))
            assert isinstance(text, str) and text
            if mode != "truncate":
                parsed = json.loads(text)
                assert parsed != payload or section in {"scope", "header"}


def test_responder_handles_unknown_documents_and_reasks(
    gold_by_id: dict[str, SoAExtraction],
) -> None:
    respond = make_extraction_responder(gold_by_id, corruption=0.0)
    assert respond([ChatMessage("user", "Document: nope\n[section: fees]")]).startswith("Sorry")
    doc_id = next(iter(gold_by_id))
    text = respond([ChatMessage("user", f"Document: {doc_id}\n[section: risk]")])
    assert json.loads(text.strip("`json\n"))["risk_profile"] == gold_by_id[doc_id].risk_profile
    fixed = make_extraction_responder(gold_by_id, corruption=1.0, p_fix_on_reask=1.0)
    reask = fixed(
        [
            ChatMessage("user", f"Document: {doc_id}\n[section: risk]"),
            ChatMessage("user", "VALIDATION FEEDBACK: x"),
        ]
    )
    assert json.loads(reask)["risk_profile"] == gold_by_id[doc_id].risk_profile


def test_generated_soa_headers_feed_the_header_prompt(soa_gens: list[GeneratedDocument]) -> None:
    for g in soa_gens:
        header = section_text(detect_sections(g.document), SECTION_SPECS["header"], g.document)
        assert header is not None and g.gold.metadata.adviser_name in header  # type: ignore[operator]
