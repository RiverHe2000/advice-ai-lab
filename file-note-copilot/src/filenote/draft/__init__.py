"""Drafting strategies behind one ``Drafter`` protocol: ``single_shot`` (one prompt → whole
note), ``extract_then_compose`` (windowed fact extraction, then composition from the facts
alone) and ``verified`` (``extract_then_compose`` + the claim verifier + one bounded repair
pass that may cite evidence or drop a claim, never silently)."""

from filenote.draft.base import Drafter, DraftError, DraftEvent, DraftResult, ProgressFn
from filenote.draft.facts import Fact, FactList, compose_from_facts
from filenote.draft.strategies import (
    ExtractThenComposeDrafter,
    SingleShotDrafter,
    VerifiedDrafter,
    build_drafter,
)

__all__ = [
    "DraftError",
    "DraftEvent",
    "DraftResult",
    "Drafter",
    "ExtractThenComposeDrafter",
    "Fact",
    "FactList",
    "ProgressFn",
    "SingleShotDrafter",
    "VerifiedDrafter",
    "build_drafter",
    "compose_from_facts",
]
