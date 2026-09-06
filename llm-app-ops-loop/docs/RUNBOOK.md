# Runbook — Northshore Adviser Assistant (opsloop alerts)

Every alert below is raised by `opsloop monitor` (multi-window burn rate on an SLO in
[`slos/default.yaml`](../slos/default.yaml), or the drift test) and paged through the Prometheus
rules in [`deploy/prometheus/rules.yml`](../deploy/prometheus/rules.yml). The first three steps
are the same for every alert:

1. **Read the evidence on the alert**: long/short window counts, burn rate, example trace ids
   (`opsloop monitor run --as-of <ISO> --out runs/now` prints the current evaluation).
2. **Look at the examples**: `GET /v1/traces/{id}` (or `opsloop replay <id>`), which prompt version,
   which tool, which topic.
3. **Draft the incident**: `opsloop incident report --window 2h --out runs/incident.md` classifies
   the failures, aggregates by prompt version / tool / topic / time bucket and finds the change
   point. Attach it to the ticket; fill in the timeline as you go.

Severity: `critical` pages (page window 10 min / 2 min at burn 3x, or fast window 30/5 at 2x);
`warning` opens a ticket (slow window 120/15 at 1x) and becomes `critical` after two consecutive
evaluations.

## `error_rate` — timeouts, provider 5xx, tool failures

* Suspect the **model provider** first: `by_error_class` in `/v1/stats?window=15m` separates
  `timeout` / `provider_error` / `tool_error`.
* Provider: check its status page, your rate limit, and the gateway's retry / fallback settings
  (the `llm-gateway-release` breaker opens on exactly this). Do not increase timeouts blindly:
  a 30 s timeout still costs the adviser 30 s.
* `tool_error`: the incident report's `by_tool` names the failing tool; check the upstream data
  service. The assistant answers "temporarily unavailable" rather than guessing — that is the
  intended degradation.
* Recovery is visible when the short window clears; the long window lags by its length.

## `latency_p95` — slow answers (successful requests only)

* Latency counts *successful* requests; a timeout burst shows up as `error_rate`, not here.
* Compare `latency_p50_ms` and `latency_p95_ms`: p95 alone rising = a slow tail (provider
  queueing, long outputs); both rising = the provider or a tool slowed down for everyone.
* If `completion_tokens_mean` rose too, see `cost_per_request` — verbose answers are slow answers.

## `cost_per_request` — the model is spending more per answer

* Is it output length (`completion_tokens_mean` up) or prompt length (`prompt_tokens_mean` up:
  a bigger tool payload, a longer system prompt, more history)?
* Check which prompt version is active (`opsloop release status`) — a prompt change is the usual
  cause; `opsloop prompt diff` the active version against the previous one.
* `cost_missing` > 0 means a model name the price table does not know: fix `pricing.py` (or
  `OPSLOOP_PRICING`) — a missing cost is deliberately never counted as zero.

## `quality_mean` / `grounding_rate` — answers are worse

* `grounding_rate` = share of answers that quote a number not present in any tool output. This
  is the cheapest hallucination detector and the first thing a prompt regression breaks.
* `opsloop replay <trace_id> --model fake` re-runs the recorded prompt; `--prompt-version v1`
  re-runs it with the previous prompt. If the previous prompt is grounded and the current one is
  not, roll back (`opsloop release rollback`) and add the failed traces to the review queue.
* Send a stratified sample to the judge (`opsloop sample` then `opsloop judge`) to confirm with
  the rubric; judge scores are stored with the judge model and prompt version.

## `refusal_rate` (high) and `refusal_rate_low`

* High: either the model started declining answerable questions (prompt regression — compare
  with the previous version) or the *questions* changed (see `topic_drift`: out-of-scope
  questions are refused by design).
* Low (`refusal_rate_low`): a refusal rate near zero over two hours usually means the
  out-of-scope guard stopped working — the assistant is answering questions it should decline.
  Check the prompt's scope instruction and the guardrail configuration.

## `json_validity` — structured answers do not parse

* Confined to JSON-format requests. A prompt that caps length or asks for "readable" output
  truncates JSON; the regression gate's JSON floor exists for this. Roll back the prompt.

## `pii_leak_rate` — an identifier appeared in an answer

* The SDK redacted it before storage; the count is what is stored. Treat as an incident: find
  which tool output carried the identifier (`opsloop replay` shows the recorded tool outputs
  with markers), fix the tool, add a redaction test, follow the privacy policy for notification.

## `negative_feedback_rate` — advisers are unhappy

* Read the `wrong_part` tags on the feedback (`GET /v1/traces/{id}` -> `feedback`):
  `numbers` points at grounding, `refusal` at scope, `format` at JSON / PII, `tone` at a prompt
  wording change.
* Feedback arrives late; this alert usually confirms one of the alerts above rather than
  leading it.

## `topic_drift` — the questions changed

* The evidence lists the topics that grew and their terms; a `novel` topic means vocabulary the
  baseline never saw. Decide whether it is a product change (new question types the assistant
  should support: add tools and cases, re-baseline) or misuse (route to the right tool).
* Re-baseline deliberately: the monitor's baseline is the first `baseline_minutes` of the run
  (`monitor.baseline_minutes`); in production point it at a reviewed week.

## `judge_score` — judged answers scoring below 3.5

* Only traces judged from a **uniform** sample count here (a failure-targeted sample would bias
  the SLO by construction). Confirm the judge model and prompt version did not change
  (`scores.model`, `scores.prompt_version`) before blaming the assistant.

## After the incident

* `opsloop curate` the failed traces -> review -> `opsloop dataset build` a new version -> the
  regression gate now guards against this class of failure for every future prompt change.
* Record the time-to-detect against the monitor's measured numbers in `docs/RESULTS.md`; if an
  incident was missed, add it as a scenario and re-run `opsloop monitor evaluate`.
