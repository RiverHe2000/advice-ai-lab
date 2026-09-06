from __future__ import annotations

import hashlib
import random
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from advicedoc.corpus.generator import (
    CorpusSpec,
    GeneratedDocument,
    generate_documents,
    licensee_abn,
    load_corpus_document,
    load_holdings,
    load_manifest,
    records_of_type,
    write_corpus,
)
from advicedoc.corpus.holdings import expected_holdings, simulate_holdings
from advicedoc.corpus.layout import (
    STYLES,
    Heading,
    Para,
    TableBlock,
    article,
    block_lines,
    fmt_date,
    fmt_money,
    fmt_pct,
    heading_text,
)
from advicedoc.corpus.products import DEFAULT_MASTER
from advicedoc.corpus.render import column_widths, render_pdf
from advicedoc.identifiers import abn_is_valid, find_tfn_like
from advicedoc.ingest import load_pdf
from advicedoc.schema import DOC_TYPES


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_generation_is_deterministic_and_seed_sensitive(tmp_path: Path) -> None:
    spec = CorpusSpec(n_per_type=2, n_soa=3, seed=7)
    a = write_corpus(spec, tmp_path / "a", render=False)
    b = write_corpus(spec, tmp_path / "b", render=False)
    assert [r.doc_id for r in a] == [r.doc_id for r in b]
    assert _digest(tmp_path / "a" / "manifest.jsonl") == _digest(tmp_path / "b" / "manifest.jsonl")
    for r in a:
        assert _digest(tmp_path / "a" / r.doc_type / f"{r.doc_id}.gold.json") == _digest(
            tmp_path / "b" / r.doc_type / f"{r.doc_id}.gold.json"
        )
    c = write_corpus(CorpusSpec(n_per_type=2, n_soa=3, seed=8), tmp_path / "c", render=False)
    assert c[0].soa != a[0].soa
    assert (tmp_path / "a" / "spec.json").exists()


def test_each_document_has_its_own_rng_stream() -> None:
    small = list(generate_documents(CorpusSpec(n_per_type=1, n_soa=2, seed=7)))
    larger = list(generate_documents(CorpusSpec(n_per_type=2, n_soa=4, seed=7)))
    assert small[0].gold == larger[0].gold
    assert small[1].gold == larger[1].gold


def test_corpus_covers_every_type_with_metadata(gens: list[GeneratedDocument]) -> None:
    types = {g.gold.doc_type for g in gens}
    assert types == set(DOC_TYPES)
    for g in gens:
        meta = g.gold.metadata
        assert meta.client_names and meta.document_date is not None
        assert g.gold.n_pages == g.layout.n_pages >= 1
        if g.gold.doc_type in {"super_statement", "bank_statement"}:
            assert meta.adviser_name is None
        else:
            assert meta.adviser_name
        assert find_tfn_like(g.document.text) == []
    soas = [g for g in gens if g.gold.doc_type == "soa"]
    assert all(4 <= g.layout.n_pages <= 8 for g in soas)
    assert {g.gold.variant for g in gens} == {0, 1, 2}


def test_soa_gold_is_internally_consistent(soa_gens: list[GeneratedDocument]) -> None:
    for g in soa_gens:
        gold = g.gold.soa
        assert gold is not None and gold.fees is not None
        if gold.fees.ongoing_fee_basis == "percent":
            assert gold.fees.ongoing_fee_percent is not None
        for rec in gold.recommendations:
            product = DEFAULT_MASTER.get(rec.product_name)
            assert product is not None and product.product_type == rec.product_type
        for rep in gold.replacements:
            assert DEFAULT_MASTER.get(rep.from_product) and DEFAULT_MASTER.get(rep.to_product)
            assert rep.reason
        assert g.gold.available_funds is not None
        assert abn_is_valid(licensee_abn(3))


def test_pdf_round_trip_recovers_gold_strings(
    tmp_path: Path, soa_gens: list[GeneratedDocument]
) -> None:
    g = soa_gens[0]
    gold = g.gold.soa
    assert gold is not None
    path = tmp_path / "soa.pdf"
    render_pdf(g.layout, path)
    render_pdf(g.layout, tmp_path / "soa2.pdf")
    assert _digest(path) == _digest(tmp_path / "soa2.pdf"), "PDF bytes must be reproducible"
    doc = load_pdf(path)
    text = doc.text
    assert doc.n_pages == g.layout.n_pages
    for name in gold.client_names:
        assert name in text
    assert gold.adviser_name is not None and gold.adviser_name in text
    assert gold.risk_profile is not None and gold.risk_profile in text
    assert fmt_date(gold.advice_date, g.layout.style) in text  # type: ignore[arg-type]
    for rec in gold.recommendations:
        assert rec.product_name in text.replace("\n", " ") or any(
            rec.product_name in " ".join(row) for t in doc.tables for row in t
        )
    if g.layout.style.use_tables:
        rec_table = next(t for t in doc.tables if "Action" in t[0])
        assert len(rec_table) == len(gold.recommendations) + 1
        assert all(len(row) == 6 for row in rec_table)


def test_every_type_renders_and_ingests(tmp_path: Path, gens: list[GeneratedDocument]) -> None:
    seen: set[str] = set()
    for g in gens:
        if g.gold.doc_type in seen:
            continue
        seen.add(g.gold.doc_type)
        path = tmp_path / f"{g.gold.doc_id}.pdf"
        render_pdf(g.layout, path)
        doc = load_pdf(path)
        assert doc.n_pages == g.layout.n_pages
        assert doc.n_tables == g.document.n_tables
        assert g.gold.metadata.client_names[0] in doc.pages[0].text


def test_column_widths_never_split_words() -> None:
    rows = [["#", "Action", "Product"], ["1", "Contribute", "Northshore Wealth Investment Account"]]
    widths = column_widths(rows, 300.0, "Courier", 9.0)
    assert len(widths) == 3 and sum(widths) == pytest.approx(300.0, abs=1e-6)
    tight = column_widths(rows, 60.0, "Courier", 9.0)
    assert sum(tight) == pytest.approx(60.0, abs=1e-6)
    wide = column_widths([["a", "b"]], 1000.0, "Helvetica", 9.0)
    assert sum(wide) == pytest.approx(1000.0, abs=1e-6)


def test_holdings_simulator_records_ground_truth(soa_gens: list[GeneratedDocument]) -> None:
    kinds_seen: set[str] = set()
    for g in soa_gens:
        gold = g.gold.soa
        assert gold is not None and g.holdings is not None
        h = g.holdings
        expected = expected_holdings(gold)
        names = {x.product_name for x in h.holdings}
        for planted in h.planted:
            kinds_seen.add(planted.kind)
            if planted.kind == "not_implemented":
                assert planted.product_name not in names
            elif planted.kind == "unexpected_product":
                assert planted.product_name in names and planted.product_name not in expected
            elif planted.kind == "fee_mismatch":
                assert h.advice_fee_charged_pa == Decimal(planted.observed)
            else:
                holding = next(x for x in h.holdings if x.product_name == planted.product_name)
                assert holding.balance == Decimal(planted.observed)
        assert h.as_of == date.fromordinal(gold.advice_date.toordinal() + 90)  # type: ignore[union-attr]
    forced = simulate_holdings(soa_gens[0].gold.soa, "x", random.Random(1), p_discrepancy=1.0)  # type: ignore[arg-type]
    assert forced.planted
    for _ in range(30):
        forced = simulate_holdings(soa_gens[1].gold.soa, "x", random.Random(_), p_discrepancy=1.0)  # type: ignore[arg-type]
        kinds_seen.update(p.kind for p in forced.planted)
    assert kinds_seen == {
        "not_implemented",
        "amount_mismatch",
        "unexpected_product",
        "fee_mismatch",
    }


def test_manifest_and_loaders(json_corpus: Path) -> None:
    records = load_manifest(json_corpus)
    assert len(records) == 9 * 4 + 12
    soas = records_of_type(records, "soa")
    assert len(soas) == 12 and all(r.holdings_path for r in soas)
    holdings = load_holdings(json_corpus, soas[0])
    assert holdings is not None and holdings.doc_id == soas[0].doc_id
    assert load_holdings(json_corpus, records_of_type(records, "fds")[0]) is None
    doc = load_corpus_document(json_corpus, soas[0])
    assert doc.source == soas[0].doc_id and doc.n_pages == soas[0].n_pages


def test_pdf_corpus_files_exist(pdf_corpus: Path) -> None:
    records = load_manifest(pdf_corpus)
    assert all((pdf_corpus / r.pdf_path).suffix == ".pdf" for r in records)
    doc = load_corpus_document(pdf_corpus, records[0])
    assert doc.n_pages >= 1


def test_layout_formatting_helpers() -> None:
    dollar, aud, words = STYLES
    assert fmt_money(Decimal("1250"), dollar) == "$1,250.00"
    assert fmt_money(Decimal("-1250.4"), dollar) == "-$1,250.40"
    assert fmt_money(Decimal("1250"), aud) == "AUD 1250"
    assert fmt_money(Decimal("-1250"), aud) == "AUD -1250"
    assert fmt_money(Decimal("1250"), words) == "1,250 dollars"
    d = date(2026, 3, 12)
    assert fmt_date(d, dollar) == "12 March 2026"
    assert fmt_date(d, aud) == "12/03/2026"
    assert fmt_date(d, words) == "2026-03-12"
    assert fmt_pct(Decimal("0.30"), dollar) == "0.3%"
    assert fmt_pct(Decimal("1"), aud) == "1 per cent"
    assert heading_text("Fees", 3, words) == "3. FEES"
    assert heading_text("Fees", 3, aud) == "Fees"
    assert article("operations manager") == "an" and article("nurse") == "a"
    tables: list[list[list[str]]] = []
    assert block_lines(Heading("H"), tables) == ["H"]
    assert block_lines(Para("x", "bullet"), tables) == ["- x"]
    assert block_lines(TableBlock((("a", "b"),)), tables) == ["a  b"] and tables == [[["a", "b"]]]
