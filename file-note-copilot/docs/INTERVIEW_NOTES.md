# Interview notes — file-note copilot

## The problem and the shape of the answer

**Why this project?** Advisers are being encouraged to draft file notes with AI, and the
three things holding adoption back are accuracy, the fact that the adviser stays
responsible for the content, and where the client data goes. This project is the
engineering answer to each: every claim in the draft carries transcript evidence, an
independent mechanical verifier scores every claim, nothing is saved until a named adviser
has resolved every unsupported claim and approved the note, names are pseudonymised before
the model sees the transcript, and the whole thing deploys behind any OpenAI-compatible
endpoint so the business chooses the model — including an open-source one on its own GPU.

**Walk me through one draft.** The transcript is parsed into numbered segments (`s001…`).
Attendee names are replaced by `CLIENT_1` / `ADVISER` / `PARAPLANNER` through a reversible
map. The `verified` strategy then runs three model passes: (1) *extract* — each window of
20 segments is turned into atomic facts, each carrying the ids of the segments that support
it; (2) *compose* — the note is assembled from the fact list *alone*, the model never sees
the raw transcript again; (3) *verify* — the deterministic verifier checks every claim: the
cited ids exist, the claim's figures and dates appear in the cited segments after
normalisation ("eighty-five thousand" = "$85k" = "85,000"), decisions cite commitment
language and not deferral language, action-item owners agree with who said "I'll", claims
have advice content at all (small talk), and content-word overlap is above a threshold.
Unsupported claims are marked, never deleted, and one bounded *repair* pass asks the model to
either cite real evidence or drop them. Names are restored, the note is versioned in SQLite,
and the adviser sees a two-pane UI: transcript left, note right, evidence chips on each
claim, unsupported claims flagged with colour + icon + text. The Approve button is disabled
until every unsupported claim has been edited or deleted; the server enforces the same rule
(409) and records the approver, the timestamp and the diff between the AI draft and what was
approved. Everything is written to a PII-redacted audit trail.

**Why extract-then-compose rather than one prompt?** Two reasons. Hallucination surface:
in the compose pass the model can only rearrange facts that already carry evidence ids, so
an invented decision has nowhere to hide. Context: a two-hour meeting does not fit a small
model's window; 20-segment windows fit any model. The cost is more calls (≈ 4× tokens on
this corpus) and the risk that a fact is dropped between passes, which the omission-rate
metric measures. With the scripted model the two strategies score the same by design; with
a real model the difference is what the GPU stage measures.

**Why a model-free verifier?** Because the adviser has to trust the flag more than the
draft. A rule that says "the claim mentions $14,000 and no cited segment does" is
deterministic, explainable in one line, free, and its detection and false-alarm rates can
be measured against a simulator with known truth. An LLM judge can be added behind the same
interface (the `semantic` check already has an embedder slot), but it would be a second
opinion, not the accountability mechanism.

## The verifier and its evaluation

**How do you know the verifier works?** I plant hallucinations of seven known kinds into
gold notes — an invented decision, a changed figure, a wrong action-item owner, a wrong due
date, a deferred item recorded as decided, a citation pointing at the wrong segment, small
talk written into the note — and measure per kind how often the planted claim is marked
*unsupported* (the status that blocks approval), whether the stated reason names the actual
problem, and, on the 1 669 untouched gold claims, how often a genuine claim is wrongly
blocked. On the synthetic corpus: 98–100 % detection on six kinds, 95 % on small-talk
leakage, 0 % false alarms (6 % of gold claims land in the informational *weak* band). The
numbers are in `docs/RESULTS.md` with cluster-bootstrap intervals over meetings.

**Those are suspiciously good.** They are a lower bound on false alarms and an upper bound
on detection, and the write-up says so: the gold notes are template paraphrases of the
transcript, so lexical overlap is high; real adviser notes paraphrase more and would push
more claims into the *weak* band. The hard checks (figures, dates, decision language, owner)
do not depend on paraphrase, which is why they are the ones that carry the approval rule.
The 2 % of changed figures that slip through are cases where the altered number happens to
appear elsewhere in the cited segments; the 5 % of small talk that slips through contains a
domain word ("your goals", "that statement"). Both are reported, not tuned away.

**"Deferred as decided" — why is that the interesting case?** Because it is the mistake a
summariser makes most naturally and the one that matters most for advice: the adviser
explained salary sacrifice, the client said "let me think about it", and the note says the
client agreed. The corpus plants at least one explicit deferral in every meeting; the
decision-language check requires at least one cited segment with commitment language and
no deferral language, so "we'll park that and revisit next time" fails even though it
contains "we'll". Detection on this kind is 100 %.

**How is "number agreement" robust to how people talk?** A small normaliser: digits with
separators and currency, `k`/`m`/`%` suffixes, and spoken forms ("twenty-seven thousand five
hundred", "one point two million", "nine point five percent"). Date mentions are parsed
separately (day/month/year in several formats, ordinal days) so "20 September" is compared
as a date, not as the figures 20 and 2026. Identifiers (`s034`, `CLIENT_2`) are never
figures — a bug the pseudonymisation check caught: `CLIENT_2` was being read as the figure
2, so pseudonymised drafts were flagged more often than raw ones until the boundary rule was
fixed. That is exactly what the paired no-harm check exists for.

**What is the support score and is it calibrated?** Each claim gets a score in [0, 1] from
the lexical overlap and the hard checks. Treating it as P(genuine) against the planted /
gold labels gives an ECE of 0.05 with a reliability table in the results — the score is
monotone but coarse (a hard failure is 0, otherwise it sits above 0.5). It is shown to the
adviser only as a status, never as a probability, precisely because it is not calibrated
enough to act on numerically.

## Statistics

**Why bootstrap intervals and paired tests?** Because "verified beats single-shot by 0.03
F1" means nothing on 100 meetings without an interval, and the two strategies see the *same*
100 transcripts, so the right comparison is the per-meeting difference: a paired bootstrap on
the mean difference and an exact McNemar test on the binary "hallucination-free note"
outcome. At corruption 0.3 the verified strategy is *better* on decisions F1 (+0.15,
CI [+0.07, +0.23]) and on hallucination rate, and the McNemar p on hallucination-free
meetings is < 0.001; at corruption 0.1 the F1 differences are inconclusive while the
hallucination rate is still better — which is the honest reading: the verifier's job is to
surface problems, not to raise F1.

**Why a cluster bootstrap for the verifier?** Claims within a meeting share a transcript,
speakers and figures, so they are not independent; resampling meetings rather than claims
keeps the interval honest.

**Pseudonymisation "no harm".** Same corpus, same corrupted model behaviour, once with
names and once with placeholders, compared pairwise with a non-inferiority margin of 0.02
F1: identical metrics, verdict *non-inferior* on every row. With the scripted model this is
a plumbing check (the fake returns the same content either way); with a real model it
becomes a real measurement, which is why the GPU script runs both.

## Product and engineering

**How does the UI enforce accountability?** The Approve button is disabled while any claim
is unsupported and unedited; editing a claim marks it `edited` and re-verifies the note
server-side; deleting removes it. The server refuses approval with a 409 and a count, logs
the blocked attempt, and on approval stores a unified diff between version 1 (the AI draft)
and the approved version. The diff is the record of what the adviser changed — the thing a
compliance reviewer actually wants.

**Why Server-Sent Events rather than WebSockets or polling?** The traffic is one-way
(server → browser), it must survive a dropped connection, and it should work through any
proxy. SSE gives an event id per frame; the client sends `Last-Event-ID` (or `last_id`) on
reconnect and the server replays from there, with a comment heartbeat every five seconds
so idle connections are not cut. The JS client reconnects with backoff and closes on `done`.

**No framework, no build step — why?** A CSP with `script-src 'self'` and no inline
handlers is a security property; a few pure functions (render, diff, unsupported count)
exposed on `window.filenote` are testable from Playwright directly; and an incubator
prototype that anyone can read in one file is worth more than a bundler.

**What is in the audit trail and what is not?** Every event (created, done, edited,
blocked approval, approved, feedback) with counts, the approver's identity, and the approval
diff. Every string passes the redactor before it is written: TFN (mod-11 checksum so a
balance is not a TFN), phone, e-mail, DOB, street address. The name → placeholder map is
never logged.

**What does the GPU stage add?** Twenty of the same transcripts with a real local model
(Qwen3-4B-Instruct-2507 and a 1.5 B baseline), four strategies, and the pseudonymisation
check, paired against each other. The scripted run proves the *machinery* (verifier,
repair, gates, UI); the real run measures the *model* — and it overturned one design
assumption (the two-pass draft) and one no-harm claim (pseudonymisation); see the section
below.

**Why Cloud Run for an incubator?** Scale-to-zero means a pilot with ten advisers costs
nothing overnight; revision-based traffic splitting gives a canary for free (the deploy
workflow tags a new revision, smoke-tests it with a scripted draft, then moves traffic);
Workload Identity Federation means no service-account key ever lives in GitHub. What would
move to GKE at scale: the model server (GPU node pools, vLLM), a proper database instead of
SQLite on the instance, and the audit stream into the firm's SIEM.

**What breaks first in production?** Transcription quality (speaker attribution from a
whisper transcript is not available, and the owner check depends on who said "I'll"),
paraphrase-heavy note styles pushing more claims into *weak*, and long meetings making the
repair pass expensive. Each is measurable with the same harness: replace the corpus with
real (consented) transcripts, keep the planted-hallucination self-evaluation as the
regression suite, and re-tune the thresholds in `VerifierConfig` from the false-alarm table.

## What the real model changed

**Your two-pass design lost to the one-pass draft. Why keep it?** Because the result is the
point, not the design. With Qwen3-4B on 20 meetings, `extract_then_compose` costs 0.11 macro
F1 [0.03, 0.18] and most of that is *decisions* (recall 0.50 vs 0.83): a per-window fact list
flattens the commitment language that separates "agreed to" from "discussed". The scripted
model could not show this because it answers every window from gold, so the mechanism check
and the real-model run are reported as two different kinds of evidence. The strategy stays
as a documented negative result, and the fourth strategy — the same verify-and-repair loop on
the one-pass draft — exists because the question "is it verification or the base that
helps?" needed separating: verification alone is non-inferior on F1 and lowers the
hallucination rate 17.1 % → 14.7 % (p = 0.031), 44 % → 16 % on the 1.5 B model.

**Pseudonymisation cost you F1. Would you ship it?** It costs 0.065 macro F1 [0.013, 0.118]
with a 4 B model, and the scripted no-harm check passed because the fake never reads names —
which is exactly the kind of gap a real-model run exists to find. What I would ship: redact
the identifiers that carry risk (TFN, DOB, contact details — done unconditionally), keep
pseudonymisation of *names* as a per-deployment switch, and require the paired no-harm
check on the deployment's model before it is turned on. The `--pseudonymise both` run is that
check; it takes an hour on a consumer GPU.

**The verifier had 0 % false alarms on gold notes and 16 % on the real model's notes. Which
number is true?** Both, for different texts. Gold notes paraphrase the dialogue closely;
a real model paraphrases more, so 8 of 49 flags landed on claims that did match the gold.
The rule that matters — approval refused while a flag is unresolved — turns a false alarm
into thirty seconds of adviser attention, not a wrong note, and the feedback endpoint records
which flags were wrong so the thresholds can be tuned from production rather than from my
corpus.

**Why only 20 meetings for the real model?** ≈ 14 tokens per second on one RTX 4070 for a 4 B
model, 60–400 s per meeting per strategy; 20 meetings × 4 strategies × 2 models plus the
no-harm check was 3.7 h. The response cache (`--cache`) made the two verified strategies
re-use their base drafts and a re-run free; the honest consequence is wide intervals, and the
report only calls a difference a verdict when the interval excludes zero.
