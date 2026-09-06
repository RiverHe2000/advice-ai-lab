"""Deterministic claim verification (citations, lexical / numeric / date agreement, decision
language, action-item owner, off-topic content, optional semantic similarity) and its
self-evaluation against planted hallucinations of known kinds."""

from filenote.verify.verifier import (
    ClaimVerdict,
    VerificationReport,
    Verifier,
    VerifierConfig,
)

__all__ = ["ClaimVerdict", "VerificationReport", "Verifier", "VerifierConfig"]
