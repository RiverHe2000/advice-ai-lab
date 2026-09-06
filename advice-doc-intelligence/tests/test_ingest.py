from __future__ import annotations

import json
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from advicedoc.corpus.generator import GeneratedDocument
from advicedoc.ingest import (
    Document,
    apply_noise,
    document_from_json,
    document_to_json,
    lines_from_words,
    load_document,
    load_many,
)


def test_document_constructors() -> None:
    doc = Document.from_text("a\nb\fc", source="t")
    assert doc.n_pages == 2 and doc.pages[1].lines == ["c"]
    assert doc.text == "a\nb\nc" and doc.lines == ["a", "b", "c"]
    assert doc.head_text(1) == "a\nb"
    tabled = Document.from_pages([(["x"], [[["h1", "h2"], ["1", "2"]]])])
    assert tabled.n_tables == 1 and tabled.tables[0][1] == ["1", "2"]
    assert tabled.pages[0].number == 1


def test_lines_from_words_clusters_by_vertical_position() -> None:
    words = [
        {"text": "world", "top": 10.0, "x0": 40.0},
        {"text": "hello", "top": 11.0, "x0": 10.0},
        {"text": "next", "top": 30.0, "x0": 10.0},
    ]
    assert lines_from_words(words) == ["hello world", "next"]


def test_noise_is_seeded_and_bounded(soa_docs: list[Document]) -> None:
    doc = soa_docs[0]
    assert apply_noise(doc, 0.0) is doc
    a = apply_noise(doc, 0.1, seed=1)
    b = apply_noise(doc, 0.1, seed=1)
    c = apply_noise(doc, 0.1, seed=2)
    assert a.text == b.text and a.text != c.text and a.text != doc.text
    changed = Levenshtein.distance(a.text, doc.text)
    assert 0 < changed <= 0.2 * len(doc.text)
    assert a.n_tables == doc.n_tables and a.source == doc.source


def test_json_round_trip_and_load_document(tmp_path: Path, soa_docs: list[Document]) -> None:
    doc = soa_docs[0]
    dumped = document_to_json(doc)
    back = document_from_json(dumped)
    assert back.text == doc.text and back.tables == doc.tables and back.source == doc.source
    json_path = tmp_path / "soa_0001.doc.json"
    json_path.write_text(dumped, encoding="utf-8")
    assert load_document(json_path).source == "soa_0001"
    txt = tmp_path / "note.txt"
    txt.write_text("page one\fpage two", encoding="utf-8")
    assert load_document(txt).n_pages == 2


def test_load_many_uses_cache(
    tmp_path: Path, pdf_corpus: Path, gens: list[GeneratedDocument]
) -> None:
    del gens
    paths = sorted(pdf_corpus.glob("*/*.pdf"))[:2]
    cache = tmp_path / "cache.json"
    first = load_many(paths, cache_path=cache)
    assert cache.exists() and len(json.loads(cache.read_text())) == 2
    seen: list[tuple[int, int]] = []
    second = load_many(paths, cache_path=cache, progress=lambda i, n: seen.append((i, n)))
    assert [d.text for d in first] == [d.text for d in second]
    assert seen == [(1, 2), (2, 2)]
