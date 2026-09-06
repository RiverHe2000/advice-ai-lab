from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

import pytest

from filenote.config import Settings
from filenote.corpus import Meeting
from filenote.draft import build_drafter
from filenote.eval.metrics import (
    MeetingMetrics,
    as_row,
    compliance_accuracy,
    evaluate_note,
    failed_metrics,
    match_items,
    prf,
)
from filenote.eval.report import render_report_md
from filenote.eval.runner import (
    EvalReport,
    GateThresholds,
    apply_gate,
    compare_runs,
    run_strategy,
    save_report,
)
from filenote.eval.stats import (
    bootstrap_ci,
    cluster_bootstrap_rate,
    expected_calibration_error,
    mcnemar_exact,
    paired_bootstrap,
)
from filenote.schema import ActionItem, Claim
from filenote.verify import Verifier
from tests.conftest import FakeFactory

# ----- statistics ---------------------------------------------------------------------------


def test_bootstrap_ci_basic() -> None:
    iv = bootstrap_ci([0.0, 1.0, 1.0, 1.0], n_boot=500, seed=1)
    assert iv.mean == 0.75
    assert iv.low <= 0.75 <= iv.high
    assert iv.n == 4
    assert "75.0%" in iv.fmt(pct=True)
    assert bootstrap_ci([]).fmt() == "n/a"
    single = bootstrap_ci([0.4])
    assert (single.low, single.high) == (0.4, 0.4)
    assert bootstrap_ci([1.0, 2.0], n_boot=0).low == 1.5


def test_cluster_bootstrap() -> None:
    iv = cluster_bootstrap_rate([[1, 0, 0], [0, 0], [1, 1, 1, 1]], n_boot=300, seed=0)
    assert iv.mean == pytest.approx(5 / 9)
    assert iv.n == 9
    assert iv.low <= iv.mean <= iv.high
    assert math.isnan(cluster_bootstrap_rate([[]]).mean)
    assert cluster_bootstrap_rate([[1, 0]]).low == 0.5


def test_mcnemar_exact_known_values() -> None:
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 0) == pytest.approx(2 * 0.5**5)
    assert mcnemar_exact(3, 3) == 1.0
    assert mcnemar_exact(9, 1) == pytest.approx(2 * (1 + 10) / 2**10)


def test_paired_bootstrap_verdicts() -> None:
    better = paired_bootstrap([1.0] * 12, [0.5] * 11 + [1.0], n_boot=200, seed=0)
    assert better.verdict == "better" and better.wins == 11 and better.losses == 0
    worse = paired_bootstrap([0.2] * 10, [0.9] * 10, n_boot=200, seed=0)
    assert worse.verdict == "worse"
    same = paired_bootstrap([0.5] * 10, [0.5] * 10, n_boot=200, seed=0, non_inferiority_margin=0.05)
    assert same.verdict == "non-inferior" and same.mcnemar_p == 1.0
    noisy = paired_bootstrap(
        [0.9, 0.1, 0.9, 0.1, 0.9, 0.1], [0.1, 0.9, 0.1, 0.9, 0.1, 0.95], n_boot=300, seed=0
    )
    assert noisy.verdict == "inconclusive"
    empty = paired_bootstrap([], [])
    assert empty.verdict == "no pairs" and empty.n_pairs == 0
    one = paired_bootstrap([1.0], [0.0])
    assert one.verdict == "better" and one.p_improve == 1.0
    with pytest.raises(ValueError, match="equal-length"):
        paired_bootstrap([1.0], [1.0, 2.0])
    binary = paired_bootstrap(
        [1.0, 1.0, 0.0],
        [0.0, 1.0, 1.0],
        binary=[(True, False), (True, True), (False, True)],
        n_boot=10,
    )
    assert (binary.wins, binary.losses) == (1, 1)
    assert "verdict" in binary.to_dict()


def test_expected_calibration_error() -> None:
    cal = expected_calibration_error([0.95, 0.9, 0.1, 0.15, 0.5], [True, True, False, False, True])
    assert 0.0 <= cal.ece <= 1.0
    assert cal.n == 5
    assert sum(b.n for b in cal.bins) == 5
    assert "| Bin |" in cal.table()
    assert cal.to_dict()["n"] == 5
    assert math.isnan(expected_calibration_error([], []).ece)
    perfect = expected_calibration_error([1.0, 1.0, 0.0], [True, True, False])
    assert perfect.ece == 0.0


# ----- matching and metrics ----------------------------------------------------------------


def test_prf_edge_cases() -> None:
    assert prf(0, 0, 0) == (1.0, 1.0, 1.0)
    assert prf(0, 0, 3) == (0.0, 0.0, 0.0)
    assert prf(2, 1, 1) == (2 / 3, 2 / 3, 2 / 3)


def test_match_items_fuzzy_owner_and_one_to_one() -> None:
    gold = [
        ActionItem(
            description="Send the ongoing fee consent form for signature",
            owner="adviser",
            evidence=["s1"],
        ),
        ActionItem(description="Send the latest super statement", owner="client", evidence=["s2"]),
    ]
    pred = [
        ActionItem(
            description="send ongoing fee consent form for signature",
            owner="adviser",
            evidence=["s1"],
        ),
        ActionItem(description="Send the latest super statement", owner="adviser", evidence=["s2"]),
        ActionItem(description="Send the latest super statement", owner="client", evidence=["s2"]),
    ]
    matches = match_items(pred, gold, require_owner=True)
    assert sorted((p, g) for p, g, _ in matches) == [(0, 0), (2, 1)]
    loose = match_items(pred, gold, require_owner=False)
    assert len(loose) == 2
    assert (
        match_items(
            [Claim(text="totally different", evidence=["x"])],
            [Claim(text="retire at 65", evidence=["y"])],
        )
        == []
    )


def test_evaluate_note_hand_built(meeting: Meeting, verifier: Verifier) -> None:
    gold = meeting.gold
    note = gold.model_copy(deep=True)
    dropped = note.goals.pop(0)  # omission
    note.decisions.append(
        Claim(
            text="Client agreed to buy a yacht for $2,000,000.",
            evidence=[meeting.transcript.segment_ids[0]],
            unsupported=True,
        )
    )
    note.action_items[0].owner = (
        "paraplanner" if note.action_items[0].owner != "paraplanner" else "client"
    )
    if note.action_items[0].due is not None:
        note.action_items[0].due = note.action_items[0].due + dt.timedelta(days=2)
    note.compliance.fee_consent_discussed = not gold.compliance.fee_consent_discussed
    metrics = evaluate_note(meeting, note, verifier)
    # the invented decision and the re-owned action item both have no gold match and fail
    # the verifier; only the invented one was flagged in the note itself
    assert metrics.hallucinated == 2
    assert metrics.surfaced == 1
    assert metrics.surfaced_rate == 0.5
    assert metrics.sections["decisions"].fp == 1
    assert metrics.sections["goals"].fn == 1
    assert metrics.omission_rate > 0
    assert metrics.hallucination_rate == pytest.approx(2 / metrics.claims_pred)
    assert metrics.sections["action_items"].tp == len(gold.action_items) - 1
    assert metrics.compliance_accuracy == 0.75
    assert metrics.unsupported_remaining == 1
    assert metrics.macro_f1 < 1.0
    assert not metrics.hallucination_free
    row = as_row(metrics)
    assert row["meeting_id"] == meeting.id and "decisions_f1" in row
    assert dropped.text not in [g.text for g in note.goals]
    perfect = evaluate_note(meeting, gold, verifier)
    assert perfect.macro_f1 == 1.0 and perfect.hallucinated == 0 and perfect.surfaced_rate is None
    assert perfect.sections["action_items"].due_exact == 1.0
    assert perfect.small_talk_leaks == 0


def test_due_tolerance_and_small_talk(meeting: Meeting, verifier: Verifier) -> None:
    note = meeting.gold.model_copy(deep=True)
    if note.action_items[0].due is not None:
        note.action_items[0].due = note.action_items[0].due + dt.timedelta(days=3)
    note.topics_discussed.append(
        Claim(text="Client mentioned the weather", evidence=[meeting.small_talk_ids[0]])
    )
    m = evaluate_note(meeting, note, verifier)
    sec = m.sections["action_items"]
    assert sec.due_exact is not None and sec.due_within_tolerance is not None
    assert sec.due_within_tolerance >= sec.due_exact
    assert m.small_talk_leaks == 1


def test_compliance_accuracy_strings() -> None:
    a = Claim(text="x", evidence=["s"])
    _ = a
    note = MeetingMetrics(meeting_id="m")
    assert note.section_f1("goals") == 0.0
    from filenote.schema import ComplianceFlags, FileNote, MeetingMeta

    meta = MeetingMeta(date=dt.date(2026, 1, 1), type="initial")
    p = FileNote(meeting=meta, compliance=ComplianceFlags(risk_profile="balanced "))
    g = FileNote(meeting=meta, compliance=ComplianceFlags(risk_profile="Balanced"))
    assert compliance_accuracy(p, g) == 1.0


def test_failed_metrics(meeting: Meeting) -> None:
    m = failed_metrics(meeting, latency_s=1.5)
    assert m.failed and m.omission_rate == 1.0 and m.parse_failures == 1
    assert m.sections["decisions"].recall == 0.0
    assert m.macro_f1 == 0.0
    assert not m.hallucination_free


# ----- runner --------------------------------------------------------------------------------


def test_run_compare_gate_and_report(
    corpus: list[Meeting], make_fake: FakeFactory, settings: Settings, tmp_path: Path
) -> None:
    meetings = corpus[:6]
    verifier = Verifier()
    clean = run_strategy(
        meetings,
        build_drafter("verified", make_fake(0.0), settings),
        verifier,
        name="clean",
        n_boot=50,
    )
    noisy = run_strategy(
        meetings,
        build_drafter("single_shot", make_fake(0.4, seed=2), settings),
        verifier,
        name="noisy",
        corruption=0.4,
        n_boot=50,
        pseudonymise=True,
    )
    assert clean.aggregate["macro_f1"]["mean"] == 1.0
    assert clean.totals["hallucinated_claims"] == 0
    assert noisy.aggregate["macro_f1"]["mean"] < 1.0
    assert noisy.model.startswith("fake")
    comparisons = compare_runs(clean, noisy, n_boot=50)
    by_metric = {c.metric: c.result for c in comparisons}
    assert by_metric["macro_f1"]["verdict"] == "better"
    assert by_metric["hallucination_rate"]["verdict"] in ("better", "inconclusive", "non-inferior")
    assert float(by_metric["hallucination_rate"]["delta"]) <= 0.0
    with pytest.raises(ValueError, match="same meetings"):
        compare_runs(
            clean,
            run_strategy(
                meetings[:3],
                build_drafter("verified", make_fake(0.0), settings),
                verifier,
                n_boot=10,
            ),
        )
    assert apply_gate(clean, GateThresholds()) == []
    strict = GateThresholds(
        min_macro_f1=1.0,
        min_decisions_f1=1.0,
        max_hallucination_rate=0.0,
        max_omission_rate=0.0,
        min_surfaced_rate=1.0,
    )
    failures = apply_gate(noisy, strict)
    assert len(failures) >= 4
    report = EvalReport(
        created="now",
        corpus={"meetings": 6, "seed": 11, "n_boot": 50},
        runs=[clean, noisy],
        comparisons=comparisons,
        gate={"run": "noisy", "failures": failures},
    )
    md = render_report_md(report)
    assert "### clean" in md and "pseudonymised" in md and "**FAIL**" in md
    assert "| clean | noisy | macro_f1 |" in md
    json_path, md_path = save_report(report, tmp_path / "r", md)
    loaded = EvalReport.model_validate_json(json_path.read_text(encoding="utf-8"))
    assert loaded.run("clean").totals == clean.totals
    with pytest.raises(KeyError):
        loaded.run("nope")
    assert md_path.read_text(encoding="utf-8") == md


def test_run_strategy_records_failed_meetings(corpus: list[Meeting], settings: Settings) -> None:
    from filenote.llm import ScriptedChatModel

    bad = ScriptedChatModel(default="nope")
    run = run_strategy(
        corpus[:2], build_drafter("single_shot", bad, settings), Verifier(), n_boot=10
    )
    assert run.totals["failed"] == 2
    assert all(m.failed for m in run.meetings)
    assert apply_gate(run, GateThresholds())
    md = render_report_md(EvalReport(created="c", runs=[run]))
    assert "failed meetings 2" in md
