"""Corpus container, persistence and statistics. ``generate_corpus(n, seed)`` is deterministic:
the same seed gives byte-identical JSON."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from filenote.corpus.render import render_meeting
from filenote.corpus.seed import MeetingSeed, generate_seed
from filenote.schema import CLAIM_SECTIONS, Claim, FileNote, Transcript


class Meeting(BaseModel):
    """One synthetic meeting with its ground truth."""

    model_config = ConfigDict(extra="forbid")

    seed: MeetingSeed
    transcript: Transcript
    gold: FileNote
    small_talk_ids: list[str] = Field(default_factory=list)
    deferred: list[Claim] = Field(
        default_factory=list, description="advice discussed but explicitly deferred"
    )

    @property
    def id(self) -> str:
        return self.seed.id


def generate_meeting(index: int, seed: int) -> Meeting:
    rng = random.Random(seed * 1_000_003 + index)
    meeting_seed = generate_seed(index, rng)
    rendered = render_meeting(meeting_seed, rng)
    rendered.gold.validate_against(rendered.transcript)
    return Meeting(
        seed=meeting_seed,
        transcript=rendered.transcript,
        gold=rendered.gold,
        small_talk_ids=rendered.small_talk_ids,
        deferred=rendered.deferred,
    )


def generate_corpus(n: int, seed: int) -> list[Meeting]:
    return [generate_meeting(i + 1, seed) for i in range(n)]


def save_corpus(meetings: list[Meeting], path: Path | str) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8", newline="\n") as fh:
        for m in meetings:
            fh.write(
                json.dumps(m.model_dump(mode="json"), sort_keys=True, ensure_ascii=False) + "\n"
            )
    return p


def load_corpus(path: Path | str) -> list[Meeting]:
    with Path(path).open(encoding="utf-8") as fh:
        return [Meeting.model_validate_json(line) for line in fh if line.strip()]


def corpus_stats(meetings: list[Meeting]) -> dict[str, Any]:
    n_seg = [len(m.transcript.segments) for m in meetings]
    n_claims = [len(m.gold.all_claims()) for m in meetings]
    per_section = {
        s: sum(len(m.gold.section_items(s)) for m in meetings) / max(1, len(meetings))
        for s in CLAIM_SECTIONS
    }
    types: dict[str, int] = {}
    for m in meetings:
        types[m.seed.type] = types.get(m.seed.type, 0) + 1
    return {
        "meetings": len(meetings),
        "segments": {
            "total": sum(n_seg),
            "mean": sum(n_seg) / max(1, len(meetings)),
            "min": min(n_seg, default=0),
            "max": max(n_seg, default=0),
        },
        "gold_claims": {
            "total": sum(n_claims),
            "mean": sum(n_claims) / max(1, len(meetings)),
            "per_section_mean": per_section,
        },
        "decisions_total": sum(len(m.gold.decisions) for m in meetings),
        "deferred_total": sum(len(m.deferred) for m in meetings),
        "meetings_with_deferral": sum(1 for m in meetings if m.deferred),
        "small_talk_segments_total": sum(len(m.small_talk_ids) for m in meetings),
        "small_talk_segments_mean": sum(len(m.small_talk_ids) for m in meetings)
        / max(1, len(meetings)),
        "meetings_with_vulnerability": sum(
            1 for m in meetings if m.gold.compliance.vulnerability_indicators
        ),
        "meetings_with_pii_aside": sum(1 for m in meetings if m.seed.pii_aside is not None),
        "meetings_with_two_clients": sum(1 for m in meetings if len(m.seed.clients) == 2),
        "meetings_with_paraplanner": sum(1 for m in meetings if m.seed.paraplanner is not None),
        "by_type": dict(sorted(types.items())),
        "duration_minutes_mean": sum(m.gold.meeting.duration_minutes or 0 for m in meetings)
        / max(1, len(meetings)),
    }


def render_stats_md(stats: dict[str, Any], *, seed: int) -> str:
    seg = stats["segments"]
    cl = stats["gold_claims"]
    lines = [
        "# Corpus statistics",
        "",
        f"- meetings: {stats['meetings']} (seed {seed})",
        f"- segments: {seg['total']} total, {seg['mean']:.1f} mean, "
        f"{seg['min']} to {seg['max']} range",
        f"- gold claims: {cl['total']} total, {cl['mean']:.1f} per meeting",
        f"- decisions: {stats['decisions_total']}; explicitly deferred advice items: "
        f"{stats['deferred_total']} ({stats['meetings_with_deferral']} meetings with at least "
        f"one deferral)",
        f"- small-talk / admin segments never cited: {stats['small_talk_segments_total']} "
        f"({stats['small_talk_segments_mean']:.1f} per meeting)",
        f"- meetings with a vulnerability indicator: {stats['meetings_with_vulnerability']}; "
        f"with a PII aside (phone / e-mail / address / DOB / TFN): "
        f"{stats['meetings_with_pii_aside']}",
        f"- couples: {stats['meetings_with_two_clients']}; paraplanner present: "
        f"{stats['meetings_with_paraplanner']}",
        f"- mean duration: {stats['duration_minutes_mean']:.0f} minutes",
        "",
        "| Meeting type | n |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v} |" for k, v in stats["by_type"].items()]
    lines += ["", "| Section | Gold claims per meeting |", "|---|---:|"]
    lines += [f"| {k} | {v:.2f} |" for k, v in cl["per_section_mean"].items()]
    return "\n".join(lines) + "\n"
