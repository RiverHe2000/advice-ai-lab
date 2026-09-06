from __future__ import annotations

import json
import random
from pathlib import Path

from filenote.corpus import (
    Meeting,
    corpus_stats,
    generate_corpus,
    generate_meeting,
    generate_seed,
    load_corpus,
    render_stats_md,
    save_corpus,
)
from filenote.corpus.seed import VULNERABILITY_LINES
from filenote.numbers import find_dates, number_set


def _dump(meetings: list[Meeting]) -> str:
    return "\n".join(json.dumps(m.model_dump(mode="json"), sort_keys=True) for m in meetings)


def test_generation_is_deterministic(corpus: list[Meeting]) -> None:
    again = generate_corpus(12, 11)
    assert _dump(again) == _dump(corpus)
    other = generate_corpus(12, 12)
    assert _dump(other) != _dump(corpus)


def test_segment_count_and_ids(corpus: list[Meeting]) -> None:
    for m in corpus:
        n = len(m.transcript.segments)
        assert 40 <= n <= 120
        assert m.transcript.segment_ids == [f"s{i:03d}" for i in range(1, n + 1)]
        times = [s.t for s in m.transcript.segments]
        assert times == sorted(times)


def test_every_gold_claim_cites_existing_segments(corpus: list[Meeting]) -> None:
    for m in corpus:
        ids = set(m.transcript.segment_ids)
        for _, _, item in m.gold.iter_claims():
            assert item.evidence
            assert set(item.evidence) <= ids


def test_small_talk_is_never_cited_and_exists(corpus: list[Meeting]) -> None:
    for m in corpus:
        assert m.small_talk_ids
        cited = {e for item in m.gold.all_claims() for e in item.evidence}
        assert not cited & set(m.small_talk_ids)


def test_deferred_advice_never_becomes_a_decision(corpus: list[Meeting]) -> None:
    assert all(m.deferred for m in corpus)
    for m in corpus:
        decisions = {c.text for c in m.gold.decisions}
        for d in m.deferred:
            assert d.text not in decisions
            assert d.text in {a.text for a in m.gold.advice_discussed}


def test_gold_numbers_and_dates_agree_with_cited_segments(corpus: list[Meeting]) -> None:
    for m in corpus:
        by_id = m.transcript.by_id()
        transcript_numbers = number_set(" ".join(s.text for s in m.transcript.segments))
        for _, _, item in m.gold.iter_claims():
            evidence = " ".join(by_id[e].text for e in item.evidence)
            label = item.label
            due = getattr(item, "due", None)
            if due is not None:
                label += f" due {due.isoformat()}"
            assert number_set(label) <= number_set(evidence), (m.id, label)
            for d in find_dates(label)[0]:
                assert any(d.agrees(e) for e in find_dates(evidence)[0]), (m.id, label)
        assert number_set(m.gold.summary) <= transcript_numbers


def test_decisions_cite_commitment_and_speakers(corpus: list[Meeting]) -> None:
    for m in corpus:
        by_id = m.transcript.by_id()
        for c in m.gold.decisions:
            roles = {by_id[e].role for e in c.evidence}
            assert "client" in roles
            assert "adviser" in roles


def test_seed_variety_and_pii_asides() -> None:
    rng = random.Random(3)
    seeds = [generate_seed(i, rng) for i in range(40)]
    kinds = {p.kind for s in seeds if (p := s.pii_aside) is not None}
    assert {"phone", "email", "address", "dob", "tfn"} <= kinds
    assert any(len(s.clients) == 2 for s in seeds)
    assert any(s.paraplanner is not None for s in seeds)
    assert any(s.compliance.vulnerability for s in seeds)
    assert all(any(t.decided is False for t in s.topics) for s in seeds)
    assert {s.type for s in seeds} == {
        "initial",
        "annual_review",
        "insurance_review",
        "retirement_planning",
    }


def test_vulnerability_and_pii_render_into_transcript() -> None:
    found_v = found_p = False
    for i in range(1, 60):
        m = generate_meeting(i, 11)
        if m.seed.compliance.vulnerability:
            found_v = True
            line = VULNERABILITY_LINES[m.seed.compliance.vulnerability[0]][0]
            assert any(line in s.text for s in m.transcript.segments)
            assert m.gold.compliance.vulnerability_indicators
        if m.seed.pii_aside is not None:
            found_p = True
            assert any(m.seed.pii_aside.value in s.text for s in m.transcript.segments)
        if found_v and found_p:
            break
    assert found_v and found_p


def test_save_load_and_stats(tmp_path: Path, corpus: list[Meeting]) -> None:
    path = save_corpus(corpus, tmp_path / "c" / "meetings.jsonl")
    loaded = load_corpus(path)
    assert _dump(loaded) == _dump(corpus)
    stats = corpus_stats(corpus)
    assert stats["meetings"] == 12
    assert stats["segments"]["min"] >= 40
    assert stats["meetings_with_deferral"] == 12
    md = render_stats_md(stats, seed=11)
    assert "| annual_review |" in md or "| initial |" in md
    assert "gold claims" in md
    assert corpus_stats([])["meetings"] == 0
