"""The document classifier: logistic regression with calibrated probabilities
(``CalibratedClassifierCV`` on held-out folds) and an abstain threshold below which a
document is labelled ``unknown`` and routed to a human."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold

from advicedoc.classify.features import DocumentFeaturizer
from advicedoc.ingest import Document

UNKNOWN = "unknown"
Calibration = Literal["sigmoid", "isotonic"]


@dataclass(frozen=True, slots=True)
class Prediction:
    label: str
    confidence: float
    probabilities: dict[str, float]
    abstained: bool

    @property
    def final_label(self) -> str:
        return UNKNOWN if self.abstained else self.label


class DocumentClassifier:
    def __init__(
        self,
        featurizer: DocumentFeaturizer,
        model: Any,
        classes: list[str],
        *,
        abstain_threshold: float = 0.6,
        calibration: str = "sigmoid",
    ) -> None:
        self.featurizer = featurizer
        self.model = model
        self.classes = classes
        self.abstain_threshold = abstain_threshold
        self.calibration = calibration

    def predict_proba(self, docs: Sequence[Document]) -> np.ndarray:
        if not docs:
            return np.zeros((0, len(self.classes)))
        probs: np.ndarray = self.model.predict_proba(self.featurizer.transform(docs))
        return probs

    def predict(
        self, docs: Sequence[Document], *, abstain_threshold: float | None = None
    ) -> list[Prediction]:
        threshold = self.abstain_threshold if abstain_threshold is None else abstain_threshold
        probs = self.predict_proba(docs)
        out: list[Prediction] = []
        for row in probs:
            best = int(np.argmax(row))
            conf = float(row[best])
            out.append(
                Prediction(
                    label=self.classes[best],
                    confidence=conf,
                    probabilities={c: float(p) for c, p in zip(self.classes, row, strict=True)},
                    abstained=conf < threshold,
                )
            )
        return out

    def predict_one(self, doc: Document) -> Prediction:
        return self.predict([doc])[0]

    def save(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "featurizer": self.featurizer,
                "model": self.model,
                "classes": self.classes,
                "abstain_threshold": self.abstain_threshold,
                "calibration": self.calibration,
            },
            path,
        )

    @classmethod
    def load(cls, path: str | Path) -> DocumentClassifier:
        blob = joblib.load(path)
        return cls(
            blob["featurizer"],
            blob["model"],
            list(blob["classes"]),
            abstain_threshold=float(blob["abstain_threshold"]),
            calibration=str(blob.get("calibration", "sigmoid")),
        )


def stratified_split(
    labels: Sequence[str], *, test_frac: float = 0.25, seed: int = 0
) -> tuple[list[int], list[int]]:
    """Seeded stratified train/test index split (at least one test item per class)."""
    rng = np.random.default_rng(seed)
    by_label: dict[str, list[int]] = {}
    for i, label in enumerate(labels):
        by_label.setdefault(label, []).append(i)
    train: list[int] = []
    test: list[int] = []
    for label in sorted(by_label):
        idx = np.asarray(by_label[label])
        rng.shuffle(idx)
        n_test = max(1, round(len(idx) * test_frac)) if len(idx) > 1 else 0
        test.extend(int(i) for i in idx[:n_test])
        train.extend(int(i) for i in idx[n_test:])
    return sorted(train), sorted(test)


def train_classifier(
    docs: Sequence[Document],
    labels: Sequence[str],
    *,
    seed: int = 0,
    c: float = 4.0,
    calibration: Calibration = "sigmoid",
    cv: int = 3,
    abstain_threshold: float = 0.6,
) -> DocumentClassifier:
    if len(docs) != len(labels):
        msg = "docs and labels must have the same length"
        raise ValueError(msg)
    featurizer = DocumentFeaturizer().fit(docs)
    x = featurizer.transform(docs)
    y = np.asarray(labels)
    base = LogisticRegression(C=c, solver="lbfgs", max_iter=3000, random_state=seed)
    folds = StratifiedKFold(n_splits=cv, shuffle=True, random_state=seed)
    model = CalibratedClassifierCV(estimator=base, method=calibration, cv=folds)
    model.fit(x, y)
    return DocumentClassifier(
        featurizer,
        model,
        [str(c_) for c_ in model.classes_],
        abstain_threshold=abstain_threshold,
        calibration=calibration,
    )
