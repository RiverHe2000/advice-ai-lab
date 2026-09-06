from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from filenote.cli import main
from filenote.corpus import Meeting, save_corpus
from filenote.transcribe import TranscribedSegment


def test_corpus_generate_and_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "c" / "meetings.jsonl"
    stats = tmp_path / "c" / "stats.md"
    assert (
        main(
            [
                "corpus",
                "generate",
                "--n",
                "3",
                "--seed",
                "5",
                "--out",
                str(out),
                "--stats",
                str(stats),
            ]
        )
        == 0
    )
    assert out.exists() and stats.exists() and stats.with_suffix(".json").exists()
    assert "wrote 3 meetings" in capsys.readouterr().out
    assert main(["corpus", "show", "--corpus", str(out), "--id", "m0002"]) == 0
    text = capsys.readouterr().out
    assert "# meeting: m0002" in text and "# File note" in text
    assert main(["corpus", "show", "--corpus", str(out)]) == 0
    assert main(["corpus", "show", "--corpus", str(out), "--id", "zzz"]) == 1


def test_draft_verify_and_audit(
    tmp_path: Path, corpus: list[Meeting], capsys: pytest.CaptureFixture[str]
) -> None:
    m = corpus[0]
    transcript = tmp_path / "t.txt"
    transcript.write_text(m.transcript.to_text(), encoding="utf-8")
    note_path = tmp_path / "note.json"
    code = main(
        [
            "draft",
            str(transcript),
            "--model",
            "fake",
            "--n",
            "3",
            "--strategy",
            "verified",
            "--out",
            str(note_path),
            "--pseudonymise",
            "on",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pseudonymised"] is True and payload["verification"]["unsupported"] == 0
    assert note_path.exists()
    assert (
        main(
            [
                "draft",
                str(transcript),
                "--model",
                "fake",
                "--n",
                "3",
                "--strategy",
                "single_shot",
                "--markdown",
                "--pseudonymise",
                "off",
            ]
        )
        == 0
    )
    assert "## Decisions" in capsys.readouterr().out
    assert main(["verify", str(transcript), str(note_path)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["verdicts"]
    bad = {
        "note": {
            **payload["note"],
            "decisions": [
                {"text": "Client agreed to buy a boat for $9,999,999", "evidence": ["s001"]}
            ],
        }
    }
    (tmp_path / "bad.json").write_text(json.dumps(bad), encoding="utf-8")
    assert main(["verify", str(transcript), str(tmp_path / "bad.json")]) == 1
    capsys.readouterr()

    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        json.dumps(
            {"ts": "t", "kind": "feedback", "draft_id": "d1", "comment": "ring 0412 345 678"}
        )
        + "\n",
        encoding="utf-8",
    )
    assert main(["audit", "export", "--audit-path", str(audit)]) == 0
    assert "[PHONE]" in capsys.readouterr().out
    exported = tmp_path / "exp.jsonl"
    assert (
        main(
            ["audit", "export", "--audit-path", str(audit), "--out", str(exported), "--draft", "d1"]
        )
        == 0
    )
    assert "exported 1 entries" in capsys.readouterr().out


def test_draft_failure_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, meeting: Meeting
) -> None:
    from filenote import cli
    from filenote.llm import ScriptedChatModel

    monkeypatch.setattr(cli, "settings_from_args", lambda a: cli.Settings())  # type: ignore[attr-defined]
    monkeypatch.setattr("filenote.llm.build_model", lambda s: ScriptedChatModel(default="nope"))
    transcript = tmp_path / "t.txt"
    transcript.write_text(meeting.transcript.to_text(), encoding="utf-8")
    assert main(["draft", str(transcript), "--strategy", "single_shot"]) == 1


def test_eval_and_gate(
    tmp_path: Path, corpus: list[Meeting], capsys: pytest.CaptureFixture[str]
) -> None:
    corpus_path = save_corpus(corpus[:5], tmp_path / "meetings.jsonl")
    out = tmp_path / "eval"
    code = main(
        [
            "--log-level",
            "WARNING",
            "eval",
            "--model",
            "fake",
            "--corruption",
            "0.0",
            "--corpus",
            str(corpus_path),
            "--n",
            "4",
            "--strategies",
            "single_shot",
            "verified",
            "--pseudonymise",
            "both",
            "--out",
            str(out),
            "--n-boot",
            "20",
            "--gate",
        ]
    )
    assert code == 0
    text = capsys.readouterr().out
    assert "GATE PASSED" in text and "verified+pseud" in text
    report = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert len(report["runs"]) == 4 and report["corpus"]["meetings"] == 4
    assert report["comparisons"]
    code = main(
        [
            "--log-level",
            "WARNING",
            "eval",
            "--model",
            "fake",
            "--corruption",
            "0.5",
            "--corpus",
            str(corpus_path),
            "--n",
            "4",
            "--strategies",
            "single_shot",
            "--out",
            str(out / "bad"),
            "--n-boot",
            "20",
            "--gate",
            "--min-f1",
            "0.99",
            "--compare-with",
            str(out / "report.json"),
        ]
    )
    assert code == 1
    text = capsys.readouterr().out
    assert "GATE FAILED" in text and "single_shot@" in text
    assert (
        main(
            [
                "--log-level",
                "WARNING",
                "eval",
                "--model",
                "fake",
                "--n",
                "2",
                "--out",
                str(out / "plain"),
                "--n-boot",
                "10",
            ]
        )
        == 0
    )
    capsys.readouterr()


def test_eval_verifier_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "sv"
    assert (
        main(
            [
                "eval-verifier",
                "--n",
                "4",
                "--out",
                str(out),
                "--n-boot",
                "20",
                "--gate",
                "--min-detection",
                "0.5",
                "--max-false-alarm",
                "0.1",
            ]
        )
        == 0
    )
    assert "GATE PASSED" in capsys.readouterr().out
    assert (
        main(
            [
                "eval-verifier",
                "--n",
                "4",
                "--out",
                str(out),
                "--n-boot",
                "20",
                "--gate",
                "--min-detection",
                "1.01",
            ]
        )
        == 1
    )
    assert "GATE FAILED" in capsys.readouterr().out
    assert main(["eval-verifier", "--n", "3", "--out", str(out), "--n-boot", "10"]) == 0
    assert "verifier_selfeval.md" in capsys.readouterr().out


def test_transcribe_with_fake_transcriber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from filenote import transcribe

    class Fake(transcribe.FakeTranscriber):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(
                [
                    TranscribedSegment(0.0, 2.0, "Welcome back"),
                    TranscribedSegment(2.5, 4.0, "Thanks"),
                ]
            )

    monkeypatch.setattr(transcribe, "FasterWhisperTranscriber", Fake)
    audio = tmp_path / "meeting.wav"
    audio.write_bytes(b"RIFF")
    out = tmp_path / "meeting.txt"
    assert main(["transcribe", str(audio), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    assert (
        "# meeting: meeting" in text and "s001 [00:00:00] unknown (unknown): Welcome back" in text
    )
    assert out.read_text(encoding="utf-8") == text


def test_serve_invokes_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    seen: dict[str, Any] = {}

    def fake_run(app: Any, **kwargs: Any) -> None:
        seen["app"] = app
        seen.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    assert (
        main(["serve", "--model", "fake", "--n", "2", "--port", "9999", "--host", "127.0.0.2"]) == 0
    )
    assert seen["port"] == 9999 and seen["host"] == "127.0.0.2"
    assert seen["app"].title == "file-note-copilot"


def test_utf8_output_does_not_crash(capsys: pytest.CaptureFixture[str]) -> None:
    from filenote.cli import _utf8_stdout

    _utf8_stdout()
    print("→ non-ascii ✓")
    assert "non-ascii" in capsys.readouterr().out
