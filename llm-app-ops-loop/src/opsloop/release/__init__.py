"""Prompt canary: deterministic session bucketing, staged rollout, and automatic rollback from a
cohort comparison (two-proportion tests on error / refusal rates, bootstrap on quality)."""

from opsloop.release.canary import (
    CanaryDecision,
    CanaryPolicy,
    CanaryState,
    CohortMetrics,
    PromptRelease,
    ReleaseFile,
    assign,
    bucket,
    cohort_metrics,
    evaluate_canary,
    resolve_version,
)

__all__ = [
    "CanaryDecision",
    "CanaryPolicy",
    "CanaryState",
    "CohortMetrics",
    "PromptRelease",
    "ReleaseFile",
    "assign",
    "bucket",
    "cohort_metrics",
    "evaluate_canary",
    "resolve_version",
]
