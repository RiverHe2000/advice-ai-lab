"""The prompt regression gate: candidate vs baseline prompt on the same cases with the same
model, paired bootstrap with a non-inferiority margin, exact McNemar, per-slice non-regression,
a JSON-validity floor, cost and latency budgets, and an exit code for CI."""

from opsloop.regression.gate import GateConfig, GateReport, render_markdown, run_gate

__all__ = ["GateConfig", "GateReport", "render_markdown", "run_gate"]
