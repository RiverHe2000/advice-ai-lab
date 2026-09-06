"""The claim verifier. Model-free by default; every check is a named, configurable rule so the
adviser sees *why* a claim is flagged, and the self-evaluation can attribute detections."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from filenote.numbers import find_dates, number_set
from filenote.schema import (
    ActionItem,
    ClaimSection,
    Evidenced,
    FileNote,
    Owner,
    Segment,
    Transcript,
)
from filenote.verify.embed import Embedder, build_embedder, cosine
from filenote.verify.text import domain_terms, overlap

Status = Literal["supported", "weak", "unsupported"]

DEFAULT_COMMITMENT = [
    r"\bagree(?:d|s)?\b",
    r"\bgo ahead\b",
    r"\blet'?s (?:do|go|proceed|lock)\b",
    r"\block (?:that|it|this) in\b",
    r"\bhappy to proceed\b",
    r"\bproceed with\b",
    r"\bwe'?ll (?:set up|put|move|switch|increase|reduce|start|lodge|renew|make|go|get|update"
    r"|proceed)\b",
    r"\bdo it\b",
    r"\bsign(?:ed)? off\b",
    r"\bdecided\b",
    r"\bgo with\b",
]
DEFAULT_DEFERRAL = [
    r"\bthink about\b",
    r"\bnot yet\b",
    r"\bnext time\b",
    r"\bnext review\b",
    r"\bhold off\b",
    r"\bpark (?:that|it|this)\b",
    r"\brevisit\b",
    r"\bnot ready\b",
    r"\bsleep on it\b",
    r"\bcome back to\b",
    r"\bleave (?:it|that) for now\b",
    r"\bno rush\b",
    r"\bnot sure\b",
    r"\bmaybe later\b",
    r"\bdefer\b",
    r"\bnot today\b",
]


class VerifierConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    support_overlap: float = Field(0.5, ge=0.0, le=1.0)
    weak_overlap: float = Field(0.25, ge=0.0, le=1.0)
    require_numbers: bool = True
    require_dates: bool = True
    check_decision_language: bool = True
    check_owner: bool = True
    check_off_topic: bool = True
    check_speaker: bool = True
    section_speakers: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "decisions": ["client", "adviser"],
            "goals": ["client", "adviser"],
            "circumstance_changes": ["client", "adviser"],
            "vulnerability_indicators": ["client"],
        }
    )
    commitment_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMITMENT))
    deferral_patterns: list[str] = Field(default_factory=lambda: list(DEFAULT_DEFERRAL))
    semantic: bool = False
    semantic_threshold: float = Field(0.5, ge=-1.0, le=1.0)
    embedder: str = "hashing"


class ClaimVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str
    index: int
    text: str
    status: Status
    score: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)


class VerificationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdicts: list[ClaimVerdict] = Field(default_factory=list)
    ungrounded_numbers: list[float] = Field(default_factory=list)
    note_numbers: int = 0

    @property
    def counts(self) -> dict[str, int]:
        out = {"supported": 0, "weak": 0, "unsupported": 0}
        for v in self.verdicts:
            out[v.status] += 1
        return out

    @property
    def supported_fraction(self) -> float:
        return self.counts["supported"] / len(self.verdicts) if self.verdicts else 1.0

    @property
    def numeric_grounding_rate(self) -> float:
        if self.note_numbers == 0:
            return 1.0
        return 1.0 - len(self.ungrounded_numbers) / self.note_numbers

    def summary(self) -> dict[str, Any]:
        return {
            **self.counts,
            "claims": len(self.verdicts),
            "supported_fraction": round(self.supported_fraction, 4),
            "numeric_grounding_rate": round(self.numeric_grounding_rate, 4),
            "ungrounded_numbers": self.ungrounded_numbers,
        }

    def verdict_for(self, section: str, index: int) -> ClaimVerdict | None:
        for v in self.verdicts:
            if v.section == section and v.index == index:
                return v
        return None


_OWNER_ADVISER = re.compile(r"\b(?:i'?ll|i will|i can|i'?m going to|let me)\b")
_OWNER_CLIENT_ASK = re.compile(
    r"\b(?:could you|can you|if you could|you'?ll need to|please send|you send|would you)\b"
)
_OWNER_CLIENT_SAY = re.compile(r"\b(?:i'?ll|i will|we'?ll|we will|sure|yes|i can)\b")
_OWNER_PP_SAY = re.compile(r"\b(?:i'?ll|i will|i can)\b")


def _paraplanner_names(transcript: Transcript) -> list[str]:
    names = ["paraplanner"]
    for a in transcript.attendees:
        if a.role == "paraplanner":
            names.append(a.name.lower())
            names.append(a.name.split()[0].lower())
    return names


def implied_owners(segments: list[Segment], transcript: Transcript) -> set[Owner]:
    """Who the cited dialogue says will do the thing; empty when the text does not say."""
    votes: set[Owner] = set()
    pp_names = _paraplanner_names(transcript)
    for s in segments:
        t = s.text.lower()
        if s.role == "paraplanner":
            if _OWNER_PP_SAY.search(t):
                votes.add("paraplanner")
        elif s.role == "adviser":
            if _OWNER_CLIENT_ASK.search(t):
                votes.add("client")
            elif any(re.search(rf"\b{re.escape(n)}\b.*\bwill\b", t) for n in pp_names):
                votes.add("paraplanner")
            elif _OWNER_ADVISER.search(t):
                votes.add("adviser")
        elif s.role == "client" and _OWNER_CLIENT_SAY.search(t):
            votes.add("client")
    return votes


class Verifier:
    def __init__(
        self, config: VerifierConfig | None = None, *, embedder: Embedder | None = None
    ) -> None:
        self.config = config or VerifierConfig()
        self._commit = [re.compile(p, re.IGNORECASE) for p in self.config.commitment_patterns]
        self._defer = [re.compile(p, re.IGNORECASE) for p in self.config.deferral_patterns]
        self._embedder: Embedder | None = embedder
        if self.config.semantic and self._embedder is None:
            self._embedder = build_embedder(self.config.embedder)

    # ----- language checks ------------------------------------------------------------------

    def has_commitment(self, text: str) -> bool:
        return any(p.search(text) for p in self._commit)

    def has_deferral(self, text: str) -> bool:
        return any(p.search(text) for p in self._defer)

    # ----- one claim --------------------------------------------------------------------------

    def verify_claim(
        self, item: Evidenced, section: ClaimSection, index: int, transcript: Transcript
    ) -> ClaimVerdict:
        cfg = self.config
        by_id = transcript.by_id()
        label = item.label
        reasons: list[str] = []
        soft: list[str] = []
        checks: dict[str, Any] = {}
        invalid = [e for e in item.evidence if e not in by_id]
        valid = [e for e in item.evidence if e in by_id]
        if invalid:
            reasons.append(f"unknown segment id(s): {', '.join(invalid)}")
        if not valid:
            return ClaimVerdict(
                section=section,
                index=index,
                text=label,
                status="unsupported",
                score=0.0,
                reasons=reasons or ["no evidence cited"],
                checks={"citation": False},
            )
        segments = [by_id[e] for e in valid]
        evidence_text = " ".join(s.text for s in segments)
        checks["citation"] = not invalid

        lex = overlap(label, evidence_text)
        checks["lexical_overlap"] = round(lex, 3)

        claim_text = label
        if isinstance(item, ActionItem) and item.due is not None:
            claim_text += f" due {item.due.isoformat()}"
        if cfg.require_numbers:
            missing = sorted(number_set(claim_text) - number_set(evidence_text))
            checks["missing_numbers"] = missing
            if missing:
                shown = ", ".join(f"{m:g}" for m in missing)
                reasons.append(f"figure(s) not in cited segments: {shown}")
        if cfg.require_dates:
            claim_dates, _ = find_dates(claim_text)
            evidence_dates, _ = find_dates(evidence_text)
            bad = [d for d in claim_dates if not any(d.agrees(e) for e in evidence_dates)]
            checks["missing_dates"] = [str(d) for d in bad]
            if bad:
                reasons.append(f"date(s) not in cited segments: {', '.join(str(d) for d in bad)}")

        if cfg.check_speaker and section in cfg.section_speakers:
            allowed = cfg.section_speakers[section]
            if not any(s.role in allowed for s in segments):
                soft.append(f"no cited segment is spoken by {' / '.join(allowed)}")
        if cfg.check_decision_language and section == "decisions":
            committed = [
                s for s in segments if self.has_commitment(s.text) and not self.has_deferral(s.text)
            ]
            checks["commitment"] = bool(committed)
            if not committed:
                if any(self.has_deferral(s.text) for s in segments):
                    reasons.append("cited segments contain deferral language, not a decision")
                else:
                    reasons.append("no commitment language in cited segments")
        if cfg.check_owner and isinstance(item, ActionItem):
            owners = implied_owners(segments, transcript)
            checks["implied_owners"] = sorted(owners)
            if owners and item.owner not in owners:
                reasons.append(
                    f"cited dialogue assigns this to {' / '.join(sorted(owners))}, not {item.owner}"
                )
        if (
            cfg.check_off_topic
            and section != "follow_up"
            and not domain_terms(label)
            and not domain_terms(evidence_text)
        ):
            reasons.append("no advice-related content (small talk?)")
        if self._embedder is not None:
            a, b = self._embedder.encode([label, evidence_text])
            sim = cosine(a, b)
            checks["semantic"] = round(sim, 3)
            if sim < cfg.semantic_threshold:
                soft.append(f"semantic similarity {sim:.2f} below {cfg.semantic_threshold:.2f}")

        status: Status
        if reasons:
            status = "unsupported"
            score = 0.0
        elif lex < cfg.weak_overlap:
            status = "unsupported"
            reasons.append(f"lexical support {lex:.2f} below {cfg.weak_overlap:.2f}")
            score = lex * 0.5
        elif lex < cfg.support_overlap or soft:
            status = "weak"
            reasons.extend(soft or [f"lexical support {lex:.2f} below {cfg.support_overlap:.2f}"])
            score = 0.5 + 0.3 * lex
        else:
            status = "supported"
            score = 0.7 + 0.3 * lex
        return ClaimVerdict(
            section=section,
            index=index,
            text=label,
            status=status,
            score=round(min(1.0, score), 4),
            reasons=reasons,
            checks=checks,
        )

    # ----- whole note -------------------------------------------------------------------------

    def verify(self, note: FileNote, transcript: Transcript) -> VerificationReport:
        verdicts = [
            self.verify_claim(item, section, i, transcript)
            for section, i, item in note.iter_claims()
        ]
        transcript_numbers = number_set(" ".join(s.text for s in transcript.segments))
        note_numbers: set[float] = number_set(note.summary)
        for item in note.all_claims():
            note_numbers |= number_set(item.label)
            if isinstance(item, ActionItem) and item.due is not None:
                pass  # dates are checked per claim, not as figures
        ungrounded = sorted(note_numbers - transcript_numbers)
        return VerificationReport(
            verdicts=verdicts, ungrounded_numbers=ungrounded, note_numbers=len(note_numbers)
        )

    def apply(self, note: FileNote, report: VerificationReport) -> FileNote:
        """Mark unsupported claims in place (never delete); adviser-edited claims are left alone."""
        for section, i, item in note.iter_claims():
            verdict = report.verdict_for(section, i)
            if verdict is None or item.edited:
                continue
            item.unsupported = verdict.status == "unsupported"
            item.reasons = list(verdict.reasons) if item.unsupported else []
        return note
