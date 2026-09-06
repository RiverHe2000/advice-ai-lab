"""Tolerant JSON extraction for model output: strip code fences, find the outermost object,
remove trailing commas. Every successful repair is counted so the rate can be reported.
Truncated output is deliberately *not* closed up: a partial note would be a silent default;
it is a parse failure that triggers a bounded retry and, after that, a missing result."""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def outermost_object(text: str) -> str | None:
    """The first complete ``{...}`` at brace depth zero, string-aware; ``None`` if truncated."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def repair_json(text: str) -> tuple[dict[str, Any] | None, bool]:
    """``(object, repaired)``; ``(None, True)`` when nothing could be parsed."""
    candidates: list[str] = [text]
    fence = _FENCE_RE.search(text)
    if fence:
        candidates.append(fence.group(1))
    outer = outermost_object(fence.group(1) if fence else text)
    if outer:
        candidates.append(outer)
        candidates.append(_TRAILING_COMMA_RE.sub(r"\1", outer))
    for i, candidate in enumerate(candidates):
        try:
            obj = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(obj, dict):
            return obj, i > 0
    return None, True
