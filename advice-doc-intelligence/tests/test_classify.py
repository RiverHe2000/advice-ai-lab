from __future__ import annotations

import json
from pathlib import Path

import pytest

from advicedoc.classify.evaluate import (
    abstain_curve,
    evaluate_classifier,
    metadata_accuracy,
    render_classifier_report,
    save_classifier_report,
)
from advicedoc.classify.features import dense_features
from advicedoc.classify.metadata import extract_metadata
from advicedoc.classify.model import (
    DocumentClassifier,
    stratified_split,
    train_classifier,
)
from advicedoc.classify.zeroshot import classify_zero_shot, make_gold_responder
from advicedoc.corpus.generator import CorpusSpec, GeneratedDocument, generate_documents
from advicedoc.ingest import Document
from advicedoc.llm import ChatMessage, FakeChatModel
from advicedoc.schema import DOC_TYPES


@pytest.fixture(scope="module")
def split_corpus() -> tuple[list[GeneratedDocument], list[GeneratedDocument]]:
    docs = list(generate_documents(CorpusSpec(n_per_type=40, n_soa=40, seed=11)))
    by_type: dict[str, list[GeneratedDocument]] = {}
    for g in docs:
        by_type.setdefault(g.gold.doc_type, []).append(g)
    train = [g for items in by_type.values() for g in items[:30]]
    test = [g for items in by_type.values() for g in items[30:40]]
    return train, test


@pytest.fixture(scope="module")
def classifier(
    split_corpus: tuple[list[GeneratedDocument], list[GeneratedDocument]],
) -> DocumentClassifier:
    train, _ = split_corpus
    return train_classifier([g.document for g in train], [g.gold.doc_type for g in train], seed=0)


def test_classifier_reaches_macro_f1_target(
    classifier: DocumentClassifier,
    split_corpus: tuple[list[GeneratedDocument], list[GeneratedDocument]],
) -> None:
    train, test = split_corpus
    report = evaluate_classifier(
        classifier,
        [g.document for g in test],
        [g.gold.doc_type for g in test],
        n_train=len(train),
        n_boot=50,
        noise_rates=(0.05,),
    )
    assert report.macro_f1.point >= 0.95
    assert report.accuracy.point >= 0.95
    assert set(report.classes) == set(DOC_TYPES)
    assert report.noise["0.05"]["macro_f1"]["point"] >= 0.9
    assert 0.0 <= report.calibration.ece <= 1.0
    md = render_classifier_report(report)
    assert "## Confusion matrix" in md and "## OCR-like noise" in md


def test_abstain_logic_and_persistence(
    tmp_path: Path, classifier: DocumentClassifier, soa_docs: list[Document]
) -> None:
    preds = classifier.predict(soa_docs[:3])
    assert all(p.label == "soa" for p in preds)
    strict = classifier.predict(soa_docs[:3], abstain_threshold=1.01)
    assert all(p.abstained and p.final_label == "unknown" for p in strict)
    assert classifier.predict([]) == []
    path = tmp_path / "clf.joblib"
    classifier.save(path)
    loaded = DocumentClassifier.load(path)
    assert loaded.classes == classifier.classes
    assert loaded.predict_one(soa_docs[0]).label == preds[0].label
    assert loaded.predict_one(soa_docs[0]).confidence == pytest.approx(preds[0].confidence)
    assert classifier.predict_proba([]).shape == (0, len(classifier.classes))


def test_train_rejects_mismatched_lengths(soa_docs: list[Document]) -> None:
    with pytest.raises(ValueError, match="same length"):
        train_classifier(soa_docs[:2], ["soa"])


def test_stratified_split_is_seeded_and_disjoint() -> None:
    labels = ["a"] * 8 + ["b"] * 4 + ["c"]
    train, test = stratified_split(labels, test_frac=0.25, seed=1)
    assert not set(train) & set(test) and len(train) + len(test) == 13
    assert sum(1 for i in test if labels[i] == "a") == 2
    assert sum(1 for i in test if labels[i] == "b") == 1
    assert sum(1 for i in test if labels[i] == "c") == 0
    assert stratified_split(labels, test_frac=0.25, seed=1) == (train, test)


def test_dense_features_shape(soa_docs: list[Document]) -> None:
    feats = dense_features(soa_docs[0])
    assert feats[0] == soa_docs[0].n_pages and feats[1] == soa_docs[0].n_tables
    assert all(f in (0.0, 1.0) for f in feats[4:])


def test_metadata_rules_on_every_type(gens: list[GeneratedDocument]) -> None:
    result = metadata_accuracy([g.document for g in gens], [g.gold.metadata for g in gens])
    assert result["overall"]["client_names"] == 1.0
    assert result["overall"]["adviser_name"] == 1.0
    assert result["overall"]["document_date"] == 1.0
    assert set(result["by_type"]) == set(DOC_TYPES)


def test_metadata_rules_edge_cases() -> None:
    assert extract_metadata(Document(source="e", pages=[])).client_names == []
    letter = Document.from_text(
        "Northshore Financial Advice Pty Ltd\nDate: 3 March 2026\nAlice Oakes and Bruno Oakes\n"
        "12 Banksia Avenue\nMarlow Bay NSW 2107\nDear Alice and Bruno,\nKind regards,\nMargaret Thorne\n"
    )
    guess = extract_metadata(letter)
    assert guess.client_names == ["Alice Oakes", "Bruno Oakes"]
    assert guess.adviser_name == "Margaret Thorne"
    assert str(guess.document_date) == "2026-03-03"
    numbered = Document.from_text(
        "Client 1: Ann Vance\nClient 2: Bob Vance\nAdviser: X Y\nSigned 12/05/2025"
    )
    guess = extract_metadata(numbered)
    assert (
        guess.client_names == ["Ann Vance", "Bob Vance"]
        and str(guess.document_date) == "2025-05-12"
    )
    assert extract_metadata(Document.from_text("nothing here")).document_date is None


def test_zero_shot_paths(gens: list[GeneratedDocument]) -> None:
    labels = {g.gold.doc_id: g.gold.doc_type for g in gens}
    doc = gens[0].document
    good = FakeChatModel(default=make_gold_responder(labels, corruption=0.0))
    result = classify_zero_shot(good, doc)
    assert result.label == gens[0].gold.doc_type and result.confidence == 0.9
    prose = FakeChatModel(default="I believe this is a Fee Disclosure Statement.")
    assert classify_zero_shot(prose, doc).label == "fds"
    garbage = FakeChatModel(default="???")
    missing = classify_zero_shot(garbage, doc)
    assert missing.label is None and missing.reason == "unparseable answer"
    unknown = make_gold_responder({}, corruption=0.0)
    assert unknown([ChatMessage("user", "Document: nope")]) == "I cannot tell."
    corrupt = make_gold_responder(labels, corruption=1.0, seed=3)
    outputs = {corrupt([ChatMessage("user", f"Document: {g.gold.doc_id}")]) for g in gens}
    assert len(outputs) > 3


def test_evaluate_with_zero_shot_and_metadata(
    tmp_path: Path, classifier: DocumentClassifier, gens: list[GeneratedDocument]
) -> None:
    labels = {g.gold.doc_id: g.gold.doc_type for g in gens}
    zs = FakeChatModel(default=make_gold_responder(labels, corruption=0.3, seed=2))
    report = evaluate_classifier(
        classifier,
        [g.document for g in gens],
        [g.gold.doc_type for g in gens],
        n_train=300,
        n_boot=30,
        noise_rates=(),
        zero_shot_model=zs,
        gold_metadata=[g.gold.metadata for g in gens],
    )
    assert report.zero_shot is not None and report.metadata is not None
    assert 0 <= report.zero_shot["vs_ml"]["mcnemar_p"] <= 1
    report.notes.append("note")
    md = render_classifier_report(report)
    assert "Zero-shot LLM baseline" in md and "Metadata rules" in md and "- note" in md
    save_classifier_report(report, tmp_path)
    saved = json.loads((tmp_path / "classifier_report.json").read_text())
    assert saved["n_test"] == len(gens)
    curve = abstain_curve(
        classifier.predict([g.document for g in gens]), [g.gold.doc_type for g in gens]
    )
    assert curve[0]["abstain_rate"] == 0.0 and curve[-1]["threshold"] == 0.99
