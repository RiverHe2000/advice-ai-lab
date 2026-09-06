"""Heuristic answer scorers: empty answer, refusal phrases, PII leak, **numeric grounding**
against recorded tool outputs, JSON validity, length budget, tone, and dataset expectations
(must / must-not contain). Cheap and deterministic, so they run on *every* trace at ingest;
the LLM judge (``judge.py``) is sampled."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from opsloop.jsonrepair import is_valid_json
from opsloop.pii import contains_marker, find_pii
from opsloop.sdk.models import Trace

REFUSAL_PATTERNS: tuple[str, ...] = (
    r"\bI can only (?:help|answer)\b",
    r"\bI (?:cannot|can't|am unable to|'m unable to) (?:answer|help|provide|assist|confirm)\b",
    r"\bnot (?:something|a question) I can (?:answer|help)\b",
    r"\boutside (?:what|the scope of what) I can\b",
    r"\bunable to answer\b",
    r"\bcannot answer\b",
    r"\bI (?:don't|do not) have (?:access|enough)\b",
)
COURTESY_PATTERNS: tuple[str, ...] = (
    r"\blet me know\b",
    r"\bhappy to\b",
    r"\bif you(?:'d| would) like\b",
    r"\bhope (?:this|that) helps\b",
)
_REFUSAL = re.compile("|".join(REFUSAL_PATTERNS), flags=re.IGNORECASE)
_COURTESY = re.compile("|".join(COURTESY_PATTERNS), flags=re.IGNORECASE)
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.-])-?\$?\d[\d,]*(?:\.\d+)?\s?%?(?![A-Za-z0-9_])")

WEIGHTS = {
    "non_empty": 1.0,
    "no_refusal": 3.0,
    "no_pii": 2.0,
    "grounded": 3.0,
    "json_valid": 2.0,
    "length_ok": 0.5,
    "tone_ok": 0.5,
    "must_contain": 2.0,
    "must_not_contain": 2.0,
}


@dataclass(slots=True)
class HeuristicScores:
    empty: bool
    refusal: bool
    pii_leak: bool
    grounded: bool
    ungrounded_numbers: list[str]
    n_numbers: int
    json_expected: bool
    json_valid: bool | None
    length_ok: bool
    tone_ok: bool | None
    must_contain_ok: bool | None
    must_not_contain_ok: bool | None
    allow_refusal: bool
    quality: float = 0.0
    passed: bool = False
    checks: dict[str, bool] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "empty": self.empty,
            "refusal": self.refusal,
            "pii_leak": self.pii_leak,
            "grounded": self.grounded,
            "ungrounded_numbers": list(self.ungrounded_numbers),
            "n_numbers": self.n_numbers,
            "json_expected": self.json_expected,
            "json_valid": self.json_valid,
            "length_ok": self.length_ok,
            "tone_ok": self.tone_ok,
            "must_contain_ok": self.must_contain_ok,
            "must_not_contain_ok": self.must_not_contain_ok,
            "quality": round(self.quality, 4),
            "passed": self.passed,
        }


def is_refusal(text: str) -> bool:
    return bool(_REFUSAL.search(text))


def _parse_number(token: str) -> float | None:
    raw = token.replace("$", "").replace(",", "").replace(" ", "").rstrip("%")
    if raw.startswith("-") and len(raw) == 1:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[tuple[str, float]]:
    """Numeric tokens in an answer, with ISO dates removed first (they are matched as strings)."""
    cleaned = _ISO_DATE.sub(" ", text)
    out: list[tuple[str, float]] = []
    for m in _NUMBER.finditer(cleaned):
        token = m.group(0).strip()
        value = _parse_number(token)
        if value is not None:
            out.append((token, value))
    return out


def evidence_values(
    obj: Any, values: set[float] | None = None, strings: set[str] | None = None
) -> tuple[set[float], set[str]]:
    """Every number reachable in ``obj`` (with the percentage form of fractions in (0, 1]) and
    every string, for grounding checks."""
    values = values if values is not None else set()
    strings = strings if strings is not None else set()
    if isinstance(obj, bool):
        return values, strings
    if isinstance(obj, int | float):
        v = float(obj)
        values.add(v)
        values.add(round(v, 2))
        if 0.0 < abs(v) <= 1.0:
            values.add(round(v * 100.0, 2))
        return values, strings
    if isinstance(obj, str):
        strings.add(obj)
        for _, v in extract_numbers(obj):
            values.add(v)
        for d in _ISO_DATE.findall(obj):
            strings.add(d)
        return values, strings
    if isinstance(obj, dict):
        for v in obj.values():
            evidence_values(v, values, strings)
    elif isinstance(obj, list | tuple):
        for v in obj:
            evidence_values(v, values, strings)
    return values, strings


def numeric_grounding(
    answer: str, evidence: Any, *, extra_text: str = "", tolerance: float = 0.005
) -> tuple[bool, list[str], int]:
    """Every number in the answer must appear in the evidence (tool outputs + question)."""
    values, strings = evidence_values(evidence)
    evidence_values(extra_text, values, strings)
    evidence_text = " ".join(sorted(strings))
    ungrounded: list[str] = []
    numbers = extract_numbers(answer)
    for token, value in numbers:
        if any(abs(value - v) <= tolerance for v in values):
            continue
        bare = token.replace("$", "").replace(",", "").rstrip("%").strip()
        if bare and bare in evidence_text:
            continue
        ungrounded.append(token)
    for date in _ISO_DATE.findall(answer):
        if date not in strings and date not in evidence_text:
            ungrounded.append(date)
    return not ungrounded, ungrounded, len(numbers)


def score_answer(
    answer: str,
    *,
    tool_outputs: Any,
    question: str = "",
    json_expected: bool = False,
    max_chars: int = 1500,
    must_contain: Sequence[str] = (),
    must_not_contain: Sequence[str] = (),
    numeric_facts: Sequence[float] = (),
    allow_refusal: bool = False,
    pii_markers: bool = True,
) -> HeuristicScores:
    text = answer or ""
    empty = len(text.strip()) == 0
    refusal = (not empty) and is_refusal(text)
    pii_leak = bool(find_pii(text)) or (pii_markers and contains_marker(text))
    evidence: Any = {"tool_outputs": tool_outputs, "numeric_facts": list(numeric_facts)}
    grounded, ungrounded, n_numbers = numeric_grounding(text, evidence, extra_text=question)
    json_valid: bool | None = is_valid_json(text) if json_expected else None
    length_ok = len(text) <= max_chars
    tone_ok: bool | None = (
        None if json_expected or empty else bool(_COURTESY.search(text)) and not refusal
    )
    lowered = text.lower()
    must_ok: bool | None = all(s.lower() in lowered for s in must_contain) if must_contain else None
    must_not_ok: bool | None = (
        not any(s.lower() in lowered for s in must_not_contain) if must_not_contain else None
    )
    scores = HeuristicScores(
        empty=empty,
        refusal=refusal,
        pii_leak=pii_leak,
        grounded=grounded,
        ungrounded_numbers=ungrounded,
        n_numbers=n_numbers,
        json_expected=json_expected,
        json_valid=json_valid,
        length_ok=length_ok,
        tone_ok=tone_ok,
        must_contain_ok=must_ok,
        must_not_contain_ok=must_not_ok,
        allow_refusal=allow_refusal,
    )
    checks: dict[str, bool] = {
        "non_empty": not empty,
        "no_pii": not pii_leak,
        "grounded": grounded,
        "length_ok": length_ok,
    }
    if not allow_refusal:
        checks["no_refusal"] = not refusal
    if json_valid is not None:
        checks["json_valid"] = json_valid
    if tone_ok is not None:
        checks["tone_ok"] = tone_ok
    if must_ok is not None:
        checks["must_contain"] = must_ok
    if must_not_ok is not None:
        checks["must_not_contain"] = must_not_ok
    total = sum(WEIGHTS[k] for k in checks)
    scores.quality = sum(WEIGHTS[k] for k, ok in checks.items() if ok) / total
    scores.passed = all(
        checks[k]
        for k in (
            "non_empty",
            "no_pii",
            "grounded",
            "no_refusal",
            "json_valid",
            "must_contain",
            "must_not_contain",
        )
        if k in checks
    )
    scores.checks = checks
    return scores


def score_trace(trace: Trace, *, max_chars: int = 1500) -> HeuristicScores | None:
    """Heuristic scores for a stored trace; ``None`` for error traces (the error SLO owns those)."""
    if trace.status != "ok":
        return None
    blocked = bool(trace.attributes.get("guardrail.blocked", False))
    return score_answer(
        trace.output_text,
        tool_outputs=trace.tool_outputs(),
        question=trace.input_text,
        json_expected=trace.json_expected and not blocked,
        max_chars=max_chars,
        allow_refusal=blocked,
    )
