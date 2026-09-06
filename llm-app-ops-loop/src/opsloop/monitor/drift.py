"""Text-input drift: embed each request (hashing embedder by default; sentence-transformers
optional), fit k-means on a baseline window, and test the topic mix of the current window
against the baseline with a two-sample chi-square test **and** a Jensen-Shannon distance above
a bootstrap threshold. Reports which topics grew and their characteristic terms."""

from __future__ import annotations

import math
import re
import zlib
from collections import Counter
from collections.abc import Sequence
from itertools import pairwise
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, Field
from scipy import stats as sps
from sklearn.cluster import KMeans

from opsloop.stats import chi_square_two_sample, js_distance

_TOKEN = re.compile(r"[a-z][a-z'-]{2,}")
STOPWORDS = frozenset(
    [
        "the", "and", "for", "with", "what", "does", "this", "that", "from", "into", "have",
        "has", "how", "much", "many", "when", "were", "which", "their", "they", "them", "did",
        "will", "would", "should", "could", "can", "our", "your", "his", "her", "its", "are",
        "was", "is", "about", "over", "under", "onto", "than", "then", "there", "here", "any",
        "all", "each", "per", "via",
    ]
)  # fmt: skip


class Embedder(Protocol):
    def embed(self, texts: Sequence[str], *, vocab: set[str] | None = None) -> np.ndarray: ...


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]


class HashingEmbedder:
    """Signed feature hashing of unigrams + bigrams, L2-normalised. Deterministic across
    processes (crc32, not Python's salted ``hash``)."""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, texts: Sequence[str], *, vocab: set[str] | None = None) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float64)
        for i, text in enumerate(texts):
            toks = [t for t in tokens(text) if vocab is None or t in vocab]
            grams = toks + [f"{a}_{b}" for a, b in pairwise(toks)]
            for g in grams:
                h = zlib.crc32(g.encode("utf-8"))
                sign = 1.0 if (h >> 31) & 1 else -1.0
                out[i, h % self.dim] += sign
            norm = np.linalg.norm(out[i])
            if norm > 0:
                out[i] /= norm
        return out


class SentenceTransformerEmbedder:  # pragma: no cover - optional dependency, GPU stage
    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: Sequence[str], *, vocab: set[str] | None = None) -> np.ndarray:
        del vocab  # dense embeddings do not need the vocabulary filter
        return np.asarray(
            self._model.encode(list(texts), normalize_embeddings=True), dtype=np.float64
        )


def build_embedder(kind: str = "hashing", *, dim: int = 256) -> Embedder:
    if kind == "sentence-transformers":  # pragma: no cover
        return SentenceTransformerEmbedder()
    return HashingEmbedder(dim)


class TopicModel:
    """k-means over embedded requests plus a **novelty bucket**.

    At fit time the model learns a radius (the ``novelty_quantile`` of baseline distances to
    the nearest centroid); a request farther than that from every centroid is assigned to the
    extra topic ``k`` ("novel"); so is a request whose share of tokens outside the fitted
    vocabulary exceeds the same quantile of held-out baseline shares. Questions built from
    vocabulary the baseline never saw land there, which is what a topic shift looks like in
    production. The proportions the drift
    test compares against are estimated on a held-out half of the baseline, not on the texts
    k-means was fitted to (in-sample counts are too tight and make ordinary windows look
    drifted). Tokens seen in fewer than ``min_df`` baseline texts can optionally be dropped."""

    def __init__(
        self,
        embedder: Embedder,
        *,
        k: int = 8,
        seed: int = 0,
        min_df: int = 0,
        holdout: float = 0.5,
        novelty_quantile: float = 0.95,
    ) -> None:
        self.embedder = embedder
        self.k = k
        self.seed = seed
        self.min_df = min_df
        self.holdout = holdout
        self.novelty_quantile = novelty_quantile
        self.vocab: set[str] | None = None
        self.radius: float = math.inf
        self.fit_vocab: set[str] = set()
        self.oov_threshold: float = math.inf
        self._km: KMeans | None = None
        self.baseline_counts: np.ndarray | None = None
        self.baseline_terms: list[list[str]] = []

    def fit(self, texts: Sequence[str]) -> TopicModel:
        if self.min_df > 0:
            df: Counter[str] = Counter()
            for text in texts:
                df.update(set(tokens(text)))
            self.vocab = {t for t, c in df.items() if c >= self.min_df} or None
        n = len(texts)
        split = int(n * (1.0 - self.holdout))
        use_holdout = self.holdout > 0 and split >= 2 * self.k and n - split >= self.k
        fit_texts = list(texts[:split]) if use_holdout else list(texts)
        count_texts = list(texts[split:]) if use_holdout else list(texts)
        k = max(1, min(self.k, len(fit_texts)))
        x = self.embedder.embed(fit_texts, vocab=self.vocab)
        self._km = KMeans(n_clusters=k, n_init=4, random_state=self.seed).fit(x)
        self.fit_vocab = {t for text in fit_texts for t in tokens(text)}
        # Calibrate both novelty rules out of sample: in-sample distances (and an in-sample
        # vocabulary) are optimistic.
        calib_texts = count_texts if use_holdout else fit_texts
        calib = self.embedder.embed(calib_texts, vocab=self.vocab) if use_holdout else x
        nearest = self._km.transform(calib).min(axis=1)
        self.radius = (
            float(np.quantile(nearest, self.novelty_quantile)) if nearest.size else math.inf
        )
        oov = np.asarray([self.oov_share(t) for t in calib_texts], dtype=np.float64)
        self.oov_threshold = (
            float(np.quantile(oov, self.novelty_quantile)) if oov.size and use_holdout else math.inf
        )
        labels = self.assign(count_texts)
        self.baseline_counts = np.bincount(labels, minlength=k + 1).astype(np.float64)
        self.baseline_terms = self.top_terms(count_texts, labels)
        return self

    @property
    def n_topics(self) -> int:
        """Clusters plus the novelty bucket (index ``k``)."""
        return int(self._km.n_clusters) + 1 if self._km is not None else 0

    @property
    def novel_index(self) -> int:
        return self.n_topics - 1

    def assign(self, texts: Sequence[str]) -> np.ndarray:
        if self._km is None:
            msg = "TopicModel.fit must run first"
            raise RuntimeError(msg)
        if not texts:
            return np.zeros(0, dtype=np.int64)
        d = self._km.transform(self.embedder.embed(texts, vocab=self.vocab))
        labels = np.asarray(d.argmin(axis=1), dtype=np.int64)
        oov = np.asarray([self.oov_share(t) for t in texts], dtype=np.float64)
        labels[(d.min(axis=1) > self.radius) | (oov > self.oov_threshold)] = self.novel_index
        return labels

    def oov_share(self, text: str) -> float:
        """Share of a request's tokens that the fitted baseline vocabulary never saw."""
        toks = tokens(text)
        if not toks:
            return 0.0
        return sum(1 for t in toks if t not in self.fit_vocab) / len(toks)

    def top_terms(self, texts: Sequence[str], labels: Any, *, n: int = 4) -> list[list[str]]:
        counters: list[Counter[str]] = [Counter() for _ in range(self.n_topics)]
        for text, label in zip(texts, labels, strict=True):
            counters[int(label)].update(tokens(text))
        return [[t for t, _ in c.most_common(n)] for c in counters]


class TopicShift(BaseModel):
    topic: int
    novel: bool = False
    baseline_share: float
    current_share: float
    delta: float
    terms: list[str]


class DriftResult(BaseModel):
    n_baseline: int
    n_current: int
    js: float
    threshold: float
    chi2: float
    p_value: float
    novel_share_baseline: float = 0.0
    novel_share_current: float = 0.0
    novel_p_value: float = 1.0
    trigger: str = ""
    drifted: bool
    grown: list[TopicShift] = Field(default_factory=list)
    baseline_counts: list[int] = Field(default_factory=list)
    current_counts: list[int] = Field(default_factory=list)


def bootstrap_js_threshold(
    baseline_counts: Any, n_current: int, *, n_boot: int, quantile: float, seed: int
) -> float:
    """JS distance a window of ``n_current`` draws from the *baseline* mix reaches by chance."""
    base = np.asarray(baseline_counts, dtype=np.float64)
    if base.sum() <= 0 or n_current <= 0:
        return math.inf
    p = base / base.sum()
    rng = np.random.default_rng(seed)
    draws = rng.multinomial(n_current, p, size=n_boot)
    values = [js_distance(p, d) for d in draws]
    return float(np.quantile(values, quantile))


def drift_test(
    model: TopicModel,
    current_texts: Sequence[str],
    *,
    alpha: float = 0.01,
    n_boot: int = 200,
    quantile: float = 0.99,
    seed: int = 0,
    novel_alpha: float = 0.001,
    novel_min: int = 5,
) -> DriftResult:
    """Two triggers: the whole topic mix moved (two-sample chi-square at ``alpha`` AND the JS
    distance above its bootstrap threshold), or the *novel* bucket alone grew (one-sided
    binomial test of the current novel count against the baseline novel share at
    ``novel_alpha``, with at least ``novel_min`` novel requests). The second is the targeted
    test for unseen question types; the first catches re-weighting among known topics."""
    if model.baseline_counts is None:
        msg = "TopicModel.fit must run first"
        raise RuntimeError(msg)
    k = model.n_topics
    labels = model.assign(current_texts)
    current = np.bincount(labels, minlength=k).astype(np.float64)
    base = model.baseline_counts
    js = js_distance(base, current)
    threshold = bootstrap_js_threshold(
        base, int(current.sum()), n_boot=n_boot, quantile=quantile, seed=seed
    )
    chi2, p = chi_square_two_sample([int(v) for v in base], [int(v) for v in current])
    mix_drift = bool(p < alpha and js > threshold)
    nv = model.novel_index
    base_novel = float(base[nv] / base.sum()) if base.sum() > 0 else 0.0
    cur_novel_n = int(current[nv])
    n_cur = int(current.sum())
    cur_novel = cur_novel_n / n_cur if n_cur else 0.0
    novel_p = 1.0
    if n_cur and 0.0 < base_novel < 1.0:
        novel_p = float(sps.binomtest(cur_novel_n, n_cur, base_novel, alternative="greater").pvalue)
    novel_drift = bool(novel_p < novel_alpha and cur_novel_n >= novel_min)
    drifted = mix_drift or novel_drift
    trigger = "+".join(t for t, on in (("mix", mix_drift), ("novel", novel_drift)) if on)
    grown: list[TopicShift] = []
    if current.sum() > 0 and base.sum() > 0:
        terms = (
            model.top_terms(current_texts, labels) if len(current_texts) else model.baseline_terms
        )
        for t in range(k):
            b_share = float(base[t] / base.sum())
            c_share = float(current[t] / current.sum())
            if c_share - b_share > 0.02:
                grown.append(
                    TopicShift(
                        topic=t,
                        novel=t == model.novel_index,
                        baseline_share=round(b_share, 4),
                        current_share=round(c_share, 4),
                        delta=round(c_share - b_share, 4),
                        terms=terms[t] if t < len(terms) else [],
                    )
                )
        grown.sort(key=lambda s: -s.delta)
    return DriftResult(
        n_baseline=int(base.sum()),
        n_current=int(current.sum()),
        js=round(js, 5),
        threshold=round(threshold, 5),
        chi2=round(chi2, 3),
        p_value=p,
        novel_share_baseline=round(base_novel, 4),
        novel_share_current=round(cur_novel, 4),
        novel_p_value=novel_p,
        trigger=trigger,
        drifted=drifted,
        grown=grown,
        baseline_counts=[int(v) for v in base],
        current_counts=[int(v) for v in current],
    )
