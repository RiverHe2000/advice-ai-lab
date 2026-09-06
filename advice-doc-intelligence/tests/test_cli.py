from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from advicedoc.cli import _extractor, build_parser, main


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, Any]:
    code = main(list(argv))
    out = capsys.readouterr().out
    payload: Any = json.loads(out) if out.strip().startswith(("{", "[")) else {}
    return code, payload


@pytest.fixture(scope="module")
def trained(tmp_path_factory: pytest.TempPathFactory, json_corpus: Path) -> Path:
    runs = tmp_path_factory.mktemp("runs")
    code = main(
        [
            "train-classifier",
            "--corpus",
            str(json_corpus),
            "--out",
            str(runs / "clf.joblib"),
            "--test-frac",
            "0.25",
        ]
    )
    assert code == 0
    return runs


def test_corpus_generate_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(
        capsys,
        "corpus",
        "generate",
        "--out",
        str(tmp_path / "c"),
        "--n-per-type",
        "1",
        "--n-soa",
        "2",
        "--seed",
        "1",
        "--no-pdf",
    )
    assert code == 0 and payload["documents"] == 11 and payload["by_type"]["soa"] == 2
    assert (tmp_path / "c" / "manifest.jsonl").exists()


def test_eval_classifier_gate(
    trained: Path, json_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _run(
        capsys,
        "eval-classifier",
        "--corpus",
        str(json_corpus),
        "--classifier",
        str(trained / "clf.joblib"),
        "--out",
        str(trained / "ce"),
        "--zero-shot",
        "--corruption",
        "0.2",
        "--n-boot",
        "20",
        "--noise",
        "0.05",
        "--gate",
        "--min-macro-f1",
        "0.9",
    )
    assert code == 0 and payload["gate"] == "PASS" and payload["zero_shot"] is not None
    assert (trained / "ce" / "classifier_report.md").exists()
    code, payload = _run(
        capsys,
        "eval-classifier",
        "--corpus",
        str(json_corpus),
        "--classifier",
        str(trained / "clf.joblib"),
        "--out",
        str(trained / "ce2"),
        "--n-boot",
        "10",
        "--noise",
        "--gate",
        "--min-macro-f1",
        "1.5",
    )
    assert code == 1 and payload["gate"] == "FAIL"


def test_eval_extraction_gate_and_noise(
    trained: Path, json_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _run(
        capsys,
        "eval-extraction",
        "--corpus",
        str(json_corpus),
        "--strategies",
        "rules",
        "llm_validated",
        "--corruption",
        "0.3",
        "--limit",
        "6",
        "--noise",
        "0.0",
        "0.05",
        "--n-boot",
        "20",
        "--out",
        str(trained / "ex"),
        "--note",
        "mechanism check",
        "--gate",
        "--min-doc-accuracy",
        "0.9",
    )
    assert code == 0 and payload["gate"] == "PASS"
    assert set(payload["doc_accuracy"]) == {
        "rules",
        "llm_validated",
        "rules@noise0.05",
        "llm_validated@noise0.05",
    }
    code, payload = _run(
        capsys,
        "eval-extraction",
        "--corpus",
        str(json_corpus),
        "--strategies",
        "llm",
        "--corruption",
        "0.5",
        "--limit",
        "4",
        "--n-boot",
        "5",
        "--out",
        str(trained / "ex2"),
        "--gate",
        "--gate-strategy",
        "llm",
        "--min-doc-accuracy",
        "1.0",
    )
    assert code == 1 and payload["gate"] == "FAIL"


def test_router_train_and_eval(
    trained: Path, json_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _run(
        capsys,
        "train-router",
        "--corpus",
        str(json_corpus),
        "--strategy",
        "llm_validated",
        "--corruption",
        "0.4",
        "--out",
        str(trained / "router.joblib"),
        "--records-out",
        str(trained / "records.json"),
        "--limit",
        "8",
    )
    assert code == 0 and payload["n_fields"] > 0 and (trained / "records.json").exists()
    code, payload = _run(
        capsys,
        "eval-router",
        "--corpus",
        str(json_corpus),
        "--strategy",
        "llm",
        "--corruption",
        "0.4",
        "--out",
        str(trained / "re"),
        "--limit",
        "8",
        "--n-boot",
        "10",
        "--cv",
        "3",
        "--note",
        "x",
    )
    assert code == 0 and 0 <= payload["ece"] <= 1 and (trained / "re" / "router_report.md").exists()
    code, payload = _run(
        capsys,
        "train-router",
        "--corpus",
        str(json_corpus),
        "--strategy",
        "rules",
        "--out",
        str(trained / "router_rules.joblib"),
        "--limit",
        "4",
        "--noise",
        "0.05",
    )
    assert code == 0


def test_reconcile_commands(
    trained: Path, json_corpus: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, payload = _run(
        capsys,
        "eval-reconcile",
        "--corpus",
        str(json_corpus),
        "--out",
        str(trained / "rc"),
        "--sources",
        "gold",
        "rules",
        "--tolerance",
        "0.05",
        "--limit",
        "6",
        "--n-boot",
        "10",
    )
    assert code == 0 and len(payload["runs"]) == 2
    code = main(["reconcile", "--corpus", str(json_corpus), "--doc-id", "soa_0001"])
    assert code == 0 and "Implementation reconciliation" in capsys.readouterr().out
    assert (
        main(
            [
                "reconcile",
                "--corpus",
                str(json_corpus),
                "--doc-id",
                "soa_0001",
                "--source",
                "rules",
                "--out",
                str(trained / "one.md"),
            ]
        )
        == 0
    )
    assert main(["reconcile", "--corpus", str(json_corpus), "--doc-id", "fds_0001"]) == 2
    assert main(["reconcile"]) == 2
    extraction = trained / "soa_0001.json"
    assert (
        main(["extract", str(json_corpus / "soa" / "soa_0001.doc.json"), "--out", str(extraction)])
        == 0
    )
    holdings = json_corpus / "soa" / "soa_0001.holdings.json"
    assert main(["reconcile", "--extraction", str(extraction), "--holdings", str(holdings)]) == 0
    assert "Document `soa_0001`" in capsys.readouterr().out


def test_extract_dir_with_fake_llm(json_corpus: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _run(
        capsys,
        "extract",
        str(json_corpus / "soa"),
        "--strategy",
        "llm",
        "--corpus",
        str(json_corpus),
        "--corruption",
        "0.2",
    )
    assert code == 0 and len(payload) == 12 and payload[0]["strategy"] == "llm"
    args = build_parser().parse_args(["extract", "x"])
    with pytest.raises(ValueError, match="needs a model"):
        _extractor("llm", None, args)


def test_run_inbox(
    trained: Path, json_corpus: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    for name in ("soa/soa_0001.doc.json", "soa/soa_0001.holdings.json", "fds/fds_0001.doc.json"):
        shutil.copy(json_corpus / name, inbox / Path(name).name)
    code, payload = _run(
        capsys,
        "run",
        "--inbox",
        str(inbox),
        "--classifier",
        str(trained / "clf.joblib"),
        "--router",
        str(trained / "router.joblib"),
        "--strategy",
        "llm_validated",
        "--corpus",
        str(json_corpus),
        "--corruption",
        "0.2",
        "--db",
        str(tmp_path / "jobs.sqlite"),
    )
    assert (
        code == 0
        and payload["jobs"] == 2
        and payload["by_state"].get("done", 0) + payload["by_state"].get("routed", 0) == 2
    )


def test_environment_overrides_parser_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADVICEDOC_MODEL__KIND", "openai")
    monkeypatch.setenv("ADVICEDOC_MODEL__BASE_URL", "http://vllm:8000/v1")
    monkeypatch.setenv("ADVICEDOC_STRATEGY", "llm_validated")
    monkeypatch.setenv("ADVICEDOC_TAU", "0.8")
    args = build_parser().parse_args(["run"])
    assert args.model == "openai" and args.base_url == "http://vllm:8000/v1"
    assert args.strategy == "llm_validated" and args.tau == 0.8
    assert build_parser().parse_args(["run", "--tau", "0.3"]).tau == 0.3


def test_console_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "advicedoc", "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0 and "eval-extraction" in result.stdout
