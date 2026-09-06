"""``advicedoc {corpus,train-classifier,eval-classifier,extract,eval-extraction,train-router,
eval-router,reconcile,eval-reconcile,run,serve}``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from advicedoc.classify.evaluate import evaluate_classifier, save_classifier_report
from advicedoc.classify.model import DocumentClassifier, stratified_split, train_classifier
from advicedoc.classify.zeroshot import make_gold_responder
from advicedoc.config import Settings
from advicedoc.corpus.generator import (
    CorpusSpec,
    load_holdings,
    load_manifest,
    records_of_type,
    write_corpus,
)
from advicedoc.corpus.products import DEFAULT_MASTER
from advicedoc.eval.extraction import (
    StrategyEvaluation,
    compare_strategies,
    run_extractor,
    summarise,
)
from advicedoc.eval.report import ExtractionReport, save_extraction_report
from advicedoc.extract import Extractor
from advicedoc.extract.fake import make_extraction_responder
from advicedoc.extract.llm import LLMExtractor
from advicedoc.extract.rules import RulesExtractor
from advicedoc.extract.validated import ValidatedLLMExtractor
from advicedoc.ingest import Document, apply_noise, load_document, load_many
from advicedoc.llm import ChatModel, FakeChatModel, ModelKind, build_model
from advicedoc.logging_utils import configure_logging
from advicedoc.reconcile import (
    evaluate_reconciliation,
    reconcile,
    render_reconciliation_md,
    save_reconcile_evaluation,
)
from advicedoc.route.evaluate import evaluate_router, save_router_report
from advicedoc.route.features import FieldRecord, field_records
from advicedoc.route.model import ReviewRouter, cross_val_probabilities, train_router
from advicedoc.schema import GoldRecord, HoldingsSnapshot, SoAExtraction
from advicedoc.workflow import (
    InMemoryQueue,
    JobStore,
    PipelineDeps,
    Workflow,
    default_holdings_lookup,
)

log = logging.getLogger("advicedoc")


def _print(obj: Any) -> None:
    sys.stdout.write(json.dumps(obj, indent=2, ensure_ascii=False, default=str) + "\n")


def _say(message: str) -> None:
    sys.stderr.write(message + "\n")


# ----- shared helpers -----------------------------------------------------------------------


def _add_model_args(parser: argparse.ArgumentParser, s: Settings) -> None:
    parser.add_argument("--model", choices=["fake", "openai", "hf"], default=s.model.kind)
    parser.add_argument("--model-name", dest="model_name", default=s.model.model)
    parser.add_argument("--base-url", dest="base_url", default=s.model.base_url)
    parser.add_argument("--device", default=s.model.device)
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=s.model.max_tokens)
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="SQLite response cache for real models; identical greedy requests are served from it",
    )
    parser.add_argument(
        "--corruption",
        type=float,
        default=s.model.corruption,
        help="fake backend: probability that a section answer is corrupted",
    )


def _corpus_docs(
    corpus: Path, records: Sequence[GoldRecord], *, quiet: bool = False
) -> list[Document]:
    paths = [corpus / r.pdf_path for r in records]
    started = time.perf_counter()

    def progress(i: int, n: int) -> None:
        if not quiet and (i % 100 == 0 or i == n):
            _say(f"  ingested {i}/{n} documents ({time.perf_counter() - started:.1f}s)")

    docs = load_many(paths, cache_path=corpus / ".ingest_cache.json", progress=progress)
    for doc, r in zip(docs, records, strict=True):
        doc.source = r.doc_id
    return docs


def _soa_records(corpus: Path, limit: int | None) -> list[GoldRecord]:
    records = records_of_type(load_manifest(corpus), "soa")
    return records[:limit] if limit else records


def _gold_by_id(records: Sequence[GoldRecord]) -> dict[str, SoAExtraction]:
    return {r.doc_id: r.soa for r in records if r.soa is not None}


def _real_model(args: argparse.Namespace) -> ChatModel:
    kind: ModelKind = args.model
    model = build_model(
        kind, model_name=args.model_name, base_url=args.base_url, device=args.device
    )
    cache = getattr(args, "cache", None)
    if cache is not None:
        from advicedoc.cache import CachedChatModel

        return CachedChatModel(model, cache)
    return model


def _extraction_model(args: argparse.Namespace, gold_by_id: dict[str, SoAExtraction]) -> ChatModel:
    if args.model == "fake":
        return FakeChatModel(
            default=make_extraction_responder(
                gold_by_id, corruption=args.corruption, seed=args.seed
            )
        )
    return _real_model(args)


def _extractor(strategy: str, model: ChatModel | None, args: argparse.Namespace) -> Extractor:
    if strategy == "rules":
        return RulesExtractor(DEFAULT_MASTER)
    if model is None:
        msg = "an LLM strategy needs a model"
        raise ValueError(msg)
    if strategy == "llm":
        return LLMExtractor(model, max_tokens=args.max_tokens)
    return ValidatedLLMExtractor(model, max_tokens=args.max_tokens)


# ----- corpus -------------------------------------------------------------------------------


def cmd_corpus_generate(args: argparse.Namespace) -> int:
    spec = CorpusSpec(
        n_per_type=args.n_per_type,
        n_soa=args.n_soa,
        seed=args.seed,
        p_discrepancy=args.p_discrepancy,
    )
    started = time.perf_counter()
    count = 0

    def progress(doc_id: str) -> None:
        nonlocal count
        count += 1
        if count % 100 == 0:
            _say(f"  {count} documents ({doc_id}) {time.perf_counter() - started:.1f}s")

    records = write_corpus(spec, args.out, render=not args.no_pdf, progress=progress)
    elapsed = time.perf_counter() - started
    by_type: dict[str, int] = {}
    for r in records:
        by_type[r.doc_type] = by_type.get(r.doc_type, 0) + 1
    _print(
        {
            "out": str(args.out),
            "documents": len(records),
            "by_type": by_type,
            "elapsed_s": round(elapsed, 1),
            "pdf": not args.no_pdf,
        }
    )
    return 0


# ----- classifier ---------------------------------------------------------------------------


def _split_path(classifier_path: Path) -> Path:
    return classifier_path.with_suffix(classifier_path.suffix + ".split.json")


def cmd_train_classifier(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    records = load_manifest(corpus)
    labels = [r.doc_type for r in records]
    train_idx, test_idx = stratified_split(labels, test_frac=args.test_frac, seed=args.seed)
    docs = _corpus_docs(corpus, records)
    started = time.perf_counter()
    clf = train_classifier(
        [docs[i] for i in train_idx],
        [labels[i] for i in train_idx],
        seed=args.seed,
        calibration=args.calibration,
        abstain_threshold=args.abstain,
    )
    elapsed = time.perf_counter() - started
    out = Path(args.out)
    clf.save(out)
    _split_path(out).write_text(
        json.dumps(
            {
                "train": [records[i].doc_id for i in train_idx],
                "test": [records[i].doc_id for i in test_idx],
                "seed": args.seed,
                "test_frac": args.test_frac,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _print(
        {
            "classifier": str(out),
            "n_train": len(train_idx),
            "n_test": len(test_idx),
            "classes": clf.classes,
            "calibration": args.calibration,
            "train_s": round(elapsed, 2),
        }
    )
    return 0


def cmd_eval_classifier(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    clf = DocumentClassifier.load(args.classifier)
    split = json.loads(_split_path(Path(args.classifier)).read_text(encoding="utf-8"))
    by_id = {r.doc_id: r for r in load_manifest(corpus)}
    test_records = [by_id[i] for i in split["test"]]
    docs = _corpus_docs(corpus, test_records)
    zero_shot: ChatModel | None = None
    if args.zero_shot:
        if args.model == "fake":
            zero_shot = FakeChatModel(
                default=make_gold_responder(
                    {r.doc_id: r.doc_type for r in test_records},
                    corruption=args.corruption,
                    seed=args.seed,
                )
            )
        else:
            zero_shot = _real_model(args)
    report = evaluate_classifier(
        clf,
        docs,
        [r.doc_type for r in test_records],
        n_train=len(split["train"]),
        seed=args.seed,
        n_boot=args.n_boot,
        noise_rates=args.noise,
        zero_shot_model=zero_shot,
        gold_metadata=[r.metadata for r in test_records],
    )
    save_classifier_report(report, args.out)
    summary = {
        "accuracy": report.accuracy.to_dict(),
        "macro_f1": report.macro_f1.to_dict(),
        "ece": report.calibration.ece,
        "noise": {k: v["macro_f1"]["point"] for k, v in report.noise.items()},
        "zero_shot": report.zero_shot["accuracy"] if report.zero_shot else None,
        "out": str(args.out),
    }
    if args.gate:
        ok = report.macro_f1.point >= args.min_macro_f1
        summary["gate"] = "PASS" if ok else "FAIL"
        summary["min_macro_f1"] = args.min_macro_f1
        _print(summary)
        return 0 if ok else 1
    _print(summary)
    return 0


# ----- extraction ---------------------------------------------------------------------------


def _input_docs(path: Path) -> list[Document]:
    if path.is_dir():
        files = sorted(path.glob("*.pdf")) + sorted(path.glob("*.doc.json"))
        return [load_document(p) for p in files]
    return [load_document(path)]


def cmd_extract(args: argparse.Namespace) -> int:
    docs = _input_docs(Path(args.path))
    gold_by_id: dict[str, SoAExtraction] = {}
    if args.corpus:
        gold_by_id = _gold_by_id(load_manifest(Path(args.corpus)))
    model = None if args.strategy == "rules" else _extraction_model(args, gold_by_id)
    extractor = _extractor(args.strategy, model, args)
    results = [extractor.extract(d).to_dict() for d in docs]
    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        _say(f"wrote {args.out}")
    else:
        _print(results)
    return 0


def cmd_eval_extraction(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    records = _soa_records(corpus, args.limit)
    docs = _corpus_docs(corpus, records)
    golds = [r.soa for r in records if r.soa is not None]
    gold_by_id = _gold_by_id(records)
    evaluations: list[StrategyEvaluation] = []
    for rate in args.noise:
        inputs = [apply_noise(d, rate, seed=args.seed) for d in docs] if rate > 0 else docs
        for strategy in args.strategies:
            model = None if strategy == "rules" else _extraction_model(args, gold_by_id)
            extractor = _extractor(strategy, model, args)
            name = strategy if rate == 0 else f"{strategy}@noise{rate:g}"
            started = time.perf_counter()
            results = run_extractor(extractor, inputs)
            _say(f"  {name}: {len(results)} documents in {time.perf_counter() - started:.1f}s")
            evaluations.append(summarise(name, results, golds, seed=args.seed, n_boot=args.n_boot))
    report = ExtractionReport(
        title=args.title,
        strategies=evaluations,
        comparisons=compare_strategies(evaluations, seed=args.seed, n_boot=args.n_boot),
        settings={
            "corpus": str(corpus),
            "n_docs": len(docs),
            "model": args.model if any(s != "rules" for s in args.strategies) else "-",
            "model_name": args.model_name if args.model != "fake" else "-",
            "corruption": args.corruption if args.model == "fake" else "-",
            "noise": list(args.noise),
            "seed": args.seed,
        },
        notes=list(args.note or []),
    )
    md, _ = save_extraction_report(report, args.out, stem=args.stem)
    summary: dict[str, Any] = {
        "report": str(md),
        "doc_accuracy": {e.strategy: e.doc_accuracy.to_dict() for e in evaluations},
    }
    if args.gate:
        target = next((e for e in evaluations if e.strategy == args.gate_strategy), None)
        ok = target is not None and target.doc_accuracy.point >= args.min_doc_accuracy
        summary["gate"] = "PASS" if ok else "FAIL"
        summary["gate_strategy"] = args.gate_strategy
        summary["min_doc_accuracy"] = args.min_doc_accuracy
        _print(summary)
        return 0 if ok else 1
    _print(summary)
    return 0


# ----- router -------------------------------------------------------------------------------


def _router_records(args: argparse.Namespace) -> tuple[list[FieldRecord], int]:
    corpus = Path(args.corpus)
    records = _soa_records(corpus, args.limit)
    docs = _corpus_docs(corpus, records)
    if args.noise > 0:
        docs = [apply_noise(d, args.noise, seed=args.seed) for d in docs]
    gold_by_id = _gold_by_id(records)
    model = None if args.strategy == "rules" else _extraction_model(args, gold_by_id)
    primary = _extractor(args.strategy, model, args)
    rules = RulesExtractor(DEFAULT_MASTER)
    out: list[FieldRecord] = []
    for doc, rec in zip(docs, records, strict=True):
        p = primary.extract(doc)
        r = rules.extract(doc) if args.strategy != "rules" else None
        out.extend(field_records(p, r, rec.soa))
    return out, len(docs)


def _records_json(records: Sequence[FieldRecord]) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": r.doc_id,
            "key": r.key,
            "kind": r.kind,
            "features": r.features,
            "correct": r.correct,
        }
        for r in records
    ]


def cmd_train_router(args: argparse.Namespace) -> int:
    records, n_docs = _router_records(args)
    router = train_router(records, seed=args.seed, tau=args.tau)
    router.save(args.out)
    if args.records_out:
        Path(args.records_out).write_text(
            json.dumps(_records_json(records), indent=1), encoding="utf-8"
        )
    _print(
        {
            "router": str(args.out),
            "n_docs": n_docs,
            "n_fields": len(records),
            "positive_rate": sum(1 for r in records if r.correct) / max(1, len(records)),
            "tau": args.tau,
        }
    )
    return 0


def cmd_eval_router(args: argparse.Namespace) -> int:
    records, n_docs = _router_records(args)
    probs = cross_val_probabilities(records, seed=args.seed, cv=args.cv)
    full = train_router(records, seed=args.seed, cv=args.cv)
    report = evaluate_router(
        records,
        probs,
        target_residual=args.target_residual,
        seed=args.seed,
        n_boot=args.n_boot,
        coefficients=full.coefficients(),
    )
    report.notes = list(args.note or [])
    save_router_report(report, args.out)
    _print(
        {
            "n_docs": n_docs,
            "n_fields": report.n_fields,
            "ece": report.calibration.ece,
            "aurc": report.aurc.to_dict(),
            "tau": report.chosen.tau,
            "review_rate": report.chosen.review_rate.to_dict(),
            "residual_error": report.chosen.residual_error.to_dict(),
            "base_doc_error": report.base_doc_error,
            "out": str(args.out),
        }
    )
    return 0


# ----- reconciliation -----------------------------------------------------------------------


def cmd_reconcile(args: argparse.Namespace) -> int:
    if args.corpus and args.doc_id:
        corpus = Path(args.corpus)
        record = next((r for r in load_manifest(corpus) if r.doc_id == args.doc_id), None)
        if record is None or record.soa is None:
            _say(f"unknown SoA {args.doc_id}")
            return 2
        holdings = load_holdings(corpus, record)
        if holdings is None:
            _say("no holdings snapshot")
            return 2
        extraction = record.soa
        if args.source == "rules":
            extraction = (
                RulesExtractor().extract(load_document(corpus / record.pdf_path)).extraction
            )
    elif args.extraction and args.holdings:
        payload = json.loads(Path(args.extraction).read_text(encoding="utf-8"))
        if isinstance(payload, list):
            payload = payload[0]
        extraction = SoAExtraction.model_validate(payload.get("extraction", payload))
        holdings = HoldingsSnapshot.model_validate_json(
            Path(args.holdings).read_text(encoding="utf-8")
        )
    else:
        _say("give --corpus and --doc-id, or --extraction and --holdings")
        return 2
    report = reconcile(
        extraction, holdings, amount_tolerance=args.tolerance, fee_tolerance=args.fee_tolerance
    )
    text = render_reconciliation_md(report)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        _say(f"wrote {args.out}")
    else:
        sys.stdout.write(text)
    return 0


def cmd_eval_reconcile(args: argparse.Namespace) -> int:
    corpus = Path(args.corpus)
    records = _soa_records(corpus, args.limit)
    holdings = [load_holdings(corpus, r) for r in records]
    evaluations = []
    for source in args.sources:
        if source == "gold":
            extractions = [r.soa for r in records]
        else:
            docs = _corpus_docs(corpus, records)
            rules = RulesExtractor()
            extractions = [rules.extract(d).extraction for d in docs]
        cases = [
            (e, h)
            for e, h in zip(extractions, holdings, strict=True)
            if e is not None and h is not None
        ]
        for tol in args.tolerance:
            evaluations.append(
                evaluate_reconciliation(
                    cases,
                    amount_tolerance=tol,
                    fee_tolerance=args.fee_tolerance,
                    seed=args.seed,
                    n_boot=args.n_boot,
                    source=source,
                )
            )
    save_reconcile_evaluation(evaluations, args.out)
    _print(
        {
            "out": str(args.out),
            "runs": [
                {
                    "source": e.source,
                    "tolerance": e.amount_tolerance,
                    "overall_detection": e.overall_detection.to_dict(),
                    "clean_docs_flagged": e.clean_docs_flagged.to_dict(),
                }
                for e in evaluations
            ],
        }
    )
    return 0


# ----- workflow -----------------------------------------------------------------------------


def _build_workflow(args: argparse.Namespace) -> Workflow:
    gold_by_id: dict[str, SoAExtraction] = {}
    if args.corpus:
        gold_by_id = _gold_by_id(load_manifest(Path(args.corpus)))
    model = None if args.strategy == "rules" else _extraction_model(args, gold_by_id)
    extractor = _extractor(args.strategy, model, args)
    router = ReviewRouter.load(args.router) if args.router else None
    deps = PipelineDeps(
        classifier=DocumentClassifier.load(args.classifier),
        extractor=extractor,
        router=router,
        rules_extractor=RulesExtractor(DEFAULT_MASTER) if router is not None else None,
        tau=args.tau,
        holdings_lookup=default_holdings_lookup,
    )
    store = JobStore(args.db or ":memory:")
    return Workflow(store, InMemoryQueue(), deps, max_retries=args.max_retries)


def cmd_run(args: argparse.Namespace) -> int:
    workflow = _build_workflow(args)
    started = time.perf_counter()
    jobs = workflow.run_inbox(args.inbox)
    summary = workflow.summary()
    summary["elapsed_s"] = round(time.perf_counter() - started, 2)
    summary["jobs_detail"] = [
        {
            "id": j.id,
            "source": Path(j.source_path).name,
            "doc_type": j.doc_type,
            "state": j.state,
            "route": j.route,
            "error": j.error,
        }
        for j in jobs
    ]
    _print(summary)
    return 0 if all(j.state != "failed" for j in jobs) else 1


def cmd_serve(args: argparse.Namespace) -> int:  # pragma: no cover - needs a server
    import uvicorn

    from advicedoc.api import create_app

    app = create_app(_build_workflow(args), inbox_dir=args.inbox)
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    return 0


# ----- parser -------------------------------------------------------------------------------


def build_parser(settings: Settings | None = None) -> argparse.ArgumentParser:
    """Every default below can be overridden with an ``ADVICEDOC_*`` environment variable
    (see ``config.Settings``); command-line flags override both."""
    s = settings or Settings()
    parser = argparse.ArgumentParser(prog="advicedoc", description=__doc__)
    parser.add_argument("--log-level", dest="log_level", default=s.log_level)
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("corpus", help="synthetic corpus").add_subparsers(
        dest="corpus_command", required=True
    )
    gen = corpus.add_parser("generate", help="write PDFs, gold JSON, holdings and a manifest")
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument("--n-per-type", dest="n_per_type", type=int, default=60)
    gen.add_argument("--n-soa", dest="n_soa", type=int, default=120)
    gen.add_argument("--seed", type=int, default=7)
    gen.add_argument("--p-discrepancy", dest="p_discrepancy", type=float, default=0.35)
    gen.add_argument(
        "--no-pdf", dest="no_pdf", action="store_true", help="write JSON documents instead of PDFs"
    )
    gen.set_defaults(func=cmd_corpus_generate)

    strategies = ["rules", "llm", "llm_validated"]

    tc = sub.add_parser("train-classifier")
    tc.add_argument("--corpus", type=Path, default=s.corpus_dir)
    tc.add_argument("--out", type=Path, default=s.classifier_path)
    tc.add_argument("--test-frac", dest="test_frac", type=float, default=0.25)
    tc.add_argument("--seed", type=int, default=s.seed)
    tc.add_argument("--calibration", choices=["sigmoid", "isotonic"], default="sigmoid")
    tc.add_argument("--abstain", type=float, default=s.abstain_threshold)
    tc.set_defaults(func=cmd_train_classifier)

    ec = sub.add_parser("eval-classifier")
    ec.add_argument("--corpus", type=Path, default=s.corpus_dir)
    ec.add_argument("--classifier", type=Path, default=s.classifier_path)
    ec.add_argument("--out", type=Path, default=Path("runs/classifier_eval"))
    ec.add_argument("--seed", type=int, default=s.seed)
    ec.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
    ec.add_argument("--noise", type=float, nargs="*", default=[0.05, 0.10])
    ec.add_argument("--zero-shot", dest="zero_shot", action="store_true")
    _add_model_args(ec, s)
    ec.add_argument("--gate", action="store_true")
    ec.add_argument("--min-macro-f1", dest="min_macro_f1", type=float, default=0.95)
    ec.set_defaults(func=cmd_eval_classifier)

    ex = sub.add_parser("extract", help="extract one file or a directory")
    ex.add_argument("path", type=Path)
    ex.add_argument("--strategy", choices=strategies, default=s.strategy)
    ex.add_argument("--corpus", type=Path, default=None, help="corpus with gold (fake backend)")
    ex.add_argument("--out", type=Path, default=None)
    ex.add_argument("--seed", type=int, default=s.seed)
    _add_model_args(ex, s)
    ex.set_defaults(func=cmd_extract)

    ee = sub.add_parser("eval-extraction")
    ee.add_argument("--corpus", type=Path, default=s.corpus_dir)
    ee.add_argument("--strategies", nargs="+", default=strategies)
    ee.add_argument("--out", type=Path, default=Path("runs/extraction"))
    ee.add_argument("--stem", default="extraction_report")
    ee.add_argument("--title", default="SoA extraction evaluation")
    ee.add_argument("--limit", type=int, default=None)
    ee.add_argument("--noise", type=float, nargs="*", default=[0.0])
    ee.add_argument("--seed", type=int, default=s.seed)
    ee.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
    ee.add_argument("--note", action="append")
    _add_model_args(ee, s)
    ee.add_argument("--gate", action="store_true")
    ee.add_argument("--gate-strategy", dest="gate_strategy", default="rules")
    ee.add_argument("--min-doc-accuracy", dest="min_doc_accuracy", type=float, default=0.9)
    ee.set_defaults(func=cmd_eval_extraction)

    for name, func in (("train-router", cmd_train_router), ("eval-router", cmd_eval_router)):
        p = sub.add_parser(name)
        p.add_argument("--corpus", type=Path, default=s.corpus_dir)
        p.add_argument("--strategy", choices=strategies, default="llm_validated")
        p.add_argument("--limit", type=int, default=None)
        p.add_argument("--noise", type=float, default=0.0)
        p.add_argument("--seed", type=int, default=s.seed)
        p.add_argument("--tau", type=float, default=s.tau)
        p.add_argument("--cv", type=int, default=5)
        p.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
        p.add_argument("--note", action="append")
        _add_model_args(p, s)
        if name == "train-router":
            p.add_argument("--out", type=Path, default=s.router_path or Path("runs/router.joblib"))
            p.add_argument("--records-out", dest="records_out", type=Path, default=None)
        else:
            p.add_argument("--out", type=Path, default=Path("runs/router_eval"))
            p.add_argument("--target-residual", dest="target_residual", type=float, default=0.01)
        p.set_defaults(func=func)

    rc = sub.add_parser("reconcile")
    rc.add_argument("--corpus", type=Path, default=None)
    rc.add_argument("--doc-id", dest="doc_id", default=None)
    rc.add_argument("--source", choices=["gold", "rules"], default="gold")
    rc.add_argument("--extraction", type=Path, default=None)
    rc.add_argument("--holdings", type=Path, default=None)
    rc.add_argument("--tolerance", type=float, default=0.05)
    rc.add_argument("--fee-tolerance", dest="fee_tolerance", type=float, default=0.05)
    rc.add_argument("--out", type=Path, default=None)
    rc.set_defaults(func=cmd_reconcile)

    er = sub.add_parser("eval-reconcile")
    er.add_argument("--corpus", type=Path, default=s.corpus_dir)
    er.add_argument("--out", type=Path, default=Path("runs/reconcile"))
    er.add_argument("--sources", nargs="+", choices=["gold", "rules"], default=["gold"])
    er.add_argument("--tolerance", type=float, nargs="+", default=[0.05, 0.10])
    er.add_argument("--fee-tolerance", dest="fee_tolerance", type=float, default=0.05)
    er.add_argument("--limit", type=int, default=None)
    er.add_argument("--seed", type=int, default=s.seed)
    er.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
    er.set_defaults(func=cmd_eval_reconcile)

    for name, func in (("run", cmd_run), ("serve", cmd_serve)):
        p = sub.add_parser(name)
        p.add_argument("--inbox", type=Path, default=s.inbox_dir)
        p.add_argument("--classifier", type=Path, default=s.classifier_path)
        p.add_argument("--router", type=Path, default=s.router_path)
        p.add_argument("--tau", type=float, default=s.tau)
        p.add_argument("--strategy", choices=strategies, default=s.strategy)
        p.add_argument("--corpus", type=Path, default=None, help="corpus with gold (fake backend)")
        p.add_argument("--db", type=Path, default=s.db_path)
        p.add_argument("--max-retries", dest="max_retries", type=int, default=s.max_retries)
        p.add_argument("--seed", type=int, default=s.seed)
        _add_model_args(p, s)
        if name == "serve":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8080)
        p.set_defaults(func=func)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    result: int = args.func(args)
    return result
