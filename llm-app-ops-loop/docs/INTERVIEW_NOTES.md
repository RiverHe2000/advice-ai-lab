# Interview notes — the operations loop around an LLM application

## The loop

**Walk me through what happens after the assistant ships.** Every request runs inside
`tracer.trace(...)`: a guardrail span (input PII policy), one tool span per tool with the
recorded input and output, an LLM span with model and token usage, and the prompt name,
version, content hash and variables on the trace. The SDK prices the call (a model the price
table does not know is a *missing* cost, never zero), redacts PII from the text and every
string attribute but keeps the counts, decides head-based sampling (errors are always kept),
and hands the trace to an exporter — the SQLite store in-process, `POST /v1/traces` to the
collector, or OTLP-style JSON with `gen_ai.*` attribute names. At ingest the cheap heuristic
scorers run on every trace (empty, refusal, PII, numeric grounding against the recorded tool
outputs, JSON validity, length, tone) and write their outcome next to it. The monitor windows
those rows: every SLO is "at most *budget* of eligible requests may be bad", evaluated as a
burn rate on three window pairs (10/2, 30/5, 120/15 minutes) that must both burn, plus a
minimum number of bad events so a 1 % budget cannot page on two Poisson errors, plus a topic
drift test on the request text. Advisers give thumbs / regenerate / edit feedback against the
trace; a stratified sample (errors, negative feedback, low heuristic score, then random) goes
to the LLM judge and to a human review queue; accepted cases become a versioned JSONL dataset
with a content hash; every prompt change runs through the regression gate on that dataset
(paired bootstrap with a non-inferiority margin, exact McNemar, per-slice checks, JSON floor,
cost and latency budgets); a passing prompt ships as a 10 → 50 → 100 % canary whose cohort is
compared with control and rolled back automatically. When something breaks, `opsloop replay`
rebuilds the exact prompt from the trace and re-runs it, and `opsloop incident report`
classifies the failures, aggregates them and finds the change point.

**Why is "the monitor is measured" the headline?** Because an alerting policy is a
classifier and nobody deploys a classifier without a confusion matrix. The demo application
has a scenario file with planted incidents — the ground truth — so `opsloop monitor evaluate`
can report time-to-detect, detection rate and the false-alarm rate on quiet ticks, across
seeds with bootstrap intervals. The number a reviewer wants is the false-alarm rate, because
that is what decides whether people keep the pager on. The numbers are in `docs/RESULTS.md`;
the same command is the CI gate, so a threshold change is validated before it ships.

## Tracing SDK

**Why not just use OpenTelemetry?** In production I would, and the converter proves the
schema is compatible: the OTLP JSON uses `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.tool.name`, `error.type`, `service.version`, so dashboards written here carry over.
The reason to own a thin SDK in this project is the three behaviours OTel does not give you
out of the box and that the rest of the loop depends on: cost with explicit *missing*
semantics, PII redaction *with counts* (the count is the signal — "the model leaked a TFN" must
survive the redaction), and sampling that keeps errors and can promote a sampled-out trace
when negative feedback arrives later. Those live in a few hundred lines and are tested.

**"Never raises into the application" — how?** Exporter failures, redaction failures and
the trace build are wrapped and counted in `tracer.stats`; the application's own exceptions
are recorded on the span/trace (`error.type` from the exception's `kind` or class name) and
re-raised, because the application must still see them. Spans are id'ed deterministically from
the trace id, so a seeded run of the demo produces byte-identical exports (tested).

**Head-based sampling loses the interesting traces. What do you do about that?** Errors are
kept regardless of the sampling decision. For late signals (thumbs down five minutes later) the
tracer keeps a bounded buffer of sampled-out traces; `add_feedback` promotes the trace to the
exporter if it is still there. It is a bounded, best-effort answer to a problem tail-based
sampling solves properly at the collector; I say so in the README.

## Monitoring

**Why express every SLO as a bad-event fraction?** One mechanism for all of them. "p95 latency
under 2.5 s" is "at most 5 % of requests slower than 2.5 s"; "error rate under 1 %" is the
same statement with a different predicate; so are quality, refusals, JSON validity, PII and
cost. The burn rate is then bad-fraction / budget, and the multi-window rule (long window says
the budget is really burning, short window says it is still burning now) applies to all of
them. Latency counts successful requests only — a 30-second timeout is an error, not a slow
answer — so the two alerts do not fire together for one cause.

**What produced false alarms while you were building it, and what did you change?** Three
things, each measured by the self-evaluation rather than noticed by eye. (1) Windows that were
not yet full: a 2-hour window holding five minutes of data fired on a handful of events; now
a window is evaluated only once it has existed for its full length. (2) A 1 % error budget on
a 10-minute window pages on two Poisson errors; a minimum bad-event count (3) per window
removed that without slowing detection of a real burst (25 % errors gives twelve in ten
minutes). (3) The refusal-rate *floor* on a short window fired whenever nobody happened to
refuse; floors now only use the slowest full window. The measured false-alarm rate after those
changes is in `docs/RESULTS.md`.

**How does text drift work and why the "novel" bucket?** Requests are embedded with a
deterministic hashing embedder (unigrams + bigrams, crc32, L2-normalised — no model download),
k-means is fitted on the first half of the baseline hour, and the reference topic mix is
counted on the second half so in-sample tightness does not make ordinary windows look
drifted. The current window's mix is compared with a two-sample chi-square test **and** a
Jensen-Shannon distance above a bootstrap threshold (what a window of that size reaches by
chance under the baseline mix); both must fire. The first version without the novelty bucket
detected the planted topic shift late or not at all: out-of-scope questions ("Age Pension",
"binding death benefit nomination", "SMSF rollover") share enough ordinary words to be
absorbed into existing clusters. A request farther from every centroid than the 95th
percentile of held-out baseline distances is now assigned to an extra topic, so unseen
vocabulary shows up as growth of that bucket, and the alert names the terms. Detection went
from 55 minutes to 15 with no change in false alarms.

**Why is the judge SLO restricted to uniform samples?** Because the stratified sample is
deliberately failure-heavy (that is what a judge should look at), and a mean over it is not
the population mean — the first smoke run raised a `judge_score` alert purely from selection
bias. Judge scores from stratified samples are stored (with judge model and prompt version,
for audit) but do not write the trace's `judge` column that the SLO reads.

## Quality and datasets

**Numeric grounding — how, and what does it not catch?** Every number in the answer must
appear in the recorded tool outputs (or the question), with fractions accepted in percentage
form, ISO dates matched as strings, and a small tolerance. It is deterministic, free, and
catches the most expensive hallucination on an advice desk — an invented or altered figure.
It cannot see a number that is present but attached to the wrong thing, which is what the
rubric judge is for. The design consequence in the demo: tools compute every derived figure
(deviation in percentage points, days to review, fee totals, contribution room) so the model
only ever repeats numbers. A parametrized test asserts that invariant for all 42 templates.

**Why store expectations rather than gold answers?** Advice answers are not unique strings.
A curated case snapshots the input, the context the model saw (tool outputs, prompt
variables), and the *properties* a correct answer must have — must / must-not contain,
numeric facts, JSON expected, refusal allowed — plus provenance (trace id, reviewer, date).
The heuristic scorers evaluate those properties for any prompt or model; the reference answer
is kept for humans and for edit-distance style checks, not as the ground truth.

**How is the dataset versioned?** JSONL per version with a manifest carrying a content hash
over the canonical case lines, the parent version and hash, a changelog and slice counts;
versions are immutable, near-duplicates (rapidfuzz on the normalised input) are rejected and
listed, `dataset diff` shows added / removed / changed cases, and `load` refuses a file whose
hash does not match its manifest.

## The regression gate

**What exactly decides PASS?** On the same cases with the same model: (1) the 95 % paired
bootstrap interval of the per-case quality delta must not cross −margin (non-inferiority);
(2) an exact McNemar test on per-case pass/fail must not show significantly more losses than
wins; (3) no slice with enough cases may regress by more than the slice margin; (4) JSON
validity on JSON cases must stay above the floor; (5) mean cost per case and p95 latency must
stay within budget relative to the baseline; (6) fewer paired cases than `min_cases` is
INSUFFICIENT_DATA, which fails. The CLI exit code is the decision, so CI can act on it.

**Why is the fake model's v2 "measurably different"?** The fake model obeys a handful of
directives it finds in the system prompt, so a prompt change changes behaviour the way it
would with a real model and replay reproduces recorded answers exactly. v1 rounds the fee
percentage ("about 1.2 %") — ungrounded on the fees slice; v2 adds "quote figures exactly"
(fixes it), states the allocation deviation in percentage points, and makes review-date
answers terse (a small tone regression on the reviews slice, inside the slice margin) at
slightly higher cost. v2-regressed adds "round figures", a 40-word cap and "decline if the
valuation is stale": ungrounded numbers everywhere, truncated JSON, refusals — the gate fails
on non-inferiority, McNemar, slices and the JSON floor. The test suite asserts each decision
branch separately with synthetic case runs.

## Canary and rollback

**How does the canary decide?** Sessions hash into 100 buckets, so a session always sees the
same prompt version and the split is reproducible. The cohorts on the same window are
compared with one-sided two-proportion tests on error and refusal rates (canary worse than
control by more than the allowed delta at α), and a bootstrap interval on the difference in
heuristic quality means (upper bound below −margin rolls back). Below the minimum sample per
cohort the decision is *hold*. On the demo traffic v2 advances 10 → 50 → 100 and is promoted;
v2-regressed rolls back at 10 %.

**What is the gap between this and a real canary?** Session bucketing at 10 % with a few
hundred sessions is coarse — the demo needs eight simulated hours to reach 100 canary
requests — and error and refusal rates on a small cohort have wide intervals; the policy
therefore holds rather than guesses. A real deployment would also compare latency and cost,
and would gate on the judge for a sampled subset.

## Replay and incidents

**Why does replay reproduce the answer exactly?** Because the trace records what the model
actually saw: prompt name, version, content hash, variables, and the tool outputs, and the
application's prompt assembly is a pure function of those. Replay rebuilds the messages,
stubs the tools with the recorded outputs, re-runs the model, diffs, and re-scores; with
`--prompt-version` it answers "what would the previous prompt have said". A changed prompt
hash since recording is flagged.

**How is the change point found?** Failure rate per 10-minute bucket, then the split that
maximises the standardised difference in means before and after (weighted by bucket counts) —
single-step binary segmentation. It is deliberately simple: the incident report is a skeleton
a human completes, and the number a human needs first is "when did it start".

## Statistics and honesty

**Where are the intervals?** Every headline metric carries a seeded bootstrap 95 % interval:
detection rate and time-to-detect across seeds, the false-alarm rate across quiet ticks, the
paired delta in the gate, the quality difference in the canary. Two systems are only compared
on the same cases (paired bootstrap, McNemar), never from point estimates. With three seeds the
detection intervals are degenerate (all detected) and I say so; the harness takes `--seeds` for
more.

**What is fake here and what would change with a real model?** The traffic, the incidents and
the model are simulated so the monitor can be measured against known truth — that is the
point, and the limitation. With a real model the heuristic scorers, the judge, the gate, the
canary, replay and the incident report run unchanged (`--model openai|hf`); the GPU stage in
`scripts/run_experiments.sh` runs the curated dataset through the gate with a real model
answering and judging. What would not carry over as-is are the demo's grounding guarantee
(a real model does arithmetic) and the fake judge's agreement with the heuristics.

## Model risk / governance angle

**How does this map to what a wealth platform's risk function asks for?** Every model
interaction is logged with inputs, tool calls, prompt version and content hash for replay;
PII never reaches the store; quality is measured continuously with an explicit alerting policy
whose false-alarm and detection rates are documented; changes to the prompt go through a
versioned evaluation set and a statistical gate with an exit code; releases are staged with an
automatic rollback rule; incidents have a runbook and a report template. That is the evidence
base for signing an assistant off for adviser use — and for showing, after an incident, what
was known when.

## What the real model changed

**Your "good" prompt failed the gate with the real model. Is the gate wrong?** No — it is the
most useful thing the run produced. On 80 curated cases with Qwen3-4B answering and judging,
v2 is non-inferior to v1 (Δ +0.009, interval touching zero from below, every slice fine) and
the gate still returns FAIL because the two cases that require a JSON answer got prose from
*both* prompts. The floor is absolute on purpose: a prompt family that cannot honour a
format contract must not ship, whatever the average says. The report prints `n=2` beside
the floor so nobody mistakes an under-powered check for a strong one, and it names the
cause, so the fix is a format instruction the model follows or a JSON-mode backend — not a
different prompt v2.

**The regressed prompt only cost 0.028 with a real model, against 0.304 with the fake.
Which is true?** The real one. The scripted model obeys the regression directive literally;
a real model mostly answers well regardless and just gets terser (35 tokens against 80).
That is what a production regression looks like — small and quiet — and it is why the gate
does not trust a single number: the paired interval excludes zero, McNemar on pass–fail is
significant (14 losses to 3 wins), and the JSON floor fails. Scripted regressions are upper
bounds for testing the machinery; real ones are what the thresholds have to be tuned on.

**Did the judge survive contact with a real model?** 60 traces, 0 missing, 0 repairs,
means within 0.02 of the fake judge's uniform sample, rationales that quote the tool
output. What the run cannot show is agreement with a human reviewer; the feedback endpoint
and the review queue exist to collect that, and the judge's model and prompt version are
stored with every score so a judge change is auditable later.

**Why 80 cases, and what did the GPU force you to change?** ≈ 14 tokens per second for a 4 B
model on one RTX 4070: the full 205 cases × two prompts × answer + judge is about three
hours per gate. Two engineering changes came out of it: a content-addressed response cache
(`--cache`), so the v1 baseline half of the second gate and every re-run are free, and one
shared in-process model when the same model answers and judges — two 4 B copies spilled out
of 12 GB and ran three times slower before that was measured and fixed. Both are the kind
of thing an incubator learns in week one and should not learn twice.
