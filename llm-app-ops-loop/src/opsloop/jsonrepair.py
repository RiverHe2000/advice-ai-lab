"""Tolerant JSON extraction for model output: strip code fences, take the outermost object,
drop trailing commas. Every repair is counted so reports can say how often the model needed one;
a failure after repair is a *missing* result for the caller, never a silent default."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", flags=re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


@dataclass(frozen=True, slots=True)
class RepairResult:
    value: Any | None
    repairs: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.value is not None


def _outermost(text: str, open_ch: str, close_ch: str) -> str | None:
    start = text.find(open_ch)
    end = text.rfind(close_ch)
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]


def repair_json(text: str) -> RepairResult:
    """Parse ``text`` as JSON with bounded, counted repairs.

    Order: as-is → fenced block → outermost ``{…}`` (or ``[…]``) → trailing commas removed.
    """
    repairs = 0
    candidate = text.strip()
    try:
        return RepairResult(json.loads(candidate), 0)
    except (json.JSONDecodeError, TypeError):
        pass
    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
        repairs += 1
        try:
            return RepairResult(json.loads(candidate), repairs)
        except json.JSONDecodeError:
            pass
    inner = _outermost(candidate, "{", "}") or _outermost(candidate, "[", "]")
    if inner is None:
        return RepairResult(None, repairs, "no JSON object found")
    if inner != candidate:
        repairs += 1
    try:
        return RepairResult(json.loads(inner), repairs)
    except json.JSONDecodeError:
        pass
    stripped = _TRAILING_COMMA.sub(r"\1", inner)
    if stripped != inner:
        repairs += 1
    try:
        return RepairResult(json.loads(stripped), repairs)
    except json.JSONDecodeError as exc:
        return RepairResult(None, repairs, f"invalid JSON after repair: {exc.msg}")


def is_valid_json(text: str) -> bool:
    """Strict validity (no repair): what the JSON-validity SLO counts."""
    try:
        json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return False
    return True
