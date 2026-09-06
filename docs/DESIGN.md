# Solution design — advice-ai-lab

Written before the first line of code, kept as the record of *why* the three projects look
the way they do. Numbers and results live in each project's `docs/RESULTS.md`.

## 1. The problem this repository answers

An Australian wealth-management platform's incubator team builds AI applications for
financial advisers, their clients and internal operations teams: large language models,
agents, classical machine learning and workflow systems, in Python, deployed on Google
Cloud, and then operated — monitored, debugged, improved.

Public material from that industry describes three concrete needs:

1. **Documents.** A classifier over ~20 document types that captures adviser and client
   metadata, and an extractor that pulls investment recommendations, risk profiles and fees
   out of advice documents so the business can compare what a client signed off on with
   what was implemented.
2. **File notes.** Advisers are encouraged to draft meeting file notes with AI, adoption is
   held back by accuracy concerns, the adviser stays responsible for the content, and there
   is interest in open-source models for local data control.
3. **Operations.** Shipped AI products must be monitored, issues investigated to root cause,
   and the product improved from what production shows.

Each project is one of those needs, built end to end and measured honestly.

## 2. Gap analysis against the existing portfolio

| Existing repository | Covers | Deliberately not repeated here |
|---|---|---|
| `llm-engineering-lab` | Transformer internals, LoRA fine-tuning with paired statistics, a batched inference server | Model training, serving internals |
| `genai-platform-lab` | Hybrid RAG with RAGAS-style evaluation, a LangGraph agent with guardrails and approval, an OpenAI-compatible gateway with eval-gated model promotion | Retrieval, agent state machines, gateway resilience, *model* promotion |
| `mlops-lab` | MLflow lifecycle with a statistical promotion gate, SageMaker BYOC blue/green, tabular drift monitoring with a calibrated alert policy | Experiment tracking, AWS deployment, *tabular* drift |

What the nine existing projects do **not** contain, and what this repository adds:

| Gap | Project here |
|---|---|
| Document understanding: PDFs → typed records, with a measured error rate | `advice-doc-intelligence` |
| Classical ML *inside* an LLM application (a document classifier, a calibrated review router) | `advice-doc-intelligence` |
| Human-in-the-loop routing with a risk-coverage trade-off chosen on evidence | `advice-doc-intelligence` |
| Faithful structured generation: claim-level evidence, an independent verifier, an approval workflow | `file-note-copilot` |
| A real web frontend (HTML/CSS/JavaScript, SSE streaming) with end-to-end browser tests | `file-note-copilot` |
| Google Cloud deployment (Cloud Run, Terraform, Workload Identity Federation) | `file-note-copilot` |
| Application-level LLM operations: traces, SLO burn-rate alerts, feedback, curated eval sets, prompt regression gates, prompt canaries, trace replay, incident reports | `llm-app-ops-loop` |

## 3. The through-line: read → draft → run

```
 documents ──► advice-doc-intelligence ──► typed records, review queue, reconciliation
 meetings  ──► file-note-copilot       ──► evidence-backed note, adviser approval
 both apps ──► llm-app-ops-loop        ──► traces, SLOs, eval set, regression gate, canary
```

The three are independent packages (no cross-imports) so each can be read, installed and
judged alone; the shared fiction ("Northshore Wealth", its advisers, clients and products)
keeps the examples coherent in an interview.

## 4. Design principles applied everywhere

* **Ground truth first.** Every project generates its own data with known answers — gold
  extractions, gold file notes, planted incidents — so every detector (validator, verifier,
  router, monitor) is reported with a detection rate *and* a false-alarm rate.
* **Deterministic in CI, real models later.** A scripted model with configurable corruption
  drives tests and CI gates; the same code paths run with an OpenAI-compatible endpoint or
  an in-process open-source model for the reported results. The pipeline is measured
  separately from the model's mood.
* **Statistics a model-risk function would accept.** Bootstrap intervals, paired
  comparisons, McNemar for binary outcomes, explicit non-inferiority margins, calibration
  tables where a probability drives a human decision.
* **The human stays responsible.** Nothing is auto-accepted without a calibrated confidence
  above a chosen threshold; nothing is saved as a file note without a named approver; a prompt
  change reaches all users only after a gate and a canary.
* **Privacy by construction.** No real people, products or identifiers; pseudonymisation
  before the model where the transcript is the input; redaction in every log, metric and
  audit line.
* **The same gates as the other nine projects.** `ruff`, `mypy --strict` on source and tests,
  branch coverage ≥ 90 %, offline test suites, path-filtered CI per project, pinned linters.

## 5. What the evidence said once the real models ran

Written after the fact, kept here because a design record that only contains the plan is
half a record.

* **The two-pass file-note draft (extract facts per window, then compose) was a mistake for
  a 4 B model.** It cost 0.11 macro F1 and most of the loss was decisions: a fact list loses
  the commitment language that separates "agreed" from "discussed". The one-pass draft with
  the verify-and-repair loop on top is the strategy that survived — same flags, no F1 loss.
* **Pseudonymising names before the model is not free.** 0.065 macro F1 with the 4 B model,
  a difference the scripted no-harm check could not see because the scripted model never
  reads the names. It stays a per-deployment switch with a paired check attached.
* **A 4 B model reads structured advice documents well and fails on interpretation.** Every
  scalar field exact on 40 SoAs; the errors were a boolean and a list, both invisible to the
  validators — which is the argument for the calibrated router rather than more rules.
* **Deterministic verification earns its place on real text, with a cost.** On gold notes
  the verifier had 0 % false alarms; on a real model's paraphrases about one flag in six sat
  on a claim that was actually right. The approval rule turns that into adviser attention,
  not a wrong note, and the feedback endpoint records it for tuning.
* **A consumer GPU changes the experiment design.** ≈ 14 tokens per second for a 4 B model
  meant 20 meetings and 40 documents rather than 100 and 120, a content-addressed response
  cache so strategies could share prompts, and one shared model instance when the same model
  answers and judges. The intervals are wide and the write-ups only call a difference a
  verdict when the interval excludes zero.

## 6. Choices worth defending in an interview

| Choice | Alternative | Why this one |
|---|---|---|
| Own extraction pipeline over PDF text | Google Document AI custom extractor | Model-agnostic, auditable, testable offline; Document AI OCR is the natural *ingest* layer for scanned documents and is named as such |
| Logistic regression + calibration for classification and routing | Zero-shot LLM everywhere | Cheaper by orders of magnitude, calibrated probabilities, McNemar shows where the LLM is actually better |
| Claim-level evidence + deterministic verifier | LLM-as-judge only | Deterministic checks are free, explainable and cannot hallucinate; the judge is an optional extra signal |
| Vanilla HTML/CSS/JS | React/Vite | No build toolchain to maintain for an incubator prototype; still testable end to end with Playwright |
| Cloud Run + Terraform | GKE manifests | Scale-to-zero cost for a prototype, revision traffic splitting for canaries; GKE is where it goes at scale |
| Prompt-level regression gate and canary | Model-level promotion only | Most production changes are prompt/app changes, not model swaps; those need the same discipline |
