# opsloop · the operations loop around an LLM application after it ships

Tracing for every model call, SLOs with multi-window burn-rate alerts **whose false-alarm rate
is measured**, text-input drift, a sampled LLM judge, user feedback, a curated and versioned
evaluation set grown from production, a prompt registry, a paired-statistics **prompt
regression gate** in CI, a prompt canary with automatic rollback, and deterministic **trace
replay** for root-cause analysis. The application it operates is a scripted "Northshore
Adviser Assistant" (adviser questions about clients' super, pension, fees, contributions,
insurance and reviews) with seeded failure injection, so the monitor can be scored against
planted incidents the way a classifier is scored against labels.

| | |
|---|---|
| Quality gates | `ruff`, `mypy --strict` (src + tests), **165 tests** (offline, CPU, ≈ 15 s), **98 % branch coverage** |
| Headline | Monitor self-evaluation over 7 scenarios × 3 seeds × 4 simulated hours: **all six incident kinds detected in every run** (time-to-detect 5 min for error bursts, PII leaks and the regressed prompt; 8 min cost creep; 13 min latency spike and topic shift) with a **false-alarm rate of 0.2 % [0, 0.7 %] on 459 quiet evaluations**. Full tables in [docs/RESULTS.md](docs/RESULTS.md) |
| Regression gate | v1 → v2 **PASS** (paired Δ +0.022 [+0.007, +0.038], 18 wins / 0 losses on pass–fail, fees slice +0.20, reviews slice −0.10 reported inside the slice margin); v1 → v2-regressed **FAIL** (Δ −0.304 [−0.331, −0.277], McNemar p < 10⁻⁴, 25 slices regressed, JSON validity 0/8) |
| Canary | v2 advances 10 → 50 → 100 % and is promoted; v2-regressed rolls back at 10 % (refusal rate +12 pp, p < 10⁻⁴; quality Δ −0.22 [−0.24, −0.20]) |
| Real model (Qwen3-4B-Instruct-2507 answering *and* judging, 80 cases, one RTX 4070) | v1 → v2 is non-inferior (Δ +0.009 [−0.000, +0.020], every slice OK) and the gate **still refuses**: both prompts fail the JSON-validity floor on the two cases that require JSON (0 / 2) — an instruction-following defect only a real model exposes; v1 → v2-regressed **FAIL** on McNemar (14 losses / 3 wins, p = 0.013) with an effect a tenth of the scripted one; the judge scored 60 production traces with 0 missing (grounding 4.73 / 5); replay reproduced the prompt hash and the fee total ([RESULTS §8](docs/RESULTS.md#8-real-model-stage--qwen3-4b-instruct-2507-answering-and-judging)) |
| Stack | SDK → SQLite / HTTP collector / OTLP JSON · FastAPI collector · Prometheus rules · Grafana dashboard · `docker compose` — brought up on Docker Desktop, 1 797 traces posted over HTTP, `SloBurnCritical{name="error_rate"}` **firing** in Prometheus, dashboard provisioned ([RESULTS §7](docs/RESULTS.md#7-compose-stack-verified-end-to-end-2026-09-06)) |

**Related projects.** [`llm-gateway-release`](https://github.com/RiverHe2000/genai-platform-lab)
(genai-platform-lab) promotes a *model* behind an endpoint with an eval-gated, paired-statistics
decision; [`model-monitoring-drift`](https://github.com/RiverHe2000/mlops-lab) (mlops-lab)
monitors a *tabular* model's inputs and performance with a calibrated alert policy. This project
sits one layer up: the unit of change is the *prompt and application version*, the evidence is
*production traces and human feedback*, and the loop closes by turning those into a versioned
evaluation set that gates the next prompt. Sibling projects: [`../advice-doc-intelligence`](../advice-doc-intelligence)
and [`../file-note-copilot`](../file-note-copilot) are the kind of application this loop operates.

---

## 1. Architecture

```
 adviser question ──► demo app (guardrail span · tool spans · llm span) ──► answer
                          │  Tracer: cost (missing ≠ 0) · PII redaction with counts · sampling (keep errors)
                          ▼
                    exporter: StoreExporter (SQLite) │ HttpExporter (POST /v1/traces) │ JSONL / OTLP gen_ai.*
                          ▼
              collector / store ── heuristic scorers at ingest (refusal · PII · numeric grounding · JSON · tone)
                 │            │
                 │            ├─ monitor: SLO bad-fractions ─► burn rate on 10/2 · 30/5 · 120/15 min windows
                 │            │           + min bad events + consecutive escalation; topic drift (k-means +
                 │            │           novelty bucket, chi-square ∧ JS bootstrap, novel-share binomial)
                 │            │           ─► Alert(name, severity, window, value, threshold, evidence) ─► /metrics
                 │            ├─ feedback: thumbs · regenerate · edit distance ─► negative flag, promotes sampled-out traces
                 │            └─ sample (errors, negative feedback, low score, random) ─► judge (1–5 rubric, JSON repair, missing on failure)
                 ▼
     review queue ─► curated cases (input, tool-output context, expected properties, provenance)
                 ─► versioned JSONL dataset (content hash, changelog, near-dup rejection, slices)
                 ─► regression gate: paired bootstrap + McNemar + slices + JSON floor + cost/latency ─► exit code
                 ─► canary 10 → 50 → 100 %: two-proportion tests + quality bootstrap ─► advance / rollback
     incident: replay (rebuild prompt, stub tools, diff, re-score) · report (classify, aggregate, elevated period)
```

| Component | File(s) | Notes |
|---|---|---|
| Tracing SDK | `sdk/tracing.py`, `sdk/pricing.py`, `sdk/otlp.py`, `sdk/exporters.py`, `pii.py` | `with tracer.trace(...) as t: with t.span("tool", ...)`; decorator for plain functions; thread-safe; never raises into the app (failures counted in `tracer.stats`); deterministic span ids; unknown model ⇒ cost *missing*; TFN (mod-11) / ABN (mod-89) / email / phone redaction with per-trace counts; head sampling keeps errors and can promote a retained trace on negative feedback; OTLP-style JSON with `gen_ai.*` names |
| Store + collector | `store.py`, `collector/api.py` | SQLite (traces with denormalised signals, spans, feedback, scores; indexes on time / status / prompt version / session); `POST /v1/traces`, `GET /v1/traces[/{id}]`, `GET /v1/stats?window=`, `POST /v1/feedback`, `/metrics`, `/health`; `opsloop store prune --older-than 30d`, `store export` |
| Demo app | `demo/book.py`, `demo/tools.py`, `demo/questions.py`, `demo/model.py`, `demo/app.py`, `demo/traffic.py`, `scenarios/*.yaml` | seeded client book; five tools that compute every derived figure; 42 in-scope + 6 out-of-scope question templates; a fake model that obeys prompt directives (so prompt changes change behaviour and replay reproduces answers) with seeded corruption; scenario YAML with planted incidents; Poisson traffic in simulated time (no sleeping), byte-identical for a seed |
| Monitor | `monitor/config.py`, `slo.py`, `alerts.py`, `drift.py`, `core.py`, `evaluate.py`, `exporter.py`, `slos/default.yaml` | every SLO is "≤ budget of eligible requests bad"; three burn windows that must both burn, minimum bad events, windows evaluated only when full, warning → critical after 2 ticks; refusal-rate band floor; drift = hashing embedder + k-means fitted on half the baseline, novelty bucket calibrated on the other half (distance radius ∨ out-of-vocabulary share), two-sample χ² ∧ JS > bootstrap threshold, or a one-sided binomial test on the novel share; self-evaluation with TTD / detection / false alarms and bootstrap CIs; Prometheus gauges |
| Quality | `quality/scorers.py`, `sampling.py`, `judge.py`, `pipeline.py`, `feedback.py` | heuristics run on every trace at ingest; stratified or uniform sampling with a budget; rubric judge (`fake` / `openai` / `hf`) with JSON repair, bounded retries, *missing* on failure, judge model + prompt version stored; judge scores from failure-targeted samples are kept out of the SLO |
| Dataset + prompts | `dataset/curate.py`, `dataset/versioning.py`, `prompts/registry.py`, `prompts/*.yaml`, `prompts/releases.yaml` | review queue → `CuratedCase` with expected properties and provenance; immutable versions with content hash, parent hash, changelog, rapidfuzz near-duplicate rejection, tag slices, `diff`; prompts as YAML with Jinja2 `StrictUndefined`, content hash as version id, `lint` (undeclared placeholders, token budget, forbidden phrases), `diff`, `render` |
| Regression gate | `regression/gate.py` | same model, same cases: paired bootstrap with non-inferiority margin, exact McNemar on pass/fail, per-slice non-regression, JSON floor, cost and latency budgets, INSUFFICIENT_DATA; markdown + JSON report; exit code |
| Canary | `release/canary.py` | SHA-256 session bucketing; stages from `releases.yaml`; two-proportion tests (error, refusal) and bootstrap on quality mean with a minimum cohort size; `release status / start / advance / rollback / auto` |
| Replay + incident | `replay.py`, `incident.py`, `docs/RUNBOOK.md` | replay rebuilds the exact prompt from the trace and stubs tools with recorded outputs; report classifies failures (timeout, provider error, tool error, invalid JSON, guardrail block, PII, ungrounded, refusal, low judge score, negative feedback), aggregates by prompt version / tool / topic / bucket, finds the elevated period and its z-score, drafts cause, evidence and follow-ups |
| CLI | `cli.py` | `demo traffic`, `serve`, `monitor evaluate|run|export`, `sample`, `judge`, `feedback add`, `curate`, `dataset build|list|diff`, `prompt register|list|diff|render|lint`, `regress`, `release …`, `replay`, `incident report`, `store prune|export`; `--gate` where a decision exists |
| Deploy | `deploy/` | Dockerfile (collector), `docker-compose.yml` (collector + Prometheus + Grafana), `prometheus/rules.yml` (7 rules, `promtool` clean), provisioned Grafana dashboard |

---

## 2. Results

All numbers come from `bash scripts/run_experiments.sh` (CPU stage, ≈ 3 min) and live in
[docs/experiments/](docs/experiments/); the full write-up is [docs/RESULTS.md](docs/RESULTS.md).

**Monitor self-evaluation** ([monitor_evaluation.md](docs/experiments/monitor_evaluation.md)) —
7 scenarios × seeds 1–3 × 240 simulated minutes (≈ 1 200 requests each), policy
[`slos/default.yaml`](slos/default.yaml), evaluation every 5 minutes:

| Incident kind (planted) | Detected | Time-to-detect, min (values) | First alert |
|---|---:|---|---|
| error_burst (25 % timeouts / 5xx + flaky tool, 30 min) | 3 / 3 | 5.0 (5, 5, 5) | `error_rate` |
| pii_leak (tool exposes a TFN, model echoes it, 40 min) | 3 / 3 | 5.0 (5, 5, 5) | `pii_leak_rate` |
| regressed_prompt (v2-regressed live for 60 min) | 3 / 3 | 6.7 (5, 10, 5) | `grounding_rate` / `quality_mean` |
| cost_creep (completion tokens × 4–5, 90 min) | 3 / 3 | 8.3 (10, 10, 5) | `cost_per_request` |
| latency_spike (LLM latency × 2, 40 min) | 3 / 3 | 13.3 (10, 10, 20) | `latency_p95` |
| topic_shift (35 % out-of-scope questions from minute 120) | 3 / 3 | 13.3 (15, 20, 5) | `topic_drift` |
| **False alarms on quiet ticks** | **1 / 459 = 0.22 % [0, 0.66 %]** | | (`topic_drift`, once) |

**Prompt regression gate** (fake model + fake judge, dataset `adviser_assistant` v2 = 205
curated cases from production traces, [good](docs/experiments/regression_gate_v2_good.md) /
[bad](docs/experiments/regression_gate_v2_regressed_bad.md)):

| Candidate vs v1 | Δ quality [95 % CI] | pass / fail wins–losses (McNemar p) | Slices | JSON validity | Cost ratio | Decision |
|---|---|---|---|---|---|---|
| v2 | +0.022 [+0.007, +0.038] | 18 – 0 (p ≈ 0) | fees +0.20, reviews −0.10 (inside 0.15 margin) | 8/8 | 1.09 | **PASS** |
| v2-regressed | −0.304 [−0.331, −0.277] | 0 – 123 (p < 10⁻⁴) | 25 of 34 regressed | 0/8 | 0.94 | **FAIL** |

**Canary** ([canary_*.json](docs/experiments/)): v2 at 10 % (174 canary / 2 265 control
requests) → advance; at 50 % (1 027 / 1 402) → advance; at 100 % against the historical
control → promote. v2-regressed at 10 % (188 / 2 161): refusal rate 15.4 % vs 3.2 %
(+12.2 pp, z = 8.0), quality mean 0.755 vs 0.971 (Δ −0.22 [−0.24, −0.20]) → **rollback**.

**Replay and incident report**: replaying a v1 trace with the fake model reproduces the
recorded answer exactly ([replay_same_prompt.md](docs/experiments/replay_same_prompt.md));
replaying it with v2 turns "about 1.5 %" into "1.49 %" and grounding false → true
([replay_with_v2.md](docs/experiments/replay_with_v2.md)). The error-burst incident report
([incident_report_error_burst.md](docs/experiments/incident_report_error_burst.md)) finds the
elevated period 01:30–02:10 (failure rate 33.9 % vs 10.5 % outside, z = 7.0), names provider
availability as the cause (availability failures 0.2 % → 20.3 % of requests) and lists the tool
span errors and example traces.

---

## 3. Quick start

```bash
python -m venv .venv && source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"                                   # [serve] for the collector, [hf] for local models

# four simulated hours of adviser traffic with a planted error burst, into a SQLite store
opsloop --store runs/demo.sqlite demo traffic --scenario scenarios/error_burst.yaml --minutes 240 --seed 3 --reset
opsloop --store runs/demo.sqlite monitor run --out runs/monitor          # SLO evaluation per 5-min tick, exit 3 = critical
opsloop --store runs/demo.sqlite incident report --window 2h --out runs/incident.md

# measure the monitor itself (the CI gate)
opsloop monitor evaluate --scenarios scenarios/*.yaml --seeds 1 2 3 --minutes 240 --out runs/eval --gate

# quality loop: sample -> judge -> review queue -> versioned dataset -> regression gate
opsloop --store runs/demo.sqlite sample --strategy uniform --budget 120 --out runs/sample.json
opsloop --store runs/demo.sqlite judge --sample runs/sample.json --model fake
opsloop --store runs/demo.sqlite curate --sample runs/sample.json --reviewer you --accept-all --out runs/review.jsonl
opsloop dataset build --from-review runs/review.jsonl --name adviser_assistant
opsloop regress --dataset adviser_assistant --candidate @v2 --baseline @v1 --model fake --out runs/gate --gate

# prompt canary with automatic rollback
opsloop release start --version v2 --stage 10
opsloop --store runs/canary.sqlite demo traffic --scenario scenarios/canary_good.yaml --minutes 480 --use-release --reset
opsloop --store runs/canary.sqlite release auto --window 8h --apply     # exit 0 advance/promote, 2 hold, 3 rollback

# replay a trace with the recorded prompt, or with another prompt version
opsloop --store runs/demo.sqlite replay <trace_id> --model fake --prompt-version v2 --out runs/replay.md

# collector + Prometheus + Grafana
docker compose -f deploy/docker-compose.yml up --build --wait
opsloop --store runs/http.sqlite demo traffic --scenario scenarios/error_burst.yaml --collector-url http://localhost:8090 --reset

make all      # ruff + mypy --strict + pytest
make results  # regenerate docs/experiments (CPU stage); STAGE=gpu MODEL=... for the real-model stage
```

Every model-facing command takes `--model {fake,openai,hf}` (`--base-url` for vLLM / Ollama /
Azure / the owner's gateway, a hub id or local directory for `hf`); paths and defaults are also
environment variables (`OPSLOOP_STORE_PATH`, `OPSLOOP_MODEL__KIND=openai`).

---

## 4. Design decisions

* **The monitor is validated like a model.** Planted incidents are labels; `opsloop monitor
  evaluate` is the confusion matrix (time-to-detect, detection, false alarms with bootstrap
  intervals) and it is the CI gate for any threshold change. Three false-alarm sources were
  found and removed this way, not by eye: windows evaluated before they were full, a 1 % budget
  paging on two Poisson errors (hence a minimum bad-event count), and a rate floor on a short
  window.
* **One SLO mechanism.** Every objective is a bad-event fraction against a budget, so "p95
  latency ≤ 2.5 s", "error rate ≤ 1 %", "JSON validity" and "no PII" share one burn-rate rule
  with multi-window confirmation and escalation. Latency counts successful requests only.
* **Drift needs a novelty bucket.** k-means on the baseline absorbs unseen question types into
  existing clusters; a request far from every centroid or built from out-of-vocabulary tokens
  goes to an extra topic, and a one-sided binomial test on that topic's share is the targeted
  detector. Both the radius and the reference mix are calibrated on a held-out half of the
  baseline.
* **Cost is never zero by accident.** An unknown model marks the cost missing; the SLO skips it
  and the exporter counts it.
* **Redact, but keep the count.** The store never holds a TFN; the trace records that one was
  there, which is what the PII SLO reads.
* **Grounding is the cheapest hallucination detector.** Every number in an answer must exist in
  a tool output; the demo's tools therefore compute every derived figure and a parametrized test
  proves all 42 templates are grounded. What grounding cannot see (a right number in the wrong
  place) is the judge's job.
* **Selection bias is a real bug.** Judge scores from a failure-targeted sample are stored for
  audit but excluded from the judged-quality SLO; the first smoke run alerted on exactly that.
* **A statistical decision with an exit code.** The regression gate and the canary both produce
  a report a reviewer can read and a code a pipeline can act on; slices have a wider margin
  than the whole set because they are small, and the deliberate trade-off (terser review
  answers) stays visible in the report.

Interview preparation notes: [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md). Alert
handling: [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## 5. Limitations (honest list)

* The traffic, the incidents and the model are simulated. That is what makes the detection and
  false-alarm numbers possible, and it is also their limit: on real traffic the thresholds would
  be re-validated by replaying history through `monitor evaluate`.
* The fake model's behaviour is a caricature (it obeys a handful of prompt directives); the
  judge agrees with the heuristics by construction. The real-model stage (RESULTS §8) showed
  the consequence: a scripted regression of −0.30 was −0.03 with a real model, and the good
  prompt failed the gate on an instruction-following defect the fake could not have.
* Real-model numbers come from 80 of the 205 curated cases on one consumer GPU (a budget,
  not a sampling design); the cost column is *missing* for a local model rather than zero.
* Head-based sampling with a retention buffer is a bounded answer to late feedback; tail-based
  sampling at a real collector is the proper one.
* Session bucketing at 10 % is coarse: the canary needs about eight simulated hours to reach its
  minimum cohort, and the 100 % stage compares against a historical control.
* The drift baseline is the first hour of a run; production would pin a reviewed week. The
  hashing embedder is deterministic and dependency-free; `sentence-transformers` is optional
  and untested here.
* SQLite and an in-process collector: fine for a team's assistant, not for a platform's traffic.

---

## 6. Layout

```
src/opsloop/
├── sdk/           tracing.py (Tracer, spans, sampling, redaction), pricing.py, otlp.py, exporters.py, models.py
├── collector/     api.py (FastAPI ingest / query / feedback / metrics)
├── demo/          book.py, tools.py, questions.py, model.py, app.py, scenario.py, traffic.py
├── monitor/       config.py, slo.py, alerts.py, drift.py, core.py, evaluate.py, exporter.py
├── quality/       scorers.py, sampling.py, judge.py, pipeline.py
├── dataset/       curate.py, versioning.py
├── prompts/       registry.py
├── regression/    gate.py
├── release/       canary.py
└── store.py, feedback.py, replay.py, incident.py, llm.py, pii.py, jsonrepair.py, stats.py, timeutil.py, config.py, cli.py
prompts/           adviser_assistant/{v1,v2,v2-regressed}.yaml, releases.yaml
scenarios/         steady, latency_spike, error_burst, regressed_prompt, topic_shift, cost_creep, pii_leak, canary_good, canary_bad
slos/              default.yaml
deploy/            Dockerfile, docker-compose.yml, prometheus/{prometheus,rules}.yml, grafana/
docs/              RESULTS.md, INTERVIEW_NOTES.md, RUNBOOK.md, experiments/
tests/             165 tests: SDK, primitives, store + collector, demo, quality, monitor, datasets + prompts, gate + canary, replay + incident, CLI, template invariants
../.github/workflows/  llm-app-ops-loop-ci.yml (path-filtered; lint → types → tests → prompt lint, monitor and regression gates)
```
