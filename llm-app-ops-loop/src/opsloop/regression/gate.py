"""``opsloop regress --dataset ... --candidate adviser_assistant@v2 --baseline @v1``.

Both prompts answer every case (same model, same recorded context), the heuristic scorers
(and optionally the judge) score each answer, and the decision is:

* paired bootstrap on per-case quality deltas: the 95 % CI lower bound must be >= -margin;
* exact McNemar on per-case pass/fail: significantly more losses than wins fails;
* every slice (tag) with enough cases must not regress by more than the slice margin (wider
  than the overall margin because slices are small; a slice delta inside the margin is still
  reported, which is how a deliberate trade-off such as terser review answers stays visible);
* JSON validity on JSON cases must stay above the floor;
* mean cost per case and p95 latency must stay within budget relative to the baseline;
* fewer than ``min_cases`` paired cases is INSUFFICIENT_DATA, which also fails.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import BaseModel, Field

from opsloop.dataset.curate import CuratedCase
from opsloop.dataset.versioning import Dataset
from opsloop.demo.app import build_messages
from opsloop.llm import ChatModel, ModelError
from opsloop.prompts.registry import PromptRegistry, PromptSpec
from opsloop.quality.judge import judge_answer
from opsloop.quality.scorers import score_answer
from opsloop.sdk.pricing import PriceTable
from opsloop.stats import mcnemar_exact, paired_bootstrap, percentile

Decision = Literal["PASS", "FAIL", "INSUFFICIENT_DATA"]


class GateConfig(BaseModel):
    margin: float = 0.05  # non-inferiority margin on the mean per-case score
    alpha: float = 0.05
    slice_margin: float = 0.15  # wider: slices hold 5-40 cases and one case moves the mean a lot
    slice_min_cases: int = 5
    json_validity_floor: float = 0.95
    cost_budget_ratio: float = 1.5
    latency_budget_ratio: float | None = None
    latency_p95_budget_ms: float | None = None
    min_cases: int = 20
    n_boot: int = 2000
    seed: int = 0
    use_judge: bool = False
    judge_weight: float = 0.5


class CaseRun(BaseModel):
    case_id: str
    tags: list[str]
    answer: str
    quality: float
    passed: bool
    checks: dict[str, bool]
    ungrounded_numbers: list[str]
    json_valid: bool | None
    cost_usd: float | None
    latency_ms: float
    prompt_tokens: int | None
    completion_tokens: int | None
    judge_mean: float | None = None
    judge_missing: bool = False
    error: str | None = None


class SliceResult(BaseModel):
    tag: str
    n: int
    baseline_mean: float
    candidate_mean: float
    delta: float
    ok: bool


class GateReport(BaseModel):
    dataset: str
    dataset_version: int
    dataset_hash: str
    candidate: str
    candidate_hash: str
    baseline: str
    baseline_hash: str
    model: str
    n_cases: int
    decision: Decision
    reasons: list[str]
    paired: dict[str, Any]
    mcnemar: dict[str, Any]
    slices: list[SliceResult]
    json_validity: dict[str, Any]
    cost: dict[str, Any]
    latency: dict[str, Any]
    judge: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)
    candidate_runs: list[CaseRun] = Field(default_factory=list)
    baseline_runs: list[CaseRun] = Field(default_factory=list)


def run_case(
    case: CuratedCase,
    spec: PromptSpec,
    model: ChatModel,
    *,
    prices: PriceTable,
    judge: ChatModel | None = None,
) -> CaseRun:
    variables = dict(case.context.get("prompt_variables", {}))
    tool_outputs = dict(case.context.get("tool_outputs", {}))
    messages = build_messages(spec, variables, case.input, tool_outputs)
    started = time.perf_counter()
    try:
        resp = model.chat(messages, max_tokens=int(spec.metadata.get("max_tokens", 400)))
    except ModelError as exc:
        return CaseRun(
            case_id=case.id,
            tags=case.tags,
            answer="",
            quality=0.0,
            passed=False,
            checks={},
            ungrounded_numbers=[],
            json_valid=None,
            cost_usd=None,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            prompt_tokens=None,
            completion_tokens=None,
            error=str(exc),
        )
    latency_ms = (
        resp.latency_s * 1000.0 if resp.latency_s else (time.perf_counter() - started) * 1000.0
    )
    scores = score_answer(
        resp.text,
        tool_outputs=tool_outputs,
        question=case.input,
        json_expected=case.expected.json_expected,
        must_contain=case.expected.must_contain,
        must_not_contain=case.expected.must_not_contain,
        numeric_facts=case.expected.numeric_facts,
        allow_refusal=case.expected.allow_refusal,
    )
    cost = prices.cost(resp.model, resp.prompt_tokens, resp.completion_tokens)
    judge_mean: float | None = None
    judge_missing = False
    if judge is not None:
        jr = judge_answer(
            judge,
            trace_id=case.id,
            question=case.input,
            answer=resp.text,
            tool_outputs=tool_outputs,
        )
        judge_missing = jr.missing
        judge_mean = None if jr.scores is None else jr.scores.mean
    return CaseRun(
        case_id=case.id,
        tags=case.tags,
        answer=resp.text,
        quality=scores.quality,
        passed=scores.passed,
        checks=scores.checks,
        ungrounded_numbers=scores.ungrounded_numbers,
        json_valid=scores.json_valid,
        cost_usd=cost.usd,
        latency_ms=latency_ms,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
        judge_mean=judge_mean,
        judge_missing=judge_missing,
    )


def _score(run: CaseRun, cfg: GateConfig) -> float:
    if cfg.use_judge and run.judge_mean is not None:
        judge01 = (run.judge_mean - 1.0) / 4.0
        return (1.0 - cfg.judge_weight) * run.quality + cfg.judge_weight * judge01
    return run.quality


def run_gate(
    dataset: Dataset,
    *,
    candidate: str,
    baseline: str,
    model: ChatModel,
    registry: PromptRegistry,
    config: GateConfig | None = None,
    judge: ChatModel | None = None,
    prices: PriceTable | None = None,
) -> GateReport:
    cfg = config or GateConfig()
    prices = prices or PriceTable()
    cand_spec = registry.get(candidate)
    base_spec = registry.get(baseline)
    cand_runs = [
        run_case(c, cand_spec, model, prices=prices, judge=judge if cfg.use_judge else None)
        for c in dataset.cases
    ]
    base_runs = [
        run_case(c, base_spec, model, prices=prices, judge=judge if cfg.use_judge else None)
        for c in dataset.cases
    ]
    return decide(
        dataset, cand_spec, base_spec, cand_runs, base_runs, model_name=model.name, config=cfg
    )


def decide(
    dataset: Dataset,
    cand_spec: PromptSpec,
    base_spec: PromptSpec,
    cand_runs: Sequence[CaseRun],
    base_runs: Sequence[CaseRun],
    *,
    model_name: str,
    config: GateConfig,
) -> GateReport:
    cfg = config
    reasons: list[str] = []
    n = len(cand_runs)
    cand_scores = [_score(r, cfg) for r in cand_runs]
    base_scores = [_score(r, cfg) for r in base_runs]
    paired = paired_bootstrap(cand_scores, base_scores, n_boot=cfg.n_boot, seed=cfg.seed)
    wins = sum(1 for c, b in zip(cand_runs, base_runs, strict=True) if c.passed and not b.passed)
    losses = sum(1 for c, b in zip(cand_runs, base_runs, strict=True) if b.passed and not c.passed)
    p_mcnemar = mcnemar_exact(wins, losses)
    slices: list[SliceResult] = []
    by_tag: dict[str, list[int]] = {}
    for i, r in enumerate(cand_runs):
        for t in r.tags:
            by_tag.setdefault(t, []).append(i)
    for tag, idx in sorted(by_tag.items()):
        if len(idx) < cfg.slice_min_cases:
            continue
        bm = sum(base_scores[i] for i in idx) / len(idx)
        cm = sum(cand_scores[i] for i in idx) / len(idx)
        slices.append(
            SliceResult(
                tag=tag,
                n=len(idx),
                baseline_mean=round(bm, 4),
                candidate_mean=round(cm, 4),
                delta=round(cm - bm, 4),
                ok=cm - bm >= -cfg.slice_margin,
            )
        )
    json_c = [r.json_valid for r in cand_runs if r.json_valid is not None]
    json_b = [r.json_valid for r in base_runs if r.json_valid is not None]
    json_rate_c = sum(1 for v in json_c if v) / len(json_c) if json_c else None
    json_rate_b = sum(1 for v in json_b if v) / len(json_b) if json_b else None
    cost_c = [r.cost_usd for r in cand_runs if r.cost_usd is not None]
    cost_b = [r.cost_usd for r in base_runs if r.cost_usd is not None]
    cost_mean_c = sum(cost_c) / len(cost_c) if cost_c else None
    cost_mean_b = sum(cost_b) / len(cost_b) if cost_b else None
    cost_ratio = (cost_mean_c / cost_mean_b) if cost_mean_c is not None and cost_mean_b else None
    lat_c = percentile([r.latency_ms for r in cand_runs], 95) if cand_runs else math.nan
    lat_b = percentile([r.latency_ms for r in base_runs], 95) if base_runs else math.nan
    decision: Decision = "PASS"
    if n < cfg.min_cases:
        decision = "INSUFFICIENT_DATA"
        reasons.append(f"only {n} paired cases (need {cfg.min_cases})")
    else:
        if paired.low < -cfg.margin:
            decision = "FAIL"
            reasons.append(
                f"not non-inferior: delta {paired.delta:+.4f}, 95% CI "
                f"[{paired.low:+.4f}, {paired.high:+.4f}] crosses -{cfg.margin}"
            )
        if losses > wins and p_mcnemar < cfg.alpha:
            decision = "FAIL"
            reasons.append(
                f"McNemar: {losses} losses vs {wins} wins on pass/fail "
                f"(p={p_mcnemar:.4f} < {cfg.alpha})"
            )
        for s in slices:
            if not s.ok:
                decision = "FAIL"
                reasons.append(
                    f"slice {s.tag!r} regressed by {s.delta:+.4f} "
                    f"(n={s.n}, margin {cfg.slice_margin})"
                )
        if json_rate_c is not None and json_rate_c < cfg.json_validity_floor:
            decision = "FAIL"
            reasons.append(f"JSON validity {json_rate_c:.3f} below floor {cfg.json_validity_floor}")
        if cost_ratio is not None and cost_ratio > cfg.cost_budget_ratio:
            decision = "FAIL"
            reasons.append(
                f"cost per case x{cost_ratio:.2f} exceeds budget x{cfg.cost_budget_ratio}"
            )
        if cfg.latency_p95_budget_ms is not None and lat_c > cfg.latency_p95_budget_ms:
            decision = "FAIL"
            reasons.append(
                f"latency p95 {lat_c:.0f} ms exceeds budget {cfg.latency_p95_budget_ms:.0f} ms"
            )
        if (
            cfg.latency_budget_ratio is not None
            and lat_b > 0
            and lat_c / lat_b > cfg.latency_budget_ratio
        ):
            decision = "FAIL"
            reasons.append(
                f"latency p95 x{lat_c / lat_b:.2f} exceeds budget x{cfg.latency_budget_ratio}"
            )
        if decision == "PASS":
            reasons.append(
                f"non-inferior within margin {cfg.margin} (delta {paired.delta:+.4f}, "
                f"CI [{paired.low:+.4f}, {paired.high:+.4f}]); "
                "no slice, JSON, cost or latency breach"
            )
    judged = [r for r in cand_runs if r.judge_mean is not None or r.judge_missing]
    judge_info: dict[str, Any] = {}
    if cfg.use_judge:
        judge_info = {
            "used": True,
            "weight": cfg.judge_weight,
            "candidate_mean": _mean([r.judge_mean for r in cand_runs if r.judge_mean is not None]),
            "baseline_mean": _mean([r.judge_mean for r in base_runs if r.judge_mean is not None]),
            "missing_candidate": sum(1 for r in cand_runs if r.judge_missing),
            "missing_baseline": sum(1 for r in base_runs if r.judge_missing),
            "judged": len(judged),
        }
    return GateReport(
        dataset=dataset.manifest.name,
        dataset_version=dataset.manifest.version,
        dataset_hash=dataset.manifest.content_hash,
        candidate=cand_spec.ref,
        candidate_hash=cand_spec.content_hash,
        baseline=base_spec.ref,
        baseline_hash=base_spec.content_hash,
        model=model_name,
        n_cases=n,
        decision=decision,
        reasons=reasons,
        paired={
            "mean_candidate": round(sum(cand_scores) / n, 4) if n else None,
            "mean_baseline": round(sum(base_scores) / n, 4) if n else None,
            "delta": _r(paired.delta),
            "ci_low": _r(paired.low),
            "ci_high": _r(paired.high),
            "p_improve": _r(paired.p_improve),
            "wins": paired.wins,
            "losses": paired.losses,
            "ties": paired.ties,
            "margin": cfg.margin,
        },
        mcnemar={
            "pass_candidate": sum(1 for r in cand_runs if r.passed),
            "pass_baseline": sum(1 for r in base_runs if r.passed),
            "wins": wins,
            "losses": losses,
            "p_value": round(p_mcnemar, 4),
            "alpha": cfg.alpha,
        },
        slices=slices,
        json_validity={
            "candidate": _r(json_rate_c),
            "baseline": _r(json_rate_b),
            "n": len(json_c),
            "floor": cfg.json_validity_floor,
        },
        cost={
            "candidate_mean_usd": None if cost_mean_c is None else round(cost_mean_c, 6),
            "baseline_mean_usd": None if cost_mean_b is None else round(cost_mean_b, 6),
            "ratio": _r(cost_ratio),
            "budget_ratio": cfg.cost_budget_ratio,
            "candidate_completion_tokens": _mean(
                [float(r.completion_tokens) for r in cand_runs if r.completion_tokens is not None]
            ),
            "baseline_completion_tokens": _mean(
                [float(r.completion_tokens) for r in base_runs if r.completion_tokens is not None]
            ),
        },
        latency={
            "candidate_p95_ms": _r(lat_c, 1),
            "baseline_p95_ms": _r(lat_b, 1),
            "budget_ms": cfg.latency_p95_budget_ms,
            "budget_ratio": cfg.latency_budget_ratio,
        },
        judge=judge_info,
        config=cfg.model_dump(),
        candidate_runs=list(cand_runs),
        baseline_runs=list(base_runs),
    )


def _r(v: float | None, nd: int = 4) -> float | None:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return round(v, nd)


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def render_markdown(report: GateReport, *, max_rows: int = 40) -> str:
    p, m = report.paired, report.mcnemar
    lines = [
        f"# Prompt regression gate: {report.candidate} vs {report.baseline}",
        "",
        f"Dataset `{report.dataset}` v{report.dataset_version} "
        f"(hash `{report.dataset_hash}`), {report.n_cases} cases, model `{report.model}`. "
        f"Candidate hash `{report.candidate_hash}`, baseline hash `{report.baseline_hash}`.",
        "",
        f"## Decision: **{report.decision}**",
        "",
        *[f"- {r}" for r in report.reasons],
        "",
        "## Paired comparison (per-case quality score, candidate - baseline)",
        "",
        "| n | Candidate | Baseline | delta | 95% CI | P(delta>0) | wins / losses / ties "
        "| margin |",
        "|---:|---:|---:|---:|:---:|---:|---:|---:|",
        f"| {report.n_cases} | {p['mean_candidate']} | {p['mean_baseline']} | {p['delta']:+} | "
        f"[{p['ci_low']:+}, {p['ci_high']:+}] | {p['p_improve']} | "
        f"{p['wins']} / {p['losses']} / {p['ties']} | {p['margin']} |",
        "",
        "## Pass/fail (exact McNemar on discordant pairs)",
        "",
        "| Candidate pass | Baseline pass | Candidate-only pass | Baseline-only pass | p | alpha |",
        "|---:|---:|---:|---:|---:|---:|",
        f"| {m['pass_candidate']} | {m['pass_baseline']} | {m['wins']} | {m['losses']} | "
        f"{m['p_value']} | {m['alpha']} |",
        "",
        "## Slices",
        "",
        "| Slice | n | Baseline | Candidate | delta | OK |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for s in report.slices:
        lines.append(
            f"| {s.tag} | {s.n} | {s.baseline_mean:.3f} | {s.candidate_mean:.3f} | "
            f"{s.delta:+.3f} | {'yes' if s.ok else 'NO'} |"
        )
    j, c, lat = report.json_validity, report.cost, report.latency
    lines += [
        "",
        "## Budgets",
        "",
        "| Check | Candidate | Baseline | Budget |",
        "|---|---:|---:|---:|",
        f"| JSON validity (n={j['n']}) | {j['candidate']} | {j['baseline']} | >= {j['floor']} |",
        f"| Cost per case (USD) | {c['candidate_mean_usd']} | {c['baseline_mean_usd']} | "
        f"ratio <= {c['budget_ratio']} (observed {c['ratio']}) |",
        f"| Completion tokens (mean) | {c['candidate_completion_tokens']} | "
        f"{c['baseline_completion_tokens']} | - |",
        f"| Latency p95 (ms) | {lat['candidate_p95_ms']} | {lat['baseline_p95_ms']} | "
        f"{lat['budget_ms'] or lat['budget_ratio'] or 'none'} |",
    ]
    if report.judge:
        jd = report.judge
        lines += [
            "",
            f"Judge: candidate mean {jd['candidate_mean']}, baseline mean "
            f"{jd['baseline_mean']}, missing {jd['missing_candidate']} / "
            f"{jd['missing_baseline']} (weight {jd['weight']}).",
        ]
    lines += [
        "",
        "## Per-case (first rows)",
        "",
        "| Case | Tags | Baseline | Candidate | delta | Notes |",
        "|---|---|---:|---:|---:|---|",
    ]
    for cr, br in list(zip(report.candidate_runs, report.baseline_runs, strict=True))[:max_rows]:
        notes: list[str] = []
        if cr.ungrounded_numbers:
            notes.append("cand ungrounded " + ", ".join(cr.ungrounded_numbers[:2]))
        if br.ungrounded_numbers:
            notes.append("base ungrounded " + ", ".join(br.ungrounded_numbers[:2]))
        if cr.json_valid is False:
            notes.append("cand invalid JSON")
        if not cr.checks.get("no_refusal", True):
            notes.append("cand refused")
        if cr.error:
            notes.append(f"cand error {cr.error[:40]}")
        tags = ", ".join(t for t in cr.tags if not t.startswith("prompt:"))
        lines.append(
            f"| {cr.case_id} | {tags} | {br.quality:.3f} | {cr.quality:.3f} | "
            f"{cr.quality - br.quality:+.3f} | {'; '.join(notes)} |"
        )
    return "\n".join(lines) + "\n"
