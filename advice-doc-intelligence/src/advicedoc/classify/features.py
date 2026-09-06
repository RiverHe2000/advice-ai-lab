"""Features for the document classifier: word 1-2-gram and character 3-5-gram TF-IDF on the
first two pages, plus a small dense block (page count, table count, digit ratio, length and
~30 domain-term indicator flags)."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from scipy import sparse
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler

from advicedoc.ingest import Document

DOMAIN_TERMS: tuple[str, ...] = (
    "statement of advice",
    "record of advice",
    "fact find",
    "fee disclosure statement",
    "ongoing fee",
    "consent",
    "member statement",
    "policy schedule",
    "authority to proceed",
    "account statement",
    "transaction",
    "opening balance",
    "closing balance",
    "sum insured",
    "premium",
    "risk profile",
    "recommend",
    "best interests",
    "superannuation",
    "pension",
    "dear",
    "regards",
    "bsb",
    "concessional",
    "preservation",
    "usi",
    "life insured",
    "disclosure period",
    "signed",
    "subject:",
    "questionnaire",
    "scope",
)


def head_text(doc: Document, n_pages: int = 2) -> str:
    return doc.head_text(n_pages).lower()


def dense_features(doc: Document) -> list[float]:
    head = head_text(doc)
    full = doc.text
    digits = sum(ch.isdigit() for ch in full)
    return [
        float(doc.n_pages),
        float(doc.n_tables),
        digits / max(1, len(full)),
        math.log1p(len(full)),
        *[1.0 if term in head else 0.0 for term in DOMAIN_TERMS],
    ]


class DocumentFeaturizer:
    """Fit on training documents, transform any documents to one sparse matrix."""

    def __init__(self, *, max_word_features: int = 20000, max_char_features: int = 30000) -> None:
        self.word = TfidfVectorizer(
            ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=max_word_features
        )
        self.char = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(3, 5),
            min_df=2,
            sublinear_tf=True,
            max_features=max_char_features,
        )
        self.scaler = StandardScaler()
        self.n_features_: int = 0

    def fit(self, docs: Sequence[Document]) -> DocumentFeaturizer:
        texts = [head_text(d) for d in docs]
        self.word.fit(texts)
        self.char.fit(texts)
        self.scaler.fit(np.asarray([dense_features(d) for d in docs], dtype=np.float64))
        self.n_features_ = self.transform(docs[:1]).shape[1]
        return self

    def transform(self, docs: Sequence[Document]) -> Any:
        texts = [head_text(d) for d in docs]
        dense = self.scaler.transform(np.asarray([dense_features(d) for d in docs]))
        return sparse.hstack(
            [self.word.transform(texts), self.char.transform(texts), sparse.csr_matrix(dense)],
            format="csr",
        )
