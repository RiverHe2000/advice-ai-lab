"""Per-meeting metrics against the gold note: fuzzy one-to-one matching per section (rapidfuzz
token-set ratio; owner must agree for action items; due dates scored exact / ±3 days),
precision / recall / F1, hallucination and omission rates, compliance-flag accuracy, verifier
and numeric-grounding rates, small-talk leakage, JSON repairs, latency and tokens."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz

from filenote.corpus.generate import Meeting
from filenote.draft.base import DraftResult
from filenote.schema import CLAIM_SECTIONS, ActionItem, Evidenced, FileNote
from filenote.verify.verifier import VerificationReport, Verifier

MATCH_THRESHOLD = 80
DUE_TOLERANCE_DAYS = 3
COMPLIANCE_KEYS = (
    "risk_profile_confirmed",
    "risk_profile",
    "fee_consent_discussed",
    "conflicts_disclosed",
)


def match_items(
    pred: Sequence[Evidenced],
    gold: Sequence[Evidenced],
    *,
    threshold: int = MATCH_THRESHOLD,
    require_owner: bool = False,
) -> list[tuple[int, int, float]]:
    """Greedy one-to-one matching by descending similarity: ``(pred_idx, gold_idx, score)``."""
    pairs: list[tuple[float, int, int]] = []
    for i, p in enumerate(pred):
        for j, g in enumerate(gold):
            owners_differ = (
                isinstance(p, ActionItem) and isinstance(g, ActionItem) and p.owner != g.owner
            )
            if require_owner and owners_differ:
                continue
            score = fuzz.token_set_ratio(p.label.lower(), g.label.lower())
            if score >= threshold:
                pairs.append((float(score), i, j))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_p: set[int] = set()
    used_g: set[int] = set()
    out: list[tuple[int, int, float]] = []
    for score, i, j in pairs:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        out.append((i, j, score))
    return out


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


class SectionMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    n_pred: int
    n_gold: int
    tp: int
    fp: int
    fn: int
    precision: float
    recall: float
    f1: float
    due_exact: float | None = None
    due_within_tolerance: float | None = None


class MeetingMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meeting_id: str
    failed: bool = False
    sections: dict[str, SectionMetrics] = Field(default_factory=dict)
    claims_pred: int = 0
    claims_gold: int = 0
    matched: int = 0
    unmatched_pred: int = 0
    hallucinated: int = 0
    hallucination_rate: float = 0.0
    unmatched_rate: float = 0.0
    omission_rate: float = 0.0
    surfaced: int = 0
    surfaced_rate: float | None = None
    unsupported_remaining: int = 0
    compliance_accuracy: float = 0.0
    verifier_supported_fraction: float = 0.0
    numeric_grounding_rate: float = 0.0
    small_talk_leaks: int = 0
    json_repairs: int = 0
    parse_failures: int = 0
    failed_windows: int = 0
    model_calls: int = 0
    repair_cited: int = 0
    repair_dropped: int = 0
    latency_s: float = 0.0
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def macro_f1(self) -> float:
        keys = ("circumstance_changes", "goals", "decisions", "action_items")
        return sum(self.sections[k].f1 for k in keys if k in self.sections) / len(keys)

    @property
    def hallucination_free(self) -> bool:
        return not self.failed and self.hallucinated == 0

    def section_f1(self, section: str) -> float:
        return self.sections[section].f1 if section in self.sections else 0.0


def _due_scores(
    pred: list[Evidenced], gold: list[Evidenced], matches: list[tuple[int, int, float]]
) -> tuple[float | None, float | None]:
    exact = 0
    near = 0
    n = 0
    for i, j, _ in matches:
        p, g = pred[i], gold[j]
        if not (isinstance(p, ActionItem) and isinstance(g, ActionItem)):
            continue
        n += 1
        if p.due == g.due:
            exact += 1
            near += 1
        elif p.due is not None and g.due is not None:
            if abs((p.due - g.due).days) <= DUE_TOLERANCE_DAYS:
                near += 1
    if n == 0:
        return None, None
    return exact / n, near / n


def compliance_accuracy(pred: FileNote, gold: FileNote) -> float:
    hits = 0
    for key in COMPLIANCE_KEYS:
        p = getattr(pred.compliance, key)
        g = getattr(gold.compliance, key)
        if isinstance(p, str) and isinstance(g, str):
            hits += int(p.strip().lower() == g.strip().lower())
        else:
            hits += int(p == g)
    return hits / len(COMPLIANCE_KEYS)


def evaluate_note(
    meeting: Meeting,
    note: FileNote,
    verifier: Verifier,
    *,
    result: DraftResult | None = None,
) -> MeetingMetrics:
    gold = meeting.gold
    report: VerificationReport = verifier.verify(note, meeting.transcript)
    metrics = MeetingMetrics(meeting_id=meeting.id)
    small_talk = set(meeting.small_talk_ids)
    total_pred = 0
    total_gold = 0
    total_matched = 0
    hallucinated = 0
    surfaced = 0
    for section in CLAIM_SECTIONS:
        pred = note.section_items(section)
        gold_items = gold.section_items(section)
        matches = match_items(pred, gold_items, require_owner=section == "action_items")
        tp = len(matches)
        fp = len(pred) - tp
        fn = len(gold_items) - tp
        precision, recall, f1 = prf(tp, fp, fn)
        due_exact, due_near = (
            _due_scores(pred, gold_items, matches) if section == "action_items" else (None, None)
        )
        metrics.sections[section] = SectionMetrics(
            section=section,
            n_pred=len(pred),
            n_gold=len(gold_items),
            tp=tp,
            fp=fp,
            fn=fn,
            precision=precision,
            recall=recall,
            f1=f1,
            due_exact=due_exact,
            due_within_tolerance=due_near,
        )
        matched_pred = {i for i, _, _ in matches}
        for i, item in enumerate(pred):
            if any(e in small_talk for e in item.evidence):
                metrics.small_talk_leaks += 1
            if i in matched_pred:
                continue
            verdict = report.verdict_for(section, i)
            if verdict is not None and verdict.status == "unsupported":
                hallucinated += 1
                if item.unsupported and not item.edited:
                    surfaced += 1
        total_pred += len(pred)
        total_gold += len(gold_items)
        total_matched += tp
    metrics.claims_pred = total_pred
    metrics.claims_gold = total_gold
    metrics.matched = total_matched
    metrics.unmatched_pred = total_pred - total_matched
    metrics.hallucinated = hallucinated
    metrics.hallucination_rate = hallucinated / total_pred if total_pred else 0.0
    metrics.unmatched_rate = (total_pred - total_matched) / total_pred if total_pred else 0.0
    metrics.omission_rate = (total_gold - total_matched) / total_gold if total_gold else 0.0
    metrics.surfaced = surfaced
    metrics.surfaced_rate = surfaced / hallucinated if hallucinated else None
    metrics.unsupported_remaining = note.unsupported_count()
    metrics.compliance_accuracy = compliance_accuracy(note, gold)
    metrics.verifier_supported_fraction = report.supported_fraction
    metrics.numeric_grounding_rate = report.numeric_grounding_rate
    if result is not None:
        metrics.json_repairs = result.json_repairs
        metrics.parse_failures = result.parse_failures
        metrics.failed_windows = len(result.failed_windows)
        metrics.model_calls = result.model_calls
        metrics.repair_cited = result.repair_cited
        metrics.repair_dropped = len(result.repair_dropped)
        metrics.latency_s = result.latency_s
        metrics.prompt_tokens = result.prompt_tokens
        metrics.completion_tokens = result.completion_tokens
    return metrics


def failed_metrics(meeting: Meeting, *, latency_s: float = 0.0) -> MeetingMetrics:
    """A meeting whose draft never parsed: recorded as missing (recall 0), never defaulted."""
    metrics = MeetingMetrics(meeting_id=meeting.id, failed=True, latency_s=latency_s)
    for section in CLAIM_SECTIONS:
        n_gold = len(meeting.gold.section_items(section))
        precision, recall, f1 = prf(0, 0, n_gold)
        metrics.sections[section] = SectionMetrics(
            section=section, n_pred=0, n_gold=n_gold, tp=0, fp=0, fn=n_gold,
            precision=precision, recall=recall, f1=f1,
        )  # fmt: skip
    metrics.claims_gold = len(meeting.gold.all_claims())
    metrics.omission_rate = 1.0
    metrics.parse_failures = 1
    return metrics


def as_row(metrics: MeetingMetrics) -> dict[str, Any]:
    row: dict[str, Any] = {
        "meeting_id": metrics.meeting_id,
        "failed": metrics.failed,
        "macro_f1": round(metrics.macro_f1, 4),
        "hallucination_rate": round(metrics.hallucination_rate, 4),
        "omission_rate": round(metrics.omission_rate, 4),
        "unsupported_remaining": metrics.unsupported_remaining,
        "latency_s": round(metrics.latency_s, 3),
    }
    for s in ("circumstance_changes", "goals", "decisions", "action_items"):
        row[f"{s}_f1"] = round(metrics.section_f1(s), 4)
    return row


def today() -> dt.date:
    return dt.date.today()
