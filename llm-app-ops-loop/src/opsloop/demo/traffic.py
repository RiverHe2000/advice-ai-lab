"""Seeded demo traffic in simulated time: a Poisson arrival process over sessions, questions
from the sampler, failure injection from the scenario's active incidents, simulated user
feedback, and canary assignment when the scenario (or a release) carries one."""

from __future__ import annotations

import random
import uuid
from dataclasses import dataclass, field
from typing import Any

from opsloop.demo.app import AdviserAssistant, Faults
from opsloop.demo.book import ClientBook
from opsloop.demo.model import Corruption, DemoFakeModel
from opsloop.demo.questions import Question, QuestionSampler
from opsloop.demo.scenario import Incident, Scenario
from opsloop.feedback import add_feedback, build_feedback
from opsloop.llm import ChatModel
from opsloop.prompts.registry import PromptRegistry
from opsloop.quality.pipeline import ingest_trace
from opsloop.quality.scorers import HeuristicScores
from opsloop.release.canary import CanaryState, PromptRelease, resolve_version
from opsloop.sdk.models import Trace
from opsloop.sdk.tracing import Tracer
from opsloop.store import TraceStore
from opsloop.timeutil import DEMO_EPOCH, SimClock

_NAMESPACE = uuid.UUID("2f4d1b1e-7c3a-4a8e-9b1a-3c0f1e6d2a55")


@dataclass
class TrafficSummary:
    scenario: str
    seed: int
    start_ts: float
    end_ts: float
    minutes: float
    n_requests: int = 0
    n_errors: int = 0
    n_refusals: int = 0
    n_blocked: int = 0
    n_negative_feedback: int = 0
    n_feedback: int = 0
    by_prompt_version: dict[str, int] = field(default_factory=dict)
    by_incident: dict[str, int] = field(default_factory=dict)
    tracer_stats: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class _CapturingExporter:
    """Ingest into the store and remember the heuristic scores of the last trace, so the
    traffic loop can simulate feedback that depends on answer quality."""

    def __init__(self, store: TraceStore) -> None:
        self.store = store
        self.last: HeuristicScores | None = None
        self.last_trace: Trace | None = None

    def __call__(self, trace: Trace) -> None:
        self.last_trace = trace
        self.last = ingest_trace(self.store, trace)


def faults_from(incidents: list[Incident]) -> Faults:
    faults = Faults()
    corruption = Corruption()
    for inc in incidents:
        p = inc.params
        if inc.kind == "latency_spike":
            faults.llm_latency_multiplier *= float(p["multiplier"])
        elif inc.kind == "error_burst":
            faults.error_rate = max(faults.error_rate, float(p["error_rate"]))
            faults.error_kinds = tuple(str(k) for k in p["kinds"])
            faults.tool_error_rate = max(
                faults.tool_error_rate, float(p.get("tool_error_rate", 0.0))
            )
        elif inc.kind == "cost_creep":
            corruption.verbosity = max(corruption.verbosity, float(p["verbosity"]))
        elif inc.kind == "pii_leak":
            faults.leak_tfn = True
        if "ungrounded_rate" in p:
            corruption.ungrounded_rate = max(
                corruption.ungrounded_rate, float(p["ungrounded_rate"])
            )
        if "refusal_rate" in p:
            corruption.refusal_rate = max(corruption.refusal_rate, float(p["refusal_rate"]))
        if "invalid_json_rate" in p:
            corruption.invalid_json_rate = max(
                corruption.invalid_json_rate, float(p["invalid_json_rate"])
            )
    faults.corruption = corruption
    return faults


def prompt_version_for(
    scenario: Scenario, incidents: list[Incident], session_id: str, release: PromptRelease | None
) -> str:
    for inc in incidents:
        if inc.kind == "regressed_prompt":
            return str(inc.params["version"])
    if release is not None:
        return resolve_version(release, session_id)
    if scenario.canary is not None:
        rel = PromptRelease(
            active=scenario.active_version,
            canary=CanaryState(version=scenario.canary.version, stage=scenario.canary.stage),
        )
        return resolve_version(rel, session_id)
    return scenario.active_version


def _simulate_feedback(
    rng: random.Random, scores: HeuristicScores | None, answer: str, *, blocked: bool
) -> dict[str, Any] | None:
    if scores is None or blocked:
        return None
    if scores.refusal:
        p_neg, part = 0.35, "refusal"
    elif not scores.grounded:
        p_neg, part = 0.25, "numbers"
    elif scores.pii_leak or scores.json_valid is False:
        p_neg, part = 0.30, "format"
    else:
        p_neg, part = 0.02, "other"
    u = rng.random()
    if u < p_neg:
        mode = rng.random()
        if mode < 0.5:
            return {"thumbs": "down", "wrong_part": part}
        if mode < 0.8:
            return {"regenerated": True}
        edited = "Corrected: " + answer[: max(len(answer) // 3, 1)]
        return {"edited_text": edited}
    if u < p_neg + 0.08:
        return {"thumbs": "up"}
    return None


def run_traffic(
    scenario: Scenario,
    *,
    seed: int,
    minutes: float,
    store: TraceStore,
    registry: PromptRegistry,
    start_ts: float = DEMO_EPOCH,
    model: ChatModel | None = None,
    book: ClientBook | None = None,
    release: PromptRelease | None = None,
    sample_rate: float | None = None,
) -> TrafficSummary:
    rng = random.Random(f"{scenario.name}:{seed}")
    spec = scenario.traffic
    book = book or ClientBook.generate(seed=spec.book_seed, n_clients=spec.clients)
    clock = SimClock(start_ts)
    sink = _CapturingExporter(store)
    tracer = Tracer(
        sink,
        clock=clock.now,
        sample_rate=spec.sample_rate if sample_rate is None else sample_rate,
        app_version="1.4.0",
    )
    fake = model or DemoFakeModel(seed=seed)
    app = AdviserAssistant(book, registry, tracer, clock, fake)
    sampler = QuestionSampler(book, rng)
    sessions = [f"s{seed}-{k:03d}" for k in range(spec.sessions)]
    end_ts = start_ts + minutes * 60.0
    summary = TrafficSummary(scenario.name, seed, start_ts, end_ts, minutes)
    t = start_ts + rng.expovariate(spec.rate_per_minute / 60.0)
    i = 0
    while t < end_ts:
        minute = (t - start_ts) / 60.0
        incidents = scenario.active_incidents(minute)
        faults = faults_from(incidents)
        faults.error_rate = max(faults.error_rate, spec.base_error_rate)
        share = spec.out_of_scope_share
        for inc in incidents:
            if inc.kind == "topic_shift":
                share = float(inc.params["share"])
        question = sampler.sample(out_of_scope_share=share)
        if spec.tfn_in_question_rate > 0 and rng.random() < spec.tfn_in_question_rate:
            client = book.get(question.client_id)
            question = Question(
                question.type, question.client_id, f"{question.text} (TFN {client.tfn})"
            )
        session_id = rng.choice(sessions)
        version = prompt_version_for(scenario, incidents, session_id, release)
        clock.set(t)
        trace_id = uuid.uuid5(_NAMESPACE, f"{scenario.name}:{seed}:{i}").hex
        result = app.handle(
            question,
            session_id=session_id,
            request_id=f"req-{seed}-{i:05d}",
            prompt_version=version,
            rng=rng,
            faults=faults,
            trace_id=trace_id,
        )
        summary.n_requests += 1
        summary.by_prompt_version[version] = summary.by_prompt_version.get(version, 0) + 1
        for inc in incidents:
            summary.by_incident[inc.kind] = summary.by_incident.get(inc.kind, 0) + 1
        if result.status == "error":
            summary.n_errors += 1
        scores = (
            sink.last
            if sink.last_trace is not None and sink.last_trace.trace_id == trace_id
            else None
        )
        blocked = sink.last_trace is not None and bool(
            sink.last_trace.attributes.get("guardrail.blocked")
        )
        if blocked:
            summary.n_blocked += 1
        if scores is not None and scores.refusal:
            summary.n_refusals += 1
        if spec.feedback and result.status == "ok":
            fb = _simulate_feedback(rng, scores, result.answer, blocked=blocked)
            if fb is not None:
                feedback = build_feedback(
                    trace_id,
                    ts=clock.now() + rng.uniform(5.0, 90.0),
                    thumbs=fb.get("thumbs"),
                    wrong_part=fb.get("wrong_part"),
                    regenerated=bool(fb.get("regenerated", False)),
                    original_text=result.answer if "edited_text" in fb else None,
                    edited_text=fb.get("edited_text"),
                )
                add_feedback(store, feedback, tracer=tracer)
                summary.n_feedback += 1
                if feedback.negative:
                    summary.n_negative_feedback += 1
        i += 1
        t += rng.expovariate(spec.rate_per_minute / 60.0)
    summary.tracer_stats = tracer.stats.as_dict()
    return summary
