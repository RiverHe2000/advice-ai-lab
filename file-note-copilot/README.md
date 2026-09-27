# file-note-copilot · evidence, verification and approval for AI-drafted adviser file notes

Drafts a financial adviser's file note from a client-meeting transcript, attaches transcript
evidence to every claim, verifies each claim mechanically, shows the adviser exactly what is
unsupported, and refuses final approval until a named adviser has resolved every unsupported
claim. Drafts and edits are stored before approval. Names are pseudonymised before the model sees the transcript, the
audit trail is PII-redacted. Run the application locally with an OpenAI-compatible or local
model endpoint. The included Cloud Run configuration is a disposable deployment demonstration,
with per-instance temporary storage; it is not a durable client-record system.

| | |
|---|---:|
| Quality gates | `ruff`, `mypy --strict` (src + tests), branch coverage, offline unit/API tests and Playwright browser checks; see the [executed checks](https://github.com/RiverHe2000/advice-ai-lab/actions/workflows/file-note-copilot-ci.yml) |
| Front end | HTML/CSS/JS, no framework, no build step, no inline handlers, CSP `script-src 'self'`; Server-Sent Events with `Last-Event-ID` resume; keyboard-navigable; light/dark |
| Verifier | model-free: citation validity, figure and date agreement after spoken-number normalisation, decision vs deferral language, action-item owner, small-talk detection, lexical support; optional embedding check |
| Recorded controlled experiment | On 700 planted hallucinations, the verifier detected **95–100% per kind**, with no hard false alarms on 1,669 gold claims. This measures the planted corruption set, not arbitrary real-model hallucinations. See [results and limitations](docs/RESULTS.md). |
| Recorded real-model experiment | Qwen3-4B on 20 synthetic meetings: one-pass macro F1 **0.545**; the two-pass approach was worse by **0.11**. The application now defaults to **verified_single_shot**. Historical hallucination percentages and the “44/44 surfaced” claim used a verifier-dependent denominator and are not independent detection recall. A fresh run under the corrected evaluator is required for updated model claims. |

**Related projects.** [`langgraph-agent-guardrails`](https://github.com/RiverHe2000/genai-platform-lab/tree/main/langgraph-agent-guardrails)
(genai-platform-lab) guards an *agent's* inputs, tool calls and outputs; this project guards
a *document the adviser signs*: every claim carries evidence, an independent verifier scores
it, and final approval requires a named approver. The PII rails share the same checksum
discipline (TFN mod-11) but are applied for data minimisation *before* the model, not only
for output filtering. Sibling projects in this repository: [`../advice-doc-intelligence`](../advice-doc-intelligence)
(reads advice documents into typed records) and [`../llm-app-ops-loop`](../llm-app-ops-loop)
(demonstrates LLM application operations). The owner's other repositories:
[`llm-engineering-lab`](https://github.com/RiverHe2000/llm-engineering-lab),
[`mlops-lab`](https://github.com/RiverHe2000/mlops-lab).

---

## 1. Architecture

```
 transcript ─► parse segments s001… ─► pseudonymise names (reversible) ─┐
                                                                         ▼
   single_shot:            one prompt ──────────────────────────────► JSON note
   extract_then_compose:   window (20 seg) ─► facts + segment ids ─► compose from facts only ─► JSON note
   verified:               extract_then_compose ─► VERIFIER ─► mark unsupported ─► repair pass (cite | drop) ─► re-verify
   verified_single_shot:   single_shot ─────────► VERIFIER ─► mark unsupported ─► repair pass (cite | drop) ─► re-verify
                                                                         │
                       restore names ◄──────────────────────────────────┘
                            │
   SQLite versions ◄── adviser edits (PUT, re-verified) ◄── two-pane UI (SSE progress, evidence chips, flags)
        │                     └── Approve: refused (409) while an unsupported claim is unedited; stores approver + diff
   audit JSONL (PII-redacted) · Prometheus /metrics · /health · /readyz (model backend)
```

| Component | File | Notes |
|---|---|---|
| Schema | `schema.py` | `FileNote` (meeting, summary, changes, goals, topics, advice, decisions, action items, compliance flags, follow-up); every claim cites ≥ 1 segment id; validation with a transcript context rejects unknown ids; `to_markdown()` is what the approval diff is computed on |
| Numbers | `numbers.py` | "eighty-five thousand" = "$85k" = "85,000"; "one point two million"; "nine point five percent"; four date formats incl. ordinals; identifiers (`s034`, `CLIENT_2`) are never figures |
| Corpus | `corpus/` | seed → transcript + gold note in one pass: fillers, interruptions, restatements, numbers spoken in several forms, explicit deferrals, compliance events that did or did not happen, small talk and contact-detail asides that must not reach the note; deterministic per seed |
| Models | `llm.py`, `fake.py` | one `ChatModel` protocol: OpenAI-compatible HTTP with bounded retries and `/models` readiness, in-process Hugging Face (lazy `torch`/`transformers`, hub id or local dir), and the scripted `GoldFakeChatModel` that answers from gold with configurable corruption kinds |
| Drafting | `draft/` | four strategies behind one `Drafter` (one-pass, two-pass, and the verify-and-repair loop on either base); one bounded JSON call everywhere (tolerant repair → pydantic → retry with the error → *missing*, never a default); progress events for SSE |
| Verifier | `verify/` | named checks with configurable thresholds (`VerifierConfig`), per-claim `supported / weak / unsupported` with reasons; `plant.py` + `selfeval.py` measure it against planted hallucinations |
| PII | `pii.py` | reversible pseudonymisation of attendees; redaction of TFN (mod-11), phone, e-mail, DOB, address for anything logged |
| Evaluation | `eval/` | Independent of verifier output, fuzzy one-to-one gold matching estimates unmatched claims; verifier flags are evaluated against that proxy. This is an approximate gold-matching measure, not human semantic adjudication. Reports also include omission, compliance, leaks, repairs, tokens, paired statistics and release gates. |
| Web | `web/app.py`, `web/jobs.py`, `web/static/` | FastAPI + `StreamingResponse` SSE with heartbeat and replay; `PUT` edits re-verified; approval rule enforced server-side; Prometheus registry per app; static two-pane UI with pure JS functions exposed for browser tests |
| Storage / audit | `store.py`, `audit.py` | SQLite drafts / versions / approvals (with diff) / feedback; append-only redacted JSONL, `filenote audit export` |
| Deployment | `deploy/` | multi-stage non-root Dockerfile with `HEALTHCHECK`; compose with an optional vLLM profile; Terraform for Cloud Run v2 (scale-to-zero, Secret Manager key, least-privilege runtime SA, Workload Identity Federation for GitHub) |
| CLI | `cli.py` | `corpus generate/show`, `draft`, `verify`, `eval`, `eval-verifier`, `transcribe` (faster-whisper, lazy), `serve`, `audit export` |

---

## 2. Results

The tables below describe recorded historical experiments, with artefacts in
`docs/experiments/` and [full results](docs/RESULTS.md). The old drafting evaluator
counted hallucinations only when its own verifier also marked them unsupported.
Its hallucination rates, hallucination-free comparisons and “100% surfaced” values
are therefore retired as independent quality claims. The corrected evaluator
counts unmatched gold claims regardless of verifier output; fuzzy matching remains
a proxy and can misclassify valid paraphrases. Run `make results` to produce new
scripted evidence; this does not rerun or rescore the historical GPU experiment.

**Verifier self-evaluation** — one hallucination of each kind planted into each of 100
gold notes, cluster-bootstrap intervals over meetings:

| Planted hallucination | Marked unsupported | | Planted hallucination | Marked unsupported |
|---|---:|---|---|---:|
| invented decision | 100 % | | deferred advice recorded as decided | 100 % |
| changed figure | 98 % [95, 100] | | citation to the wrong segment | 100 % |
| wrong action-item owner | 100 % | | small talk written into the note | 95 % [90, 99] |
| wrong due date | 100 % | | **false alarms on 1 669 gold claims** | **0.0 %** (6.1 % *weak*) |

**Strategy comparison, scripted model at 30 % corruption** (same 100 transcripts):

| | single_shot | extract_then_compose | verified |
|---|---:|---:|---:|
| Decisions F1 | 0.745 [0.684, 0.805] | 0.738 [0.676, 0.799] | **0.895 [0.844, 0.941]** |
| Macro F1 (4 sections) | 0.861 | 0.854 | **0.893** |



Historical paired `verified` − `single_shot`: decisions F1 +0.150 [+0.071, +0.233].
Omission is unchanged — a verifier cannot see
what the model left out; that is the model's job and the GPU stage measures it.
Pseudonymisation: identical metrics, non-inferior with margin 0.02 — and the check caught a
real bug (`CLIENT_2` read as the figure 2).

**What the scripted run does and does not prove.** The planted-corruption test
measures detection and false alarms against known injected errors. The drafting
workflow demonstrates repair, visible flags and server-side approval checks. These
are distinct from detecting every real-model hallucination. The recorded Qwen
experiment in section 8 of [RESULTS](docs/RESULTS.md) also found two-stage drafting
worse and pseudonymisation harmful to F1 on that small set. Those findings motivate
the one-pass verified default; they do not establish a general deployment guarantee.

---

## 3. Quick start

The UI, API, CLI, Compose and Terraform default to `verified_single_shot`:
one draft followed by verification and bounded repair. All four strategies remain
selectable for controlled comparisons. Historical examples below explicitly select
`verified` when reproducing the older two-pass experiment.

```bash
python -m venv .venv && source .venv/bin/activate        # .venv\Scripts\activate on Windows
pip install -e ".[dev]"                                   # [hf] local model, [audio] whisper, [semantic] embeddings, [serve]

filenote corpus generate --n 100 --seed 11 --out runs/corpus/meetings.jsonl --stats runs/corpus_stats.md
filenote corpus show --corpus runs/corpus/meetings.jsonl --id m0007 > runs/m0007.txt

# draft with the scripted model (no download), the OpenAI-compatible backend, or a local HF model
filenote draft runs/m0007.txt --model fake --strategy verified --markdown
filenote draft meeting.txt --model openai --base-url http://localhost:8000/v1 --model-name Qwen/Qwen2.5-7B-Instruct
filenote draft meeting.txt --model hf --model-name Qwen/Qwen3-4B-Instruct-2507 --pseudonymise on --out runs/note.json
filenote verify meeting.txt runs/note.json                # exit 1 if any claim is unsupported

# evaluation and the CI gates
filenote eval-verifier --n 100 --out runs/selfeval --gate
filenote eval --model fake --corruption 0.3 --n 100 --strategies single_shot extract_then_compose verified --out runs/eval
filenote eval --model fake --corruption 0.1 --strategies verified --out runs/gate --gate --min-f1 0.9 --max-hallucination 0.03

# the web app (scripted model knows the seeded corpus; paste any transcript too)
filenote serve --model fake --port 8080 --db-path state/drafts.sqlite --audit-path state/audit.jsonl
filenote audit export --audit-path state/audit.jsonl --out runs/audit_export.jsonl

# quality gates
make all                                                  # ruff + mypy --strict + pytest (browser tests skip if chromium is absent)
playwright install chromium && make test-e2e              # browser tests, required to pass
docker compose -f deploy/docker-compose.yml up --build    # app in a container; --profile vllm adds a GPU model server
```

Every knob is an environment variable (`FILENOTE_MODEL__KIND=openai`,
`FILENOTE_MODEL__BASE_URL=http://vllm:8000/v1`, `FILENOTE_VERIFIER__SUPPORT_OVERLAP=0.6`,
`FILENOTE_PSEUDONYMISE=false`). Transcript format: one segment per line,
`[hh:mm:ss] Name (role): text`, or just `Name: text`; the UI has a "Load sample" button.

---

## 4. Design decisions

* **Evidence is part of the schema, not a decoration.** A claim without a segment id does
  not validate; the UI renders the ids as chips that scroll to the segment; the verifier's
  unit of work is (claim, cited segments).
* **Compose from facts, not from the transcript.** Pass 2 never sees the raw dialogue, so an
  invented decision has nowhere to come from, and a long meeting fits any context window.
  The cost (≈ 4× tokens) and the risk (facts dropped between passes) are both measured.
* **A deterministic verifier the adviser can argue with.** "Figure $14,000 is not in the
  cited segments" is a sentence a reviewer can check in five seconds. Thresholds live in
  configuration; the self-evaluation reports what each setting buys.
* **Unsupported means visible, never deleted.** The model may cite or drop in the repair
  pass; what it insists on stays flagged and blocks approval. The server enforces the rule,
  the UI just reflects it.
* **Missing, never defaulted.** A response that does not parse after bounded retries is a
  recorded failure (a failed window, a failed meeting), not an empty note.
* **Data minimisation before the model.** Names go in as `CLIENT_1`; the mapping never
  leaves the process; the audit trail is redacted at write time.
* **Statistics as the reviewer expects them.** Bootstrap intervals, paired tests on the
  same cases, exact McNemar for binary outcomes, non-inferiority margins where a gate uses
  them, detection *and* false-alarm rates for the detector, ECE for the score.

## 5. Cloud Run deployment demonstration

The Terraform example demonstrates revisions, traffic splitting, Secret Manager
and GitHub Workload Identity Federation. The model runs behind a separate endpoint.
The default region is `australia-southeast1`; costs depend on current service and
model usage, and scale-to-zero is not a guarantee of a zero bill.

**The supplied configuration is disposable.** Drafts and audit records live under
`/tmp` on each instance and can be lost on restart, scale-to-zero or revision
replacement. Multiple instances do not share records. Use synthetic transcripts
only. A business pilot first needs shared persistent storage, durable audit
export, user authentication and recovery tests. See the
[deployment scope and setup](deploy/terraform/README.md).

## 6. Limitations and what was not done

* **Real-model numbers come from 20 meetings on one consumer GPU.** ≈ 14 tokens per second
  for a 4 B model made 100 meetings × 4 strategies × 2 models impractical; the intervals in
  section 8 of RESULTS.md are correspondingly wide, and only differences whose interval
  excludes zero are called verdicts.
* **Synthetic corpus.** Template dialogue with variation, not recorded meetings; gold notes
  are close paraphrases, so lexical false alarms are underestimated (6 % of gold claims land
  in the *weak* band; 0 % are blocked).
* **Verifier blind spots, measured**: 2 % of changed figures (the new value appears
  elsewhere in the cited segments) and 5 % of small talk (contains a domain word). A
  paraphrased invention that reuses real figures would pass the hard checks; the optional
  embedding check and an LLM entailment judge are the next rails, behind the same interface.
* **Transcription.** `filenote transcribe` (faster-whisper) produces no speaker labels; the
  owner check needs them. Diarisation is out of scope.
* **Storage scope.** Local SQLite/JSONL persistence requires a retained local path.
  The Cloud Run example uses ephemeral per-instance paths and is unsuitable for
  business records, even if restricted to one instance.
* Not built: multi-adviser auth, CRM integration, PDF rendering of the approved note.

Interview preparation notes: [docs/INTERVIEW_NOTES.md](docs/INTERVIEW_NOTES.md).

---

## 7. Layout

```
src/filenote/
├── schema.py, numbers.py, config.py, llm.py, fake.py, jsonrepair.py, pii.py, store.py, audit.py, transcribe.py, cli.py
├── corpus/       seed.py (meeting seed), render.py (dialogue + gold note), generate.py (corpus, stats)
├── draft/        base.py, facts.py, prompts.py, strategies.py (single_shot, extract_then_compose, verified)
├── verify/       text.py, embed.py, verifier.py, plant.py (hallucination kinds), selfeval.py
├── eval/         metrics.py, stats.py (bootstrap, paired, McNemar, ECE), runner.py, report.py
└── web/          app.py (FastAPI), jobs.py (SSE event log), static/{index.html, app.css, app.js}
tests/            205 tests: numbers, schema, corpus invariants, PII, every verifier check, planted kinds,
                  JSON repair, backends (HTTP mocked, HF stubbed), strategies, evaluation + stats, store/audit,
                  API incl. SSE resume and approval rule, CLI, transcriber, Playwright e2e (marked)
deploy/           Dockerfile, docker-compose.yml, terraform/ (Cloud Run v2, WIF, Secret Manager) + README
../.github/workflows/  file-note-copilot-ci.yml (lint → types → tests → gates → e2e → image + terraform), file-note-copilot-deploy-cloud-run.yml
scripts/          run_experiments.sh (CPU stage + GPU stage)
docs/             RESULTS.md, INTERVIEW_NOTES.md, experiments/
```
