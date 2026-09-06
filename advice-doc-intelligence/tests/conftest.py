"""Offline fixtures: small seeded corpora (in memory, JSON documents, and a handful of real
PDFs), gold lookups, scripted models and stub components. Nothing downloads."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from advicedoc.classify.model import Prediction
from advicedoc.corpus.generator import (
    CorpusSpec,
    GeneratedDocument,
    generate_documents,
    write_corpus,
)
from advicedoc.extract.fake import make_extraction_responder
from advicedoc.ingest import Document
from advicedoc.llm import FakeChatModel
from advicedoc.schema import DOC_TYPES, GoldRecord, SoAExtraction


@pytest.fixture(scope="session")
def gens() -> list[GeneratedDocument]:
    return list(generate_documents(CorpusSpec(n_per_type=3, n_soa=8, seed=3)))


@pytest.fixture(scope="session")
def soa_gens(gens: list[GeneratedDocument]) -> list[GeneratedDocument]:
    return [g for g in gens if g.gold.doc_type == "soa"]


@pytest.fixture(scope="session")
def soa_docs(soa_gens: list[GeneratedDocument]) -> list[Document]:
    return [g.document for g in soa_gens]


@pytest.fixture(scope="session")
def soa_golds(soa_gens: list[GeneratedDocument]) -> list[SoAExtraction]:
    return [g.gold.soa for g in soa_gens if g.gold.soa is not None]


@pytest.fixture(scope="session")
def gold_by_id(soa_gens: list[GeneratedDocument]) -> dict[str, SoAExtraction]:
    return {g.gold.doc_id: g.gold.soa for g in soa_gens if g.gold.soa is not None}


FakeModelFactory = Callable[..., FakeChatModel]


@pytest.fixture
def fake_model_factory(gold_by_id: dict[str, SoAExtraction]) -> FakeModelFactory:
    def factory(corruption: float = 0.0, seed: int = 1) -> FakeChatModel:
        return FakeChatModel(
            default=make_extraction_responder(gold_by_id, corruption=corruption, seed=seed)
        )

    return factory


@pytest.fixture(scope="session")
def json_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("json_corpus")
    write_corpus(CorpusSpec(n_per_type=4, n_soa=12, seed=11), out, render=False)
    return out


@pytest.fixture(scope="session")
def pdf_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("pdf_corpus")
    write_corpus(CorpusSpec(n_per_type=1, n_soa=3, seed=5), out, render=True)
    return out


class PrefixClassifier:
    """Reads the document type from the corpus id (``soa_0001`` -> ``soa``)."""

    def __init__(self, confidence: float = 0.95) -> None:
        self.confidence = confidence

    def predict_one(self, doc: Document) -> Prediction:
        label = next((t for t in DOC_TYPES if f"{t}_" in doc.source), "unknown")
        return Prediction(label, self.confidence, {label: self.confidence}, self.confidence < 0.6)


@pytest.fixture
def prefix_classifier() -> PrefixClassifier:
    return PrefixClassifier()


def record_by_id(records: list[GoldRecord], doc_id: str) -> GoldRecord:
    return next(r for r in records if r.doc_id == doc_id)
