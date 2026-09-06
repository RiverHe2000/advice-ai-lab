"""Seeded synthetic client meetings: a structured seed → a speaker-labelled transcript and the
gold file note whose every item cites the segments that support it, plus what the note must
*not* contain (small talk, deferred advice)."""

from filenote.corpus.generate import (
    Meeting,
    corpus_stats,
    generate_corpus,
    generate_meeting,
    load_corpus,
    render_stats_md,
    save_corpus,
)
from filenote.corpus.seed import MeetingSeed, generate_seed

__all__ = [
    "Meeting",
    "MeetingSeed",
    "corpus_stats",
    "generate_corpus",
    "generate_meeting",
    "generate_seed",
    "load_corpus",
    "render_stats_md",
    "save_corpus",
]
