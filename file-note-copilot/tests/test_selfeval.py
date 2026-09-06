from __future__ import annotations

import random
from pathlib import Path

import pytest

from filenote.corpus import Meeting
from filenote.schema import ActionItem
from filenote.verify import Verifier
from filenote.verify.plant import PLANT_KINDS, PlantKind, change_number, plant
from filenote.verify.selfeval import evaluate_verifier, render_selfeval_md, save_selfeval


@pytest.mark.parametrize("kind", PLANT_KINDS)
def test_each_planted_kind_is_detected(
    corpus: list[Meeting], verifier: Verifier, kind: PlantKind
) -> None:
    hits = 0
    n = 0
    for m in corpus:
        planted = plant(m, kind, random.Random(f"t|{kind}|{m.id}"))
        if planted is None:
            continue
        note, section, index = planted
        n += 1
        verdict = verifier.verify(note, m.transcript).verdict_for(section, index)
        assert verdict is not None
        hits += verdict.status == "unsupported"
    assert n >= 8
    assert hits / n >= 0.85, f"{kind}: {hits}/{n}"


def test_plant_changes_exactly_one_thing(meeting: Meeting) -> None:
    rng = random.Random(1)
    note, section, index = plant(meeting, "wrong_owner", rng) or (None, "", 0)
    assert note is not None
    item = note.section_items(section)[index]  # type: ignore[arg-type]
    assert isinstance(item, ActionItem)
    assert item.owner != meeting.gold.action_items[index].owner
    assert len(note.action_items) == len(meeting.gold.action_items)
    note2, _, idx2 = plant(meeting, "wrong_date", random.Random(2)) or (None, "", 0)
    assert note2 is not None
    assert note2.action_items[idx2].due != meeting.gold.action_items[idx2].due
    note3, sec3, idx3 = plant(meeting, "deferred_as_decided", random.Random(3)) or (None, "", 0)
    assert note3 is not None and sec3 == "decisions"
    assert note3.decisions[idx3].text.startswith("Client agreed to proceed with")


def test_plant_returns_none_without_hosts(meeting: Meeting) -> None:
    bare = meeting.model_copy(deep=True)
    bare.deferred = []
    bare.small_talk_ids = []
    bare.gold.action_items = []
    assert plant(bare, "deferred_as_decided", random.Random(0)) is None
    assert plant(bare, "small_talk_leakage", random.Random(0)) is None
    assert plant(bare, "wrong_owner", random.Random(0)) is None
    assert plant(bare, "wrong_date", random.Random(0)) is None
    for section in (
        "circumstance_changes",
        "goals",
        "topics_discussed",
        "advice_discussed",
        "decisions",
    ):
        setattr(bare.gold, section, [])
    bare.gold.compliance.vulnerability_indicators = []
    assert plant(bare, "changed_number", random.Random(0)) is None
    bare.gold.follow_up = None
    assert plant(bare, "wrong_citation", random.Random(0)) is None


def test_change_number_forms() -> None:
    rng = random.Random(0)
    assert change_number("no figures", rng) is None
    assert change_number("fee 0.5% per year", rng) != "fee 0.5% per year"
    out = change_number("retire at 65", rng)
    assert out is not None and out != "retire at 65"
    money = change_number("salary $95,000 and $82,000", rng)
    assert money is not None and money.count("$") == 2 and money != "salary $95,000 and $82,000"


def test_evaluate_verifier_report_and_gate(
    corpus: list[Meeting], verifier: Verifier, tmp_path: Path
) -> None:
    report = evaluate_verifier(corpus[:6], verifier, seed=0, n_boot=50)
    assert report.meetings == 6
    assert report.clean_claims > 50
    assert {k.kind for k in report.kinds} == set(PLANT_KINDS)
    assert report.false_alarm_unsupported["mean"] == 0.0
    assert 0.0 <= report.calibration["ece"] <= 1.0
    assert report.gate(min_detection=0.5, max_false_alarm=0.05) == []
    failures = report.gate(min_detection=1.01, max_false_alarm=-1.0)
    assert any("detection" in f for f in failures)
    assert any("false alarm" in f for f in failures)
    md = render_selfeval_md(report, gate_failures=[])
    assert "**PASS**" in md
    assert "| invented_decision |" in md
    md_fail = render_selfeval_md(report, gate_failures=["x"])
    assert "**FAIL**" in md_fail
    json_path, md_path = save_selfeval(report, tmp_path / "out", md)
    assert json_path.exists() and md_path.read_text(encoding="utf-8") == md
