"""The review router model: standardised features -> logistic regression -> isotonic
calibration on held-out folds grouped by document, so P(field correct) is a probability a
reviewer can act on. Cross-validated out-of-fold probabilities feed the evaluation."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from advicedoc.route.features import FEATURE_NAMES, FieldRecord

Route = Literal["review", "auto"]


class ConstantModel:
    """Stands in when the training labels have a single class."""

    def __init__(self, p: float) -> None:
        self.p = p

    def predict_proba(self, x: Any) -> np.ndarray:
        n = int(np.asarray(x).shape[0])
        return np.column_stack([np.full(n, 1.0 - self.p), np.full(n, self.p)])


def _matrix(records: Sequence[FieldRecord]) -> np.ndarray:
    return np.asarray([r.vector() for r in records], dtype=np.float64)


def _labels(records: Sequence[FieldRecord]) -> np.ndarray:
    return np.asarray([int(bool(r.correct)) for r in records], dtype=np.int64)


class ReviewRouter:
    def __init__(
        self, model: Any, *, tau: float = 0.5, feature_names: Sequence[str] = FEATURE_NAMES
    ) -> None:
        self.model = model
        self.tau = tau
        self.feature_names = list(feature_names)

    def predict_proba(self, records: Sequence[FieldRecord]) -> np.ndarray:
        if not records:
            return np.zeros(0)
        probs: np.ndarray = self.model.predict_proba(_matrix(records))[:, 1]
        return probs

    def doc_scores(self, records: Sequence[FieldRecord]) -> dict[str, float]:
        """Minimum P(correct) over the fields of each document."""
        scores: dict[str, float] = {}
        for rec, p in zip(records, self.predict_proba(records), strict=True):
            scores[rec.doc_id] = min(scores.get(rec.doc_id, 1.0), float(p))
        return scores

    def decide(
        self, records: Sequence[FieldRecord], *, tau: float | None = None
    ) -> dict[str, Route]:
        t = self.tau if tau is None else tau
        return {d: ("review" if s < t else "auto") for d, s in self.doc_scores(records).items()}

    def coefficients(self) -> dict[str, float] | None:
        est = getattr(self.model, "_reference_estimator", None)
        if est is None:
            return None
        coef = est[-1].coef_[0]
        return {n: float(c) for n, c in zip(self.feature_names, coef, strict=True)}

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": self.model, "tau": self.tau, "features": self.feature_names}, path)

    @classmethod
    def load(cls, path: str | Path) -> ReviewRouter:
        blob = joblib.load(path)
        return cls(blob["model"], tau=float(blob["tau"]), feature_names=list(blob["features"]))


def train_router(
    records: Sequence[FieldRecord], *, seed: int = 0, cv: int = 5, tau: float = 0.5, c: float = 1.0
) -> ReviewRouter:
    labelled = [r for r in records if r.correct is not None]
    if not labelled:
        msg = "router training needs labelled records"
        raise ValueError(msg)
    x = _matrix(labelled)
    y = _labels(labelled)
    if len(set(y.tolist())) < 2:
        return ReviewRouter(ConstantModel(float(y.mean())), tau=tau)
    groups = np.asarray([r.doc_id for r in labelled])
    n_groups = len(set(groups.tolist()))
    n_splits = max(2, min(cv, n_groups))
    base = make_pipeline(
        StandardScaler(), LogisticRegression(C=c, max_iter=2000, random_state=seed)
    )
    folds = list(GroupKFold(n_splits=n_splits).split(x, y, groups))
    usable = [
        f for f in folds if len(set(y[f[0]].tolist())) == 2 and len(set(y[f[1]].tolist())) == 2
    ]
    if len(usable) >= 2:
        model: Any = CalibratedClassifierCV(estimator=base, method="isotonic", cv=usable)
    else:
        model = base
    model.fit(x, y)
    reference = make_pipeline(
        StandardScaler(), LogisticRegression(C=c, max_iter=2000, random_state=seed)
    )
    reference.fit(x, y)
    model._reference_estimator = reference
    return ReviewRouter(model, tau=tau)


def cross_val_probabilities(
    records: Sequence[FieldRecord], *, seed: int = 0, cv: int = 5
) -> np.ndarray:
    """Out-of-fold P(correct) for every labelled record, folds grouped by document."""
    labelled = [r for r in records if r.correct is not None]
    groups = np.asarray([r.doc_id for r in labelled])
    n_groups = len(set(groups.tolist()))
    probs = np.zeros(len(labelled))
    if n_groups < 2:
        return probs + float(_labels(labelled).mean()) if labelled else probs
    n_splits = max(2, min(cv, n_groups))
    x = _matrix(labelled)
    for train_idx, test_idx in GroupKFold(n_splits=n_splits).split(x, _labels(labelled), groups):
        router = train_router([labelled[i] for i in train_idx], seed=seed, cv=cv)
        probs[test_idx] = router.predict_proba([labelled[i] for i in test_idx])
    return probs
