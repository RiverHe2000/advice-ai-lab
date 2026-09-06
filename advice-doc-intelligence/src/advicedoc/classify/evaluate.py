"""Classifier evaluation: accuracy and macro-F1 with bootstrap CIs, per-class table, confusion
matrix, ECE with a reliability table, the abstain-rate / accuracy-when-answered curve, the
same test set under OCR-like noise, the zero-shot LLM baseline compared with McNemar on the
same documents, and the accuracy of the rule-based metadata extraction."""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import f1_score

from advicedoc.classify.metadata import extract_metadata
from advicedoc.classify.model import DocumentClassifier, Prediction
from advicedoc.classify.zeroshot import ZeroShotResult, classify_zero_shot
from advicedoc.ingest import Document, apply_noise
from advicedoc.llm import ChatModel
from advicedoc.schema import DocMetadata
from advicedoc.stats import (
    CalibrationResult,
    Interval,
    bootstrap_statistic,
    expected_calibration_error,
    mcnemar_exact,
)
from advicedoc.textutil import normalise_name


@dataclass(slots=True)
class ClassifierReport:
    n_train: int
    n_test: int
    classes: list[str]
    accuracy: Interval
    macro_f1: Interval
    per_class: list[dict[str, Any]]
    confusion: dict[str, dict[str, int]]
    calibration: CalibrationResult
    abstain_curve: list[dict[str, float]]
    noise: dict[str, dict[str, Any]] = field(default_factory=dict)
    zero_shot: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    latency_ms_per_doc: float = 0.0
    calibration_method: str = "sigmoid"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["accuracy"] = self.accuracy.to_dict()
        d["macro_f1"] = self.macro_f1.to_dict()
        d["calibration"] = self.calibration.to_dict()
        return d


def _metrics(
    labels: Sequence[str], predicted: Sequence[str], *, seed: int, n_boot: int
) -> tuple[Interval, Interval]:
    y = np.asarray(labels)
    p = np.asarray(predicted)
    correct = (y == p).astype(np.float64)
    acc = bootstrap_statistic(
        len(y), lambda idx: float(correct[idx].mean()), n_boot=n_boot, seed=seed
    )
    f1 = bootstrap_statistic(
        len(y),
        lambda idx: float(f1_score(y[idx], p[idx], average="macro", zero_division=0)),
        n_boot=n_boot,
        seed=seed,
    )
    return acc, f1


def _per_class(
    labels: Sequence[str], predicted: Sequence[str], classes: Sequence[str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in classes:
        tp = sum(1 for y, p in zip(labels, predicted, strict=True) if y == c and p == c)
        fp = sum(1 for y, p in zip(labels, predicted, strict=True) if y != c and p == c)
        fn = sum(1 for y, p in zip(labels, predicted, strict=True) if y == c and p != c)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append(
            {"class": c, "support": tp + fn, "precision": precision, "recall": recall, "f1": f1}
        )
    return rows


def _confusion(
    labels: Sequence[str], predicted: Sequence[str], classes: Sequence[str]
) -> dict[str, dict[str, int]]:
    table = {c: dict.fromkeys([*classes, "unknown"], 0) for c in classes}
    for y, p in zip(labels, predicted, strict=True):
        table[y][p] = table[y].get(p, 0) + 1
    return table


def abstain_curve(preds: Sequence[Prediction], labels: Sequence[str]) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    for threshold in (0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99):
        answered = [(p, y) for p, y in zip(preds, labels, strict=True) if p.confidence >= threshold]
        acc = float(np.mean([p.label == y for p, y in answered])) if answered else float("nan")
        rows.append(
            {
                "threshold": threshold,
                "abstain_rate": 1.0 - len(answered) / max(1, len(preds)),
                "accuracy_when_answered": acc,
            }
        )
    return rows


def metadata_accuracy(docs: Sequence[Document], gold: Sequence[DocMetadata]) -> dict[str, Any]:
    fields = ("client_names", "adviser_name", "document_date")
    per_type: dict[str, dict[str, list[bool]]] = {}
    for doc, g in zip(docs, gold, strict=True):
        guess = extract_metadata(doc)
        got = {
            "client_names": sorted(normalise_name(n) for n in guess.client_names)
            == sorted(normalise_name(n) for n in g.client_names),
            "adviser_name": (normalise_name(guess.adviser_name or "") or None)
            == (normalise_name(g.adviser_name or "") or None),
            "document_date": guess.document_date == g.document_date,
        }
        bucket = per_type.setdefault(g.doc_type, {f: [] for f in fields})
        for f in fields:
            bucket[f].append(got[f])
    overall = {
        f: float(np.mean([v for t in per_type.values() for v in t[f]]))
        if per_type
        else float("nan")
        for f in fields
    }
    by_type = {t: {f: float(np.mean(v[f])) for f in fields} for t, v in sorted(per_type.items())}
    return {
        "overall": overall,
        "by_type": by_type,
        "n": sum(len(v["client_names"]) for v in per_type.values()),
    }


def evaluate_zero_shot(
    model: ChatModel,
    docs: Sequence[Document],
    labels: Sequence[str],
    ml_correct: Sequence[bool],
    *,
    seed: int,
    n_boot: int,
) -> dict[str, Any]:
    results: list[ZeroShotResult] = [classify_zero_shot(model, d) for d in docs]
    predicted = [r.label or "unknown" for r in results]
    acc, f1 = _metrics(labels, predicted, seed=seed, n_boot=n_boot)
    zs_correct = [p == y for p, y in zip(predicted, labels, strict=True)]
    wins = sum(1 for a, b in zip(zs_correct, ml_correct, strict=True) if a and not b)
    losses = sum(1 for a, b in zip(zs_correct, ml_correct, strict=True) if b and not a)
    return {
        "model": model.name,
        "accuracy": acc.to_dict(),
        "macro_f1": f1.to_dict(),
        "n_missing": sum(1 for r in results if r.label is None),
        "n_repaired": sum(1 for r in results if r.repaired),
        "vs_ml": {
            "zero_shot_wins": wins,
            "ml_wins": losses,
            "mcnemar_p": mcnemar_exact(wins, losses),
        },
    }


def evaluate_classifier(
    clf: DocumentClassifier,
    test_docs: Sequence[Document],
    test_labels: Sequence[str],
    *,
    n_train: int,
    seed: int = 0,
    n_boot: int = 1000,
    noise_rates: Sequence[float] = (0.05, 0.10),
    zero_shot_model: ChatModel | None = None,
    gold_metadata: Sequence[DocMetadata] | None = None,
) -> ClassifierReport:
    started = time.perf_counter()
    preds = clf.predict(test_docs)
    latency_ms = 1000.0 * (time.perf_counter() - started) / max(1, len(test_docs))
    predicted = [p.label for p in preds]
    acc, f1 = _metrics(test_labels, predicted, seed=seed, n_boot=n_boot)
    correct = [p == y for p, y in zip(predicted, test_labels, strict=True)]
    calibration = expected_calibration_error([p.confidence for p in preds], correct)
    report = ClassifierReport(
        n_train=n_train,
        n_test=len(test_docs),
        classes=list(clf.classes),
        accuracy=acc,
        macro_f1=f1,
        per_class=_per_class(test_labels, predicted, clf.classes),
        confusion=_confusion(test_labels, [p.final_label for p in preds], clf.classes),
        calibration=calibration,
        abstain_curve=abstain_curve(preds, test_labels),
        latency_ms_per_doc=latency_ms,
        calibration_method=clf.calibration,
    )
    for rate in noise_rates:
        noisy = [apply_noise(d, rate, seed=seed) for d in test_docs]
        noisy_preds = clf.predict(noisy)
        n_acc, n_f1 = _metrics(
            test_labels, [p.label for p in noisy_preds], seed=seed, n_boot=n_boot
        )
        n_correct = [p.label == y for p, y in zip(noisy_preds, test_labels, strict=True)]
        report.noise[f"{rate:.2f}"] = {
            "accuracy": n_acc.to_dict(),
            "macro_f1": n_f1.to_dict(),
            "ece": expected_calibration_error([p.confidence for p in noisy_preds], n_correct).ece,
            "abstain_rate": float(np.mean([p.abstained for p in noisy_preds])),
        }
    if zero_shot_model is not None:
        report.zero_shot = evaluate_zero_shot(
            zero_shot_model, test_docs, test_labels, correct, seed=seed, n_boot=n_boot
        )
    if gold_metadata is not None:
        report.metadata = metadata_accuracy(test_docs, gold_metadata)
    return report


def render_classifier_report(report: ClassifierReport) -> str:
    lines = [
        "# Document classifier evaluation",
        "",
        f"Train {report.n_train} / test {report.n_test} documents; calibration "
        f"`{report.calibration_method}`; {report.latency_ms_per_doc:.1f} ms per document.",
        "",
        "| Metric | Value [95 % CI] |",
        "|---|---:|",
        f"| Accuracy | {report.accuracy.fmt()} |",
        f"| Macro-F1 | {report.macro_f1.fmt()} |",
        f"| ECE (10 bins) | {report.calibration.ece:.3f} |",
        "",
        "## Per class",
        "",
        "| Class | Support | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|",
    ]
    for row in report.per_class:
        lines.append(
            f"| {row['class']} | {row['support']} | {row['precision']:.3f} | {row['recall']:.3f} | "
            f"{row['f1']:.3f} |"
        )
    lines += ["", "## Confusion matrix (rows = gold, columns = predicted incl. unknown)", ""]
    cols = [*report.classes, "unknown"]
    lines.append("| gold \\ pred | " + " | ".join(cols) + " |")
    lines.append("|---|" + "---:|" * len(cols))
    for c in report.classes:
        lines.append(
            f"| {c} | " + " | ".join(str(report.confusion[c].get(p, 0)) for p in cols) + " |"
        )
    lines += ["", "## Reliability table", "", report.calibration.table_md(), ""]
    lines += [
        "## Abstain curve",
        "",
        "| Threshold | Abstain rate | Accuracy when answered |",
        "|---:|---:|---:|",
    ]
    for row in report.abstain_curve:
        lines.append(
            f"| {row['threshold']:.2f} | {row['abstain_rate']:.3f} | "
            f"{row['accuracy_when_answered']:.3f} |"
        )
    if report.noise:
        lines += [
            "",
            "## OCR-like noise",
            "",
            "| Noise rate | Accuracy | Macro-F1 | ECE | Abstain rate |",
            "|---:|---:|---:|---:|---:|",
        ]
        for rate, m in report.noise.items():
            a = m["accuracy"]
            f = m["macro_f1"]
            lines.append(
                f"| {rate} | {a['point']:.3f} [{a['low']:.3f}, {a['high']:.3f}] | "
                f"{f['point']:.3f} [{f['low']:.3f}, {f['high']:.3f}] | {m['ece']:.3f} | "
                f"{m['abstain_rate']:.3f} |"
            )
    if report.zero_shot is not None:
        z = report.zero_shot
        a = z["accuracy"]
        lines += [
            "",
            f"## Zero-shot LLM baseline ({z['model']})",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Accuracy | {a['point']:.3f} [{a['low']:.3f}, {a['high']:.3f}] |",
            f"| Missing (unparseable) | {z['n_missing']} |",
            f"| JSON repairs | {z['n_repaired']} |",
            f"| Zero-shot wins / ML wins | {z['vs_ml']['zero_shot_wins']} / "
            f"{z['vs_ml']['ml_wins']} |",
            f"| McNemar p | {z['vs_ml']['mcnemar_p']:.3f} |",
        ]
    if report.metadata is not None:
        o = report.metadata["overall"]
        lines += [
            "",
            "## Metadata rules (first page)",
            "",
            "| Field | Accuracy |",
            "|---|---:|",
            f"| client_names | {o['client_names']:.3f} |",
            f"| adviser_name | {o['adviser_name']:.3f} |",
            f"| document_date | {o['document_date']:.3f} |",
            "",
            "| Type | client_names | adviser_name | document_date |",
            "|---|---:|---:|---:|",
        ]
        for t, m in report.metadata["by_type"].items():
            lines.append(
                f"| {t} | {m['client_names']:.3f} | {m['adviser_name']:.3f} | "
                f"{m['document_date']:.3f} |"
            )
    if report.notes:
        lines += ["", "## Notes", "", *[f"- {n}" for n in report.notes]]
    return "\n".join(lines) + "\n"


def save_classifier_report(report: ClassifierReport, out_dir: str | Path) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "classifier_report.md").write_text(render_classifier_report(report), encoding="utf-8")
    (out / "classifier_report.json").write_text(
        json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
    )
