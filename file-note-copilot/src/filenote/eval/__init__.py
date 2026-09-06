"""Evaluation against gold: per-section precision / recall / F1, hallucination and omission
rates, compliance accuracy, verifier and grounding rates, latency and tokens; bootstrap
intervals, paired comparisons across strategies and models on identical transcripts, reports
and a CI gate."""

from filenote.eval.stats import (
    Interval,
    PairedComparison,
    bootstrap_ci,
    cluster_bootstrap_rate,
    expected_calibration_error,
    mcnemar_exact,
    paired_bootstrap,
)

__all__ = [
    "Interval",
    "PairedComparison",
    "bootstrap_ci",
    "cluster_bootstrap_rate",
    "expected_calibration_error",
    "mcnemar_exact",
    "paired_bootstrap",
]
