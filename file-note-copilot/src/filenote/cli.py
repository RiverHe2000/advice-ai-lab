"""``filenote {corpus,draft,verify,eval,eval-verifier,transcribe,serve,audit}``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from filenote.config import STRATEGIES, Settings

log = logging.getLogger("filenote")


def _utf8_stdout() -> None:
    """The Windows console may be GBK; never crash on a unicode character."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def settings_from_args(args: argparse.Namespace) -> Settings:
    overrides: dict[str, Any] = {}
    model: dict[str, Any] = {}
    for field_name, arg_name in (
        ("kind", "model"),
        ("model", "model_name"),
        ("base_url", "base_url"),
        ("max_tokens", "max_tokens"),
        ("device", "device"),
        ("cache_path", "cache"),
    ):
        value = getattr(args, arg_name, None)
        if value is not None:
            model[field_name] = value
    if model:
        overrides["model"] = model
    fake: dict[str, Any] = {}
    if getattr(args, "corruption", None) is not None:
        fake["corruption"] = args.corruption
    if getattr(args, "corpus_seed", None) is not None:
        fake["corpus_seed"] = args.corpus_seed
    if getattr(args, "corpus_n", None) is not None:
        fake["corpus_n"] = args.corpus_n
    if getattr(args, "seed", None) is not None:
        fake["seed"] = args.seed
        overrides["seed"] = args.seed
    if fake:
        overrides["fake"] = fake
    draft: dict[str, Any] = {}
    if getattr(args, "strategy", None) is not None:
        draft["strategy"] = args.strategy
    if getattr(args, "window_size", None) is not None:
        draft["window_size"] = args.window_size
    if draft:
        overrides["draft"] = draft
    for key in ("db_path", "audit_path"):
        value = getattr(args, key, None)
        if value is not None:
            overrides[key] = value
    pseud = getattr(args, "pseudonymise", None)
    if pseud in ("on", "off"):
        overrides["pseudonymise"] = pseud == "on"
    return Settings(**overrides)


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", choices=["fake", "openai", "hf"], default=None)
    parser.add_argument("--model-name", dest="model_name", default=None)
    parser.add_argument("--base-url", dest="base_url", default=None)
    parser.add_argument("--max-tokens", dest="max_tokens", type=int, default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="SQLite response cache; identical greedy requests are served from it",
    )
    parser.add_argument("--corruption", type=float, default=None, help="fake backend only")
    parser.add_argument("--seed", type=int, default=None)


def _add_corpus_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--corpus", type=Path, default=None, help="corpus JSONL (else generated)")
    parser.add_argument("--n", dest="corpus_n", type=int, default=None)
    parser.add_argument("--corpus-seed", dest="corpus_seed", type=int, default=None)


def _load_meetings(args: argparse.Namespace, settings: Settings) -> list[Any]:
    from filenote.corpus import generate_corpus, load_corpus

    if getattr(args, "corpus", None) is not None:
        meetings = load_corpus(args.corpus)
        if settings.fake.corpus_n and getattr(args, "corpus_n", None) is not None:
            meetings = meetings[: settings.fake.corpus_n]
        return meetings
    return generate_corpus(settings.fake.corpus_n, settings.fake.corpus_seed)


def _write(text: str) -> None:
    sys.stdout.write(text)
    sys.stdout.flush()


# ----- commands -----------------------------------------------------------------------------


def cmd_corpus_generate(args: argparse.Namespace) -> int:
    from filenote.corpus import corpus_stats, generate_corpus, render_stats_md, save_corpus

    meetings = generate_corpus(args.n, args.seed)
    path = save_corpus(meetings, args.out)
    stats = corpus_stats(meetings)
    md = render_stats_md(stats, seed=args.seed)
    if args.stats:
        Path(args.stats).parent.mkdir(parents=True, exist_ok=True)
        Path(args.stats).write_text(md, encoding="utf-8")
        Path(args.stats).with_suffix(".json").write_text(
            json.dumps(stats, indent=2) + "\n", encoding="utf-8"
        )
    _write(md)
    _write(f"wrote {len(meetings)} meetings to {path}\n")
    return 0


def cmd_corpus_show(args: argparse.Namespace) -> int:
    from filenote.corpus import load_corpus

    meetings = load_corpus(args.corpus)
    wanted = [m for m in meetings if m.id == args.id] if args.id else meetings[:1]
    if not wanted:
        log.error("meeting %s not found", args.id)
        return 1
    m = wanted[0]
    _write(m.transcript.to_text())
    _write("\n" + m.gold.to_markdown())
    return 0


def _read_transcript(path: Path, meeting_id: str | None) -> Any:
    from filenote.schema import Transcript

    text = Path(path).read_text(encoding="utf-8")
    return Transcript.from_text(text, meeting_id=meeting_id or Path(path).stem)


def cmd_draft(args: argparse.Namespace) -> int:
    from filenote.draft import DraftError, build_drafter
    from filenote.llm import build_model
    from filenote.pii import Pseudonymiser
    from filenote.verify import Verifier

    settings = settings_from_args(args)
    transcript = _read_transcript(args.transcript, args.meeting_id)
    model = build_model(settings)
    drafter = build_drafter(settings.draft.strategy, model, settings)
    pseud = Pseudonymiser(transcript.attendees) if settings.pseudonymise else None
    model_input = pseud.transcript(transcript) if pseud is not None else transcript
    started = time.perf_counter()
    try:
        result = drafter.draft(
            model_input, progress=lambda e: log.info("%s %s", e.stage, e.message)
        )
    except DraftError as exc:
        log.error("draft failed: %s", exc)
        return 1
    note = pseud.restore_note(result.note) if pseud is not None else result.note
    if pseud is not None:
        note.meeting.attendees = list(transcript.attendees)
    report = Verifier(settings.verifier).verify(note, transcript)
    note = Verifier(settings.verifier).apply(note, report)
    payload = {
        "note": note.model_dump(mode="json"),
        "verification": report.summary(),
        "strategy": result.strategy,
        "model": result.model,
        "model_calls": result.model_calls,
        "json_repairs": result.json_repairs,
        "parse_failures": result.parse_failures,
        "repair_dropped": result.repair_dropped,
        "latency_s": round(time.perf_counter() - started, 3),
        "pseudonymised": pseud is not None,
    }
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    if args.markdown:
        _write(note.to_markdown())
    else:
        _write(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    from filenote.schema import FileNote
    from filenote.verify import Verifier

    settings = settings_from_args(args)
    transcript = _read_transcript(args.transcript, args.meeting_id)
    raw = json.loads(Path(args.note).read_text(encoding="utf-8"))
    note = FileNote.model_validate(raw.get("note", raw))
    report = Verifier(settings.verifier).verify(note, transcript)
    _write(json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n")
    return 0 if report.counts["unsupported"] == 0 else 1


def cmd_eval(args: argparse.Namespace) -> int:
    from filenote.draft import build_drafter
    from filenote.eval.report import render_report_md
    from filenote.eval.runner import (
        EvalReport,
        GateThresholds,
        StrategyRun,
        apply_gate,
        compare_runs,
        run_strategy,
        save_report,
    )
    from filenote.llm import build_model
    from filenote.verify import Verifier

    settings = settings_from_args(args)
    meetings = _load_meetings(args, settings)
    if args.model == "fake" or settings.model.kind == "fake":
        from filenote.fake import Corruption, GoldFakeChatModel

        model: Any = GoldFakeChatModel(
            {m.id: m for m in meetings},
            corruption=Corruption(p=settings.fake.corruption, seed=settings.fake.seed),
        )
    else:
        model = build_model(settings)
    verifier = Verifier(settings.verifier)
    strategies = args.strategies or [settings.draft.strategy]
    modes = [True, False] if args.pseudonymise == "both" else [args.pseudonymise == "on"]
    runs: list[StrategyRun] = []
    for strategy in strategies:
        for pseud in modes:
            name = strategy + ("+pseud" if pseud and len(modes) > 1 else "")
            log.info("run %s (pseudonymise=%s) on %d meetings", name, pseud, len(meetings))
            run = run_strategy(
                meetings,
                build_drafter(strategy, model, settings),
                verifier,
                name=name,
                pseudonymise=pseud,
                corruption=settings.fake.corruption if settings.model.kind == "fake" else None,
                n_boot=args.n_boot,
                seed=settings.seed,
                progress=lambda n, m: log.info(
                    "%s %s macro_f1=%.3f halluc=%d", n, m.meeting_id, m.macro_f1, m.hallucinated
                ),
            )
            runs.append(run)
    report = EvalReport(
        created=dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        corpus={
            "meetings": len(meetings),
            "seed": settings.fake.corpus_seed,
            "n_boot": args.n_boot,
            "corruption": settings.fake.corruption,
            "model": runs[0].model if runs else None,
        },
        runs=runs,
    )
    for i in range(1, len(runs)):
        report.comparisons.extend(
            compare_runs(
                runs[i],
                runs[0],
                n_boot=args.n_boot,
                seed=settings.seed,
                non_inferiority_margin=args.margin,
            )
        )
    if args.compare_with and Path(args.compare_with).exists():
        other = EvalReport.model_validate_json(Path(args.compare_with).read_text(encoding="utf-8"))
        for run in runs:
            for prior in other.runs:
                if [m.meeting_id for m in prior.meetings] == [m.meeting_id for m in run.meetings]:
                    prior_copy = prior.model_copy(update={"name": f"{prior.name}@{prior.model}"})
                    report.comparisons.extend(
                        compare_runs(run, prior_copy, n_boot=args.n_boot, seed=settings.seed)
                    )
    failures: list[str] = []
    if args.gate:
        thresholds = GateThresholds(
            min_macro_f1=args.min_f1,
            min_decisions_f1=args.min_decisions_f1,
            max_hallucination_rate=args.max_hallucination,
            max_omission_rate=args.max_omission,
            min_surfaced_rate=args.min_surfaced,
        )
        target = runs[-1]
        failures = apply_gate(target, thresholds)
        report.gate = {
            "run": target.name,
            "thresholds": thresholds.model_dump(),
            "failures": failures,
            "passed": not failures,
        }
    md = render_report_md(report)
    json_path, md_path = save_report(report, args.out, md)
    _write(md)
    _write(f"wrote {json_path} and {md_path}\n")
    if args.gate:
        _write("GATE FAILED\n" if failures else "GATE PASSED\n")
        return 1 if failures else 0
    return 0


def cmd_eval_verifier(args: argparse.Namespace) -> int:
    from filenote.verify import Verifier
    from filenote.verify.selfeval import evaluate_verifier, render_selfeval_md, save_selfeval

    settings = settings_from_args(args)
    meetings = _load_meetings(args, settings)
    report = evaluate_verifier(
        meetings, Verifier(settings.verifier), seed=settings.seed, n_boot=args.n_boot
    )
    failures = (
        report.gate(min_detection=args.min_detection, max_false_alarm=args.max_false_alarm)
        if args.gate
        else None
    )
    md = render_selfeval_md(report, gate_failures=failures)
    json_path, md_path = save_selfeval(report, args.out, md)
    _write(md)
    _write(f"wrote {json_path} and {md_path}\n")
    if args.gate:
        _write("GATE FAILED\n" if failures else "GATE PASSED\n")
        return 1 if failures else 0
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    from filenote.transcribe import FasterWhisperTranscriber, to_transcript

    transcriber = FasterWhisperTranscriber(args.whisper_model, device=args.device or "auto")
    segments = transcriber.transcribe(Path(args.audio))
    transcript = to_transcript(segments, meeting_id=args.meeting_id or Path(args.audio).stem)
    text = transcript.to_text()
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    _write(text)
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from filenote.web import create_app

    settings = settings_from_args(args)
    host = args.host or settings.web.host
    # Cloud Run injects PORT; an explicit flag still wins.
    port = args.port or int(os.environ.get("PORT", settings.web.port))
    uvicorn.run(create_app(settings), host=host, port=port, log_config=None)
    return 0


def cmd_audit_export(args: argparse.Namespace) -> int:
    from filenote.audit import AuditLog
    from filenote.pii import redact_any

    audit = AuditLog(args.audit_path)
    if args.out:
        n = audit.export(args.out, draft_id=args.draft)
        _write(f"exported {n} entries to {args.out}\n")
    else:
        for e in audit.entries(args.draft):
            _write(json.dumps(redact_any(e), ensure_ascii=False) + "\n")
    return 0


# ----- parser -------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="filenote", description=__doc__)
    parser.add_argument("--log-level", default="INFO")
    sub = parser.add_subparsers(dest="command", required=True)

    corpus = sub.add_parser("corpus", help="synthetic meetings with gold notes")
    corpus_sub = corpus.add_subparsers(dest="corpus_command", required=True)
    p = corpus_sub.add_parser("generate", help="generate a corpus JSONL")
    p.add_argument("--n", type=int, default=100)
    p.add_argument("--seed", type=int, default=11)
    p.add_argument("--out", type=Path, default=Path("runs/corpus/meetings.jsonl"))
    p.add_argument("--stats", type=Path, default=None, help="write statistics markdown here")
    p.set_defaults(func=cmd_corpus_generate)
    p = corpus_sub.add_parser("show", help="print one meeting's transcript and gold note")
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--id", default=None)
    p.set_defaults(func=cmd_corpus_show)

    p = sub.add_parser("draft", help="draft a file note from a transcript file")
    p.add_argument("transcript", type=Path)
    p.add_argument("--strategy", choices=STRATEGIES, default=None)
    p.add_argument("--pseudonymise", choices=["on", "off"], default=None)
    p.add_argument("--meeting-id", dest="meeting_id", default=None)
    p.add_argument("--window-size", dest="window_size", type=int, default=None)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--markdown", action="store_true", help="print the note as markdown")
    _add_model_args(p)
    _add_corpus_args(p)
    p.set_defaults(func=cmd_draft)

    p = sub.add_parser("verify", help="verify a note JSON against a transcript")
    p.add_argument("transcript", type=Path)
    p.add_argument("note", type=Path)
    p.add_argument("--meeting-id", dest="meeting_id", default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("eval", help="evaluate strategies against gold; report.json/report.md")
    p.add_argument("--strategies", nargs="+", choices=STRATEGIES, default=None)
    p.add_argument("--pseudonymise", choices=["on", "off", "both"], default="off")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
    p.add_argument("--margin", type=float, default=0.0, help="non-inferiority margin")
    p.add_argument("--compare-with", dest="compare_with", type=Path, default=None)
    p.add_argument("--gate", action="store_true", help="exit 1 unless the last run passes")
    p.add_argument("--min-f1", dest="min_f1", type=float, default=0.9)
    p.add_argument("--min-decisions-f1", dest="min_decisions_f1", type=float, default=0.9)
    p.add_argument("--max-hallucination", dest="max_hallucination", type=float, default=0.02)
    p.add_argument("--max-omission", dest="max_omission", type=float, default=0.1)
    p.add_argument("--min-surfaced", dest="min_surfaced", type=float, default=0.9)
    _add_model_args(p)
    _add_corpus_args(p)
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("eval-verifier", help="verifier self-evaluation on planted hallucinations")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--n-boot", dest="n_boot", type=int, default=1000)
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--gate", action="store_true")
    p.add_argument("--min-detection", dest="min_detection", type=float, default=0.9)
    p.add_argument("--max-false-alarm", dest="max_false_alarm", type=float, default=0.02)
    _add_corpus_args(p)
    p.set_defaults(func=cmd_eval_verifier)

    p = sub.add_parser("transcribe", help="transcribe a wav with faster-whisper ([audio] extra)")
    p.add_argument("audio", type=Path)
    p.add_argument("--whisper-model", dest="whisper_model", default="base")
    p.add_argument("--device", default=None)
    p.add_argument("--meeting-id", dest="meeting_id", default=None)
    p.add_argument("--out", type=Path, default=None)
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("serve", help="run the web application")
    p.add_argument("--host", default=None)
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--strategy", choices=STRATEGIES, default=None)
    p.add_argument("--pseudonymise", choices=["on", "off"], default=None)
    p.add_argument("--db-path", dest="db_path", type=Path, default=None)
    p.add_argument("--audit-path", dest="audit_path", type=Path, default=None)
    _add_model_args(p)
    _add_corpus_args(p)
    p.set_defaults(func=cmd_serve)

    audit = sub.add_parser("audit", help="audit trail")
    audit_sub = audit.add_subparsers(dest="audit_command", required=True)
    p = audit_sub.add_parser("export", help="print or export the redacted audit trail")
    p.add_argument("--audit-path", dest="audit_path", type=Path, required=True)
    p.add_argument("--out", type=Path, default=None)
    p.add_argument("--draft", default=None)
    p.set_defaults(func=cmd_audit_export)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    _utf8_stdout()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    func: Any = args.func
    return int(func(args))
