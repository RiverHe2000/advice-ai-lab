"""Optional semantic-support embedders: a deterministic hashing embedder for tests and a
lazily imported sentence-transformers model (``BAAI/bge-small-en-v1.5``, cached locally)."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Any, Protocol

from filenote.verify.text import content_words


class Embedder(Protocol):
    @property
    def name(self) -> str: ...

    def encode(self, texts: Sequence[str]) -> list[list[float]]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


class HashingEmbedder:
    """Bag of stemmed content words hashed into ``dim`` buckets (sha1, so it is stable across
    processes); L2-normalised. Enough to exercise the semantic path offline."""

    def __init__(self, dim: int = 256) -> None:
        self._dim = dim

    @property
    def name(self) -> str:
        return f"hashing[{self._dim}]"

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            vec = [0.0] * self._dim
            for w in content_words(text):
                h = int(hashlib.sha1(w.encode("utf-8")).hexdigest(), 16)
                vec[h % self._dim] += 1.0 if (h >> 20) % 2 == 0 else -1.0
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            out.append([v / norm for v in vec])
        return out


class SentenceTransformerEmbedder:
    def __init__(
        self, model_name: str = "BAAI/bge-small-en-v1.5", *, model: Any | None = None
    ) -> None:
        self._model_name = model_name
        self._model: Any = model

    @property
    def name(self) -> str:
        return f"sentence-transformers[{self._model_name}]"

    def encode(self, texts: Sequence[str]) -> list[list[float]]:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self._model_name)
        vectors = self._model.encode(list(texts), normalize_embeddings=True)
        return [[float(x) for x in v] for v in vectors]


def build_embedder(name: str) -> Embedder:
    if name == "hashing":
        return HashingEmbedder()
    return SentenceTransformerEmbedder(name)
