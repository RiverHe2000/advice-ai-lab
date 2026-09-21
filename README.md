# advice-ai-lab

[![advice-doc-intelligence](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/advice-doc-intelligence-ci.yml/badge.svg)](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/advice-doc-intelligence-ci.yml)
[![file-note-copilot](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/file-note-copilot-ci.yml/badge.svg)](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/file-note-copilot-ci.yml)
[![llm-app-ops-loop](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/llm-app-ops-loop-ci.yml/badge.svg)](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/llm-app-ops-loop-ci.yml)

Three AI applications for a financial-advice platform, built the way an incubator team would
have to ship them — **read the paperwork, draft the adviser's note, run the app in
production**: a document-intelligence pipeline that turns Statements of Advice into typed
records with a measured error rate and a human-review router, a file-note copilot whose
every claim carries transcript evidence and whose output an adviser must approve, and the
operations loop that keeps an LLM application healthy after launch — traces, SLOs, feedback,
a curated evaluation set, a prompt regression gate, a canary and replay.

| # | Project | What it demonstrates | Headline result |
|---|---|---|---|
| 01 | [advice-doc-intelligence](advice-doc-intelligence/) — `advicedoc` | 660 synthetic PDFs of ten advice-document types with gold labels; calibrated TF-IDF classifier with abstention; `rules` / `llm` / `llm_validated` SoA extraction behind one protocol; deterministic validators with targeted re-asks; a **calibrated review router** (selective prediction, risk-coverage curve); advice-vs-implementation reconciliation against planted discrepancies; durable SQLite workflow + FastAPI | Classifier **macro-F1 1.000** (0.958 at 10 % OCR-like noise), isotonic **ECE 0.001**; rules extractor 120/120 SoAs exact; validators lift a corrupted extraction 0.358 → 0.508 doc accuracy (McNemar p < 0.001); reconciliation **57/57 planted discrepancies** found at a measured 13 % false-alarm rate; **121 tests, 98 % coverage** |
| 02 | [file-note-copilot](file-note-copilot/) — `filenote` | Meeting transcript → structured file note with **segment-level evidence on every claim**; a model-free verifier (figures, dates, decision-vs-deferral language, owners, small talk) measured on planted hallucinations; pseudonymisation before the model; vanilla **HTML/CSS/JS** two-pane UI with SSE streaming and an approval rule enforced server-side; Playwright browser tests; Dockerfile + **Terraform for Cloud Run** with Workload Identity Federation | Verifier: **95–100 % of planted hallucinations caught per kind, 0 % false alarms** on 1 669 gold claims; the verified strategy surfaces **100 % of the hallucinations** a corrupting model leaves in a note; Terraform validated; **202 tests, 98 % coverage** |
| 03 | [llm-app-ops-loop](llm-app-ops-loop/) — `opsloop` | Tracing SDK (OTel `gen_ai.*` naming, cost, redaction, error-keeping sampling) → collector → **multi-window burn-rate SLO alerts** + text-input drift, measured on planted incidents; judge sampling and feedback → **versioned curated datasets** → prompt registry → **paired-statistics regression gate** → prompt canary with automatic rollback → trace replay and incident reports; Prometheus rules + Grafana, compose stack run for real | Monitor: **every incident kind detected** (time-to-detect 5–13 min), **0.22 % false alarms** over 459 quiet ticks; regression gate passes the good prompt (Δ +0.022 [+0.007, +0.038]) and fails the regressed one (McNemar p < 10⁻⁴); canary rolls the bad prompt back at 10 % traffic; **165 tests, 98 % coverage** |

Real-model results (Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct on one RTX 4070, greedy)
are in each project's `docs/RESULTS.md`; the short version:

| Project | With Qwen3-4B-Instruct-2507 (open-source, runs on a 12 GB card) | What it changed |
|---|---|---|
| `advicedoc` | Zero-shot classification 1.000 (ties the 1 ms ML model); SoA extraction field accuracy **0.945**, every scalar field exact, failures only on a boolean and the replacement list; the calibrated router reviews **27.5 %** of documents for **0 % residual error** (ECE 0.002) where a validator-only policy leaves 25.6 % wrong. The 1.5 B model: 0 / 40 documents correct | The errors a 4 B model makes are exactly the ones deterministic validators cannot see — which is the argument for the router |
| `filenote` | One-pass draft macro F1 **0.545**; verification on top of it is non-inferior on F1 and lowers hallucination 17.1 % → 14.7 % (paired, p = 0.031) with **every surviving hallucination flagged**; the two-pass draft is **worse** (−0.11 macro F1) and collapses on the 1.5 B model; **pseudonymising names costs 0.065 macro F1** [0.013, 0.118] | Two design assumptions the scripted checks had passed were overturned by the real model, and both are written up as negative results |
| `opsloop` | Regression gate with the real model answering *and* judging on 80 curated cases: v2 is non-inferior to v1 (paired Δ +0.009 [−0.000, +0.020], every slice OK) yet the gate **refuses to promote** — both prompts fail the JSON-validity floor on the two cases that require JSON (0 / 2), an instruction-following defect only a real model exposes; v2-regressed fails on McNemar (14 losses / 3 wins, p = 0.013) with a real effect a tenth of what the scripted model suggested; the judge scored 60 production traces with 0 missing (grounding mean 4.73 / 5); replay reproduced the prompt hash and the fee total | The scripted model overstates regressions and cannot see instruction-following failures; the gate's floor and paired tests behaved correctly on both |

Companion repositories: [`llm-engineering-lab`](https://github.com/RiverHe2000/llm-engineering-lab)
(Transformer internals, LoRA, an inference server), [`genai-platform-lab`](https://github.com/RiverHe2000/genai-platform-lab)
(RAG, an agent with guardrails, an LLM gateway) and [`mlops-lab`](https://github.com/RiverHe2000/mlops-lab)
(MLflow lifecycle, SageMaker deployment, drift monitoring). This repository is the
*application* layer those three sit under; [docs/DESIGN.md](docs/DESIGN.md) records the gap
analysis and the design choices.

---

## The through-line

The three answer the three questions a wealth platform's AI team is actually asked:

1. **"Can we trust what the model read?"** (`advicedoc`) — a classical classifier with a
   calibrated abstain threshold, an extractor whose every field is validated, and a router
   that sends a document to a human when its calibrated P(correct) is below a threshold chosen
   for a target residual error. The trade-off is a risk-coverage curve, not a promise.
2. **"Can an adviser sign what the model wrote?"** (`filenote`) — every claim cites transcript
   segments, an independent verifier scores each one, unsupported claims are shown rather than
   hidden, and the approve button is refused server-side until the adviser has resolved them.
3. **"How do we know it still works next month?"** (`opsloop`) — traces with cost and
   quality signals, burn-rate alerts with a measured false-alarm rate, production cases curated
   into a versioned eval set, and a gate that a new prompt has to pass before a canary sees it.

Everything is measured against synthetic data with a known truth — gold extractions, gold
notes, planted hallucinations, planted incidents — so each detector reports a detection
rate *and* a false-alarm rate, and every headline number carries a bootstrap interval.

---

## Engineering standard (identical across the three)

| Gate | Tooling |
|---|---|
| Lint + format | `ruff` (E, F, W, I, N, UP, B, SIM, C4, PT, RUF, PIE, RET, ARG, ASYNC), pinned |
| Types | `mypy --strict` on `src/` **and** `tests/`, pinned |
| Tests | `pytest`, **488 tests**, branch-coverage gates ≥ 90 % (measured 98 % on all three), offline on CPU in ≈ 15 s each; scripted models with configurable corruption stand in for real ones |
| Determinism | seeded corpora (byte-identical on re-run), seeded simulators, content-addressed response cache for real-model runs |
| CI | one path-filtered workflow per project on Python 3.12/3.13, `HF_HUB_OFFLINE=1`; each runs that project's own deterministic release gate (classifier + rules-extractor gate, verifier + drafting gate, monitor + prompt-regression gate); the file-note workflow also runs the Playwright browser tests, builds the image and validates the Terraform |
| Statistics | bootstrap CIs, paired bootstrap with non-inferiority margins, exact McNemar, ECE with reliability tables |

```bash
python -m venv .venv && source .venv/bin/activate
make install                                  # editable install of all three, dev extras
make all                                      # ruff + mypy + pytest for all three (what CI runs)
make PROJECT=file-note-copilot test
```

Real-model stages need `pip install torch` (CUDA wheel) and either a local Hugging Face
model directory or any OpenAI-compatible endpoint; each project's `scripts/run_experiments.sh`
documents its `MODEL=` variables.

---

## Layout

```
advice-ai-lab/
├── advice-doc-intelligence/   advicedoc: corpus, ingest, classify, extract, validate, route, reconcile, workflow, api
├── file-note-copilot/         filenote: corpus, draft strategies, verifier, pii, eval, web (static UI), deploy (Cloud Run)
├── llm-app-ops-loop/          opsloop: sdk, collector, monitor, quality, dataset, prompts, regression, release, replay, incident
├── docs/DESIGN.md             gap analysis against the other three repositories and the design choices
├── .github/workflows/         one path-filtered CI workflow per project + the Cloud Run deploy workflow
└── Makefile                   install / lint / type / test / all
```

Each project is independently installable and has its own README, `docs/INTERVIEW_NOTES.md`
and `docs/RESULTS.md` — start with the one closest to the role you are hiring for.
