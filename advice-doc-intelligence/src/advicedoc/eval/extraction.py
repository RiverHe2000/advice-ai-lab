"""Run one or more extractors over gold SoAs and measure them: per-field accuracy with
bootstrap CIs, recommendation / replacement precision-recall-F1, document-level accuracy,
repairs, retries, re-asks, latency and token cost, and paired comparisons (bootstrap on
per-document differences, exact McNemar on document correctness) between strategies."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from advicedoc.eval.matching import ALL_FIELDS, ExtractionComparison, compare_extraction
from advicedoc.extract import ExtractionResult, Extractor
from advicedoc.ingest import Document
from advicedoc.schema import SoAExtraction
from advicedoc.stats import Interval, PairedComparison, bootstrap_mean, paired_bootstrap


@dataclass(slots=True)
class DocOutcome:
    doc_id: str
    correct: bool
    field_accuracy: float
    fields: dict[str, bool]
    rec_f1: float
    repl_f1: float
    hard_violations: int
    repairs: int
    latency_s: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "correct": self.correct,
            "field_accuracy": self.field_accuracy,
            "fields": self.fields,
            "rec_f1": self.rec_f1,
            "repl_f1": self.repl_f1,
            "hard_violations": self.hard_violations,
            "repairs": self.repairs,
            "latency_s": self.latency_s,
        }


@dataclass(slots=True)
class StrategyEvaluation:
    strategy: str
    n_docs: int
    doc_accuracy: Interval
    field_accuracy: Interval
    per_field: dict[str, Interval]
    recommendations: dict[str, Interval]
    replacements: dict[str, Interval]
    repairs: int
    parse_failures: int
    retries: int
    reasks: int
    reasks_fixed: int
    n_calls: int
    prompt_tokens: int
    completion_tokens: int
    latency_s_per_doc: float
    missing_sections: dict[str, int]
    violations_by_code: dict[str, int]
    per_doc: list[DocOutcome] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "n_docs": self.n_docs,
            "doc_accuracy": self.doc_accuracy.to_dict(),
            "field_accuracy": self.field_accuracy.to_dict(),
            "per_field": {k: v.to_dict() for k, v in self.per_field.items()},
            "recommendations": {k: v.to_dict() for k, v in self.recommendations.items()},
            "replacements": {k: v.to_dict() for k, v in self.replacements.items()},
            "repairs": self.repairs,
            "parse_failures": self.parse_failures,
            "retries": self.retries,
            "reasks": self.reasks,
            "reasks_fixed": self.reasks_fixed,
            "n_calls": self.n_calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_s_per_doc": self.latency_s_per_doc,
            "missing_sections": self.missing_sections,
            "violations_by_code": self.violations_by_code,
            "per_doc": [d.to_dict() for d in self.per_doc],
        }


ProgressFn = Callable[[str, ExtractionResult], None]


def run_extractor(
    extractor: Extractor, docs: Sequence[Document], *, progress: ProgressFn | None = None
) -> list[ExtractionResult]:
    results: list[ExtractionResult] = []
    for doc in docs:
        result = extractor.extract(doc)
        results.append(result)
        if progress is not None:
            progress(doc.source, result)
    return results


def summarise(
    strategy: str,
    results: Sequence[ExtractionResult],
    golds: Sequence[SoAExtraction],
    *,
    seed: int = 0,
    n_boot: int = 1000,
) -> StrategyEvaluation:
    if len(results) != len(golds):
        msg = "one gold record per result is required"
        raise ValueError(msg)
    comparisons: list[ExtractionComparison] = [
        compare_extraction(r.extraction, g) for r, g in zip(results, golds, strict=True)
    ]
    per_doc = [
        DocOutcome(
            doc_id=r.doc_id,
            correct=c.doc_correct,
            field_accuracy=c.field_accuracy,
            fields=c.fields,
            rec_f1=c.recommendations.f1,
            repl_f1=c.replacements.f1,
            hard_violations=len(r.hard_violations),
            repairs=r.repairs,
            latency_s=r.latency_s,
        )
        for r, c in zip(results, comparisons, strict=True)
    ]

    def boot(values: Sequence[float], k: int) -> Interval:
        return bootstrap_mean(values, n_boot=n_boot, seed=seed + k)

    per_field = {
        f: boot([float(c.fields[f]) for c in comparisons], i) for i, f in enumerate(ALL_FIELDS)
    }
    missing: Counter[str] = Counter()
    codes: Counter[str] = Counter()
    for r in results:
        missing.update(r.missing.keys())
        codes.update(v.code for v in r.violations)
    return StrategyEvaluation(
        strategy=strategy,
        n_docs=len(results),
        doc_accuracy=boot([float(c.doc_correct) for c in comparisons], 101),
        field_accuracy=boot([c.field_accuracy for c in comparisons], 102),
        per_field=per_field,
        recommendations={
            "precision": boot([c.recommendations.precision for c in comparisons], 103),
            "recall": boot([c.recommendations.recall for c in comparisons], 104),
            "f1": boot([c.recommendations.f1 for c in comparisons], 105),
        },
        replacements={
            "precision": boot([c.replacements.precision for c in comparisons], 106),
            "recall": boot([c.replacements.recall for c in comparisons], 107),
            "f1": boot([c.replacements.f1 for c in comparisons], 108),
        },
        repairs=sum(r.repairs for r in results),
        parse_failures=sum(r.parse_failures for r in results),
        retries=sum(r.retries for r in results),
        reasks=sum(r.reasks for r in results),
        reasks_fixed=sum(r.reasks_fixed for r in results),
        n_calls=sum(r.n_calls for r in results),
        prompt_tokens=sum(r.prompt_tokens for r in results),
        completion_tokens=sum(r.completion_tokens for r in results),
        latency_s_per_doc=float(np.mean([r.latency_s for r in results])) if results else 0.0,
        missing_sections=dict(sorted(missing.items())),
        violations_by_code=dict(sorted(codes.items())),
        per_doc=per_doc,
    )


@dataclass(slots=True)
class StrategyComparison:
    a: str
    b: str
    doc_correct: PairedComparison
    field_accuracy: PairedComparison

    def to_dict(self) -> dict[str, Any]:
        return {
            "a": self.a,
            "b": self.b,
            "doc_correct": self.doc_correct.to_dict(),
            "field_accuracy": self.field_accuracy.to_dict(),
        }


def compare_strategies(
    evaluations: Sequence[StrategyEvaluation], *, seed: int = 0, n_boot: int = 1000
) -> list[StrategyComparison]:
    out: list[StrategyComparison] = []
    for i, a in enumerate(evaluations):
        for b in evaluations[i + 1 :]:
            ids = [d.doc_id for d in a.per_doc]
            b_by_id = {d.doc_id: d for d in b.per_doc}
            pairs = [(d, b_by_id[d.doc_id]) for d in a.per_doc if d.doc_id in b_by_id]
            if not pairs or len(pairs) != len(ids):
                continue
            out.append(
                StrategyComparison(
                    a.strategy,
                    b.strategy,
                    paired_bootstrap(
                        [float(x.correct) for x, _ in pairs],
                        [float(y.correct) for _, y in pairs],
                        n_boot=n_boot,
                        seed=seed,
                    ),
                    paired_bootstrap(
                        [x.field_accuracy for x, _ in pairs],
                        [y.field_accuracy for _, y in pairs],
                        n_boot=n_boot,
                        seed=seed,
                    ),
                )
            )
    return out
