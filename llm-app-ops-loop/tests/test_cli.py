"""CLI smoke: the whole loop on a temporary project (traffic -> sample -> judge -> curate ->
dataset -> regression gate -> release -> replay -> incident -> monitor -> store), plus the
error paths and the servers with uvicorn stubbed out."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from opsloop import cli
from opsloop.store import TraceStore
from tests.conftest import PROJECT

SEED = 3


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("proj")
    shutil.copytree(PROJECT / "prompts", root / "prompts")
    shutil.copytree(PROJECT / "slos", root / "slos")
    (root / "scenarios").mkdir()
    (root / "scenarios" / "tiny.yaml").write_text(
        "name: tiny\ntraffic: {rate_per_minute: 6, sessions: 20, clients: 60}\nactive_version: v1\n"
        "incidents:\n  - {kind: error_burst, start_minute: 40, end_minute: 60, params: {error_rate: 0.4}}\n",
        encoding="utf-8",
    )
    (root / "scenarios" / "canary.yaml").write_text(
        "name: canary\ntraffic: {rate_per_minute: 8, sessions: 200, clients: 60}\nactive_version: v1\ncanary: {version: v2, stage: 50}\nincidents: []\n",
        encoding="utf-8",
    )
    return root


def run(project: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, Any]:
    base = [
        "--store",
        str(project / "runs" / "traces.sqlite"),
        "--prompts-dir",
        str(project / "prompts"),
        "--releases",
        str(project / "prompts" / "releases.yaml"),
        "--slos",
        str(project / "slos" / "default.yaml"),
        "--datasets-dir",
        str(project / "datasets"),
    ]
    code = cli.main([*base, *args])
    out = capsys.readouterr().out
    try:
        return code, json.loads(out)
    except json.JSONDecodeError:
        return code, out


def test_demo_traffic_and_monitor_run(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(
        project,
        capsys,
        "demo",
        "traffic",
        "--scenario",
        str(project / "scenarios" / "tiny.yaml"),
        "--minutes",
        "60",
        "--seed",
        str(SEED),
        "--reset",
        "--summary-out",
        str(project / "runs" / "summary.json"),
    )
    assert (
        code == 0
        and out["n_requests"] > 200
        and out["n_errors"] > 0
        and (project / "runs" / "summary.json").exists()
    )
    code, out = run(
        project,
        capsys,
        "monitor",
        "run",
        "--out",
        str(project / "runs" / "monitor"),
        "--state",
        str(project / "runs" / "state.json"),
    )
    assert (
        code == 3
        and any(a["name"] == "error_rate" for a in out["alerts"])
        and (project / "runs" / "monitor" / "alerts.md").exists()
    )
    code, out = run(project, capsys, "monitor", "run", "--as-of", "2026-09-01T00:20:00Z")
    assert code == 0 and out["ticks"] == 1
    code, out = run(
        project, capsys, "--store", str(project / "runs" / "empty.sqlite"), "monitor", "run"
    )
    assert code == 2


def test_sample_judge_feedback_curate_dataset(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out = run(
        project,
        capsys,
        "sample",
        "--window",
        "1h",
        "--budget",
        "80",
        "--out",
        str(project / "runs" / "sample.json"),
    )
    assert code == 0 and out["n"] == 80 and out["strata"]["error"] > 0
    code, out = run(
        project,
        capsys,
        "judge",
        "--sample",
        str(project / "runs" / "sample.json"),
        "--judge-invalid-rate",
        "0.2",
        "--out",
        str(project / "runs" / "judge.json"),
    )
    assert code == 0 and out["judged"] > 0 and out["missing"] >= 0 and out["slo_eligible"] is False
    code, out = run(
        project,
        capsys,
        "sample",
        "--strategy",
        "uniform",
        "--budget",
        "80",
        "--skip-judged",
        "--out",
        str(project / "runs" / "uniform.json"),
    )
    assert code == 0 and out["strata"]["random"] == 80
    code, out = run(project, capsys, "judge", "--sample", str(project / "runs" / "uniform.json"))
    assert code == 0 and out["slo_eligible"] is True
    code, out = run(project, capsys, "judge")
    assert code == 2
    trace_id = json.loads((project / "runs" / "uniform.json").read_text(encoding="utf-8"))[
        "trace_ids"
    ][0]
    code, out = run(
        project,
        capsys,
        "feedback",
        "add",
        "--trace-id",
        trace_id,
        "--thumbs",
        "down",
        "--wrong-part",
        "numbers",
        "--comment",
        "fee is wrong",
    )
    assert code == 0 and out["negative"] is True
    code, out = run(
        project,
        capsys,
        "feedback",
        "add",
        "--trace-id",
        trace_id,
        "--edited-text",
        "Totally rewritten.",
    )
    assert code == 0 and out["edit_ratio"] is not None
    assert run(project, capsys, "feedback", "add", "--trace-id", "missing")[0] == 2
    code, out = run(
        project,
        capsys,
        "curate",
        "--sample",
        str(project / "runs" / "uniform.json"),
        "--reviewer",
        "c.he",
        "--accept-all",
        "--out",
        str(project / "runs" / "review.jsonl"),
    )
    assert code == 0 and out["accepted"] == out["queued"] > 40
    code, out = run(
        project,
        capsys,
        "curate",
        "--trace-ids",
        trace_id,
        "--out",
        str(project / "runs" / "review2.jsonl"),
    )
    assert code == 0 and out["accepted"] == 0
    code, out = run(
        project,
        capsys,
        "dataset",
        "build",
        "--from-review",
        str(project / "runs" / "review.jsonl"),
        "--name",
        "adviser_assistant",
        "--changelog",
        "seed set",
    )
    assert code == 0 and out["version"] == 1 and out["n_cases"] > 40
    code, out = run(
        project,
        capsys,
        "dataset",
        "build",
        "--from-review",
        str(project / "runs" / "review2.jsonl"),
        "--name",
        "adviser_assistant",
        "--accept-pending",
    )
    assert code == 0 and out["version"] == 2 and out["duplicates_rejected"]
    code, out = run(project, capsys, "dataset", "list")
    assert code == 0 and [d["version"] for d in out] == [1, 2]
    code, out = run(
        project,
        capsys,
        "dataset",
        "diff",
        "--name",
        "adviser_assistant",
        "--from",
        "1",
        "--to",
        "2",
    )
    assert code == 0 and out["to"]["version"] == 2


def test_regress_gate_exit_codes(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(
        project,
        capsys,
        "regress",
        "--dataset",
        "adviser_assistant@v1",
        "--candidate",
        "@v2",
        "--baseline",
        "@v1",
        "--out",
        str(project / "runs" / "gate_good"),
        "--gate",
        "--min-cases",
        "10",
    )
    assert (
        code == 0
        and out["decision"] == "PASS"
        and (project / "runs" / "gate_good" / "report.md").exists()
    )
    code, out = run(
        project,
        capsys,
        "regress",
        "--dataset",
        "adviser_assistant",
        "--candidate",
        "adviser_assistant@v2-regressed",
        "--baseline",
        "adviser_assistant@v1",
        "--out",
        str(project / "runs" / "gate_bad"),
        "--gate",
        "--min-cases",
        "10",
        "--use-judge",
    )
    assert code == 1 and out["decision"] == "FAIL"
    code, _ = run(
        project,
        capsys,
        "regress",
        "--dataset",
        "adviser_assistant",
        "--candidate",
        "@v2-regressed",
        "--baseline",
        "@v1",
        "--out",
        str(project / "runs" / "gate_nogate"),
        "--min-cases",
        "10",
        "--limit",
        "12",
    )
    assert code == 0
    limited = json.loads((project / "runs" / "gate_nogate" / "report.json").read_text("utf-8"))
    assert limited["n_cases"] == 12
    assert (
        run(
            project,
            capsys,
            "regress",
            "--dataset",
            "nope",
            "--candidate",
            "@v2",
            "--baseline",
            "@v1",
        )[0]
        == 2
    )


def test_prompt_commands(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(project, capsys, "prompt", "list", "--name", "adviser_assistant")
    assert code == 0 and {p["ref"] for p in out} == {
        "adviser_assistant@v1",
        "adviser_assistant@v2",
        "adviser_assistant@v2-regressed",
    }
    code, out = run(project, capsys, "prompt", "lint", "--gate")
    assert code == 0 and out["adviser_assistant@v1"] == []
    code, out = run(
        project, capsys, "prompt", "diff", "adviser_assistant@v1", "adviser_assistant@v2"
    )
    assert code == 0 and "+- Quote figures exactly" in out
    code, out = run(
        project, capsys, "prompt", "render", "adviser_assistant@v1", "--var", "adviser_name=Priya"
    )
    assert code == 0 and "Priya" in out and "<client_name>" in out
    bad = project / "bad.yaml"
    bad.write_text(
        "name: bad\nversion: v1\ntemplate: 'Hi {{ who }} guaranteed return'\ninputs: []\n",
        encoding="utf-8",
    )
    code, out = run(project, capsys, "prompt", "register", str(bad))
    assert code == 0 and out["ref"] == "bad@v1"
    code, out = run(project, capsys, "prompt", "lint", "bad@v1", "--gate")
    assert code == 1 and {f["code"] for f in out["bad@v1"]} >= {
        "undeclared_placeholder",
        "forbidden_phrase",
    }
    bad.write_text("name: bad\nversion: v1\ntemplate: 'changed'\ninputs: []\n", encoding="utf-8")
    assert run(project, capsys, "prompt", "register", str(bad))[0] == 2
    assert run(project, capsys, "prompt", "register", str(bad), "--overwrite")[0] == 0
    assert run(project, capsys, "prompt", "render", "nope@v1")[0] == 2


def test_release_lifecycle(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = str(project / "runs" / "canary.sqlite")
    code, out = run(project, capsys, "--store", store, "release", "status")
    assert code == 0 and out["active"] == "v1" and out["canary"] is None
    code, out = run(
        project, capsys, "--store", store, "release", "start", "--version", "v2", "--stage", "50"
    )
    assert code == 0 and out["canary"]["stage"] == 50
    assert run(project, capsys, "release", "start", "--version", "v9")[0] == 2
    code, out = run(
        project,
        capsys,
        "--store",
        store,
        "demo",
        "traffic",
        "--scenario",
        str(project / "scenarios" / "canary.yaml"),
        "--minutes",
        "45",
        "--seed",
        "2",
        "--reset",
        "--use-release",
    )
    assert code == 0 and set(out["by_prompt_version"]) == {"v1", "v2"}
    code, out = run(
        project,
        capsys,
        "--store",
        store,
        "release",
        "auto",
        "--window",
        "2h",
        "--apply",
        "--out",
        str(project / "runs" / "canary.json"),
    )
    assert code == 0 and out["action"] == "advance" and out["release"]["canary"]["stage"] == 100
    code, out = run(project, capsys, "--store", store, "release", "auto", "--window", "2h")
    assert code == 0 and out["action"] == "promote" and out["applied"] is False
    code, out = run(project, capsys, "--store", store, "release", "advance", "--reason", "manual")
    assert code == 0 and out["active"] == "v2"
    assert run(project, capsys, "--store", store, "release", "rollback")[0] == 2
    code, out = run(
        project, capsys, "--store", store, "release", "start", "--version", "v2-regressed"
    )
    code, out = run(project, capsys, "--store", store, "release", "auto", "--window", "2h")
    assert code == 2 and out["action"] == "hold"
    code, out = run(project, capsys, "--store", store, "release", "rollback", "--reason", "cleanup")
    assert code == 0 and out["rolled_back"] == "v2-regressed"


def test_replay_incident_store_and_monitor_evaluate(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = TraceStore(project / "runs" / "traces.sqlite")
    trace_id = store.query(status="ok", limit=1)[0].trace_id
    store.close()
    code, out = run(
        project,
        capsys,
        "replay",
        trace_id,
        "--model",
        "fake",
        "--seed",
        str(SEED),
        "--out",
        str(project / "runs" / "replay.md"),
    )
    assert code == 0 and out["identical"] is True
    code, out = run(project, capsys, "replay", trace_id, "--prompt-version", "v2-regressed")
    assert code == 0 and "similarity" in out
    assert run(project, capsys, "replay", "missing")[0] == 2
    code, out = run(
        project,
        capsys,
        "incident",
        "report",
        "--window",
        "1h",
        "--out",
        str(project / "runs" / "incident.md"),
        "--title",
        "Burst",
    )
    assert code == 0 and out["n_failed"] > 0 and (project / "runs" / "incident.json").exists()
    code, out = run(
        project,
        capsys,
        "incident",
        "report",
        "--since",
        "2026-09-01T00:30:00Z",
        "--until",
        "2026-09-01T01:00:00Z",
    )
    assert code == 0 and out["n_requests"] > 0
    code, out = run(
        project,
        capsys,
        "store",
        "export",
        "--out",
        str(project / "runs" / "export.jsonl"),
        "--since",
        "2026-09-01T00:30:00Z",
    )
    assert code == 0 and out["exported"] > 0
    code, out = run(
        project, capsys, "store", "prune", "--older-than", "30m", "--now", "2026-09-01T01:00:00Z"
    )
    assert code == 0 and out["removed"] > 0 and out["remaining"] > 0
    code, out = run(
        project,
        capsys,
        "monitor",
        "evaluate",
        "--scenarios",
        str(project / "scenarios" / "tiny.yaml"),
        "--seeds",
        "1",
        "--minutes",
        "60",
        "--out",
        str(project / "runs" / "eval"),
        "--gate",
        "--max-false-alarm",
        "1.0",
    )
    assert (
        code == 0
        and out["kinds"][0]["detected"] == 1
        and (project / "runs" / "eval" / "monitor_evaluation.md").exists()
    )
    code, out = run(
        project,
        capsys,
        "monitor",
        "evaluate",
        "--scenarios",
        str(project / "scenarios" / "tiny.yaml"),
        "--seeds",
        "1",
        "--minutes",
        "60",
        "--out",
        str(project / "runs" / "eval2"),
        "--gate",
        "--min-detection",
        "2.0",
    )
    assert code == 1


def test_serve_export_and_collector_url(
    project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    served: list[dict[str, Any]] = []

    class FakeUvicorn:
        @staticmethod
        def run(app: Any, **kwargs: Any) -> None:
            served.append({"routes": {r.path for r in app.routes}, **kwargs})

    monkeypatch.setitem(__import__("sys").modules, "uvicorn", FakeUvicorn)
    assert run(project, capsys, "serve", "--port", "1234")[0] == 0
    assert "/v1/traces" in served[0]["routes"] and served[0]["port"] == 1234
    assert run(project, capsys, "monitor", "export")[0] == 0 and "/metrics" in served[1]["routes"]
    posted: list[str] = []

    class FakeExporter:
        def __init__(self, url: str) -> None:
            posted.append(url)

        def __call__(self, trace: Any) -> None:
            posted.append(trace.trace_id)

    monkeypatch.setattr("opsloop.sdk.exporters.HttpExporter", FakeExporter)
    code, out = run(
        project,
        capsys,
        "--store",
        str(project / "runs" / "http.sqlite"),
        "demo",
        "traffic",
        "--scenario",
        str(project / "scenarios" / "tiny.yaml"),
        "--minutes",
        "5",
        "--collector-url",
        "http://collector:8090",
        "--start",
        "2026-09-02T00:00:00Z",
    )
    assert code == 0 and out["posted_to_collector"] == out["n_requests"] == len(posted) - 1


def test_version_and_help() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    parser = cli.build_parser()
    assert parser.prog == "opsloop"
