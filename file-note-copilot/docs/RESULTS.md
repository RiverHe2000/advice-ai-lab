# Results

Produced by `bash scripts/run_experiments.sh` (`STAGE=cpu`) on 2026-09-06, Windows 11,
Python 3.12, CPU only, in about 20 s of compute. Every artefact is in
[`experiments/`](experiments/), every run is seeded (corpus seed 11, bootstrap seed 0), and
regenerating gives byte-identical JSON. Intervals are 95 % percentile bootstraps with 1 000
resamples; the verifier's intervals resample *meetings* (cluster bootstrap) because claims
within a meeting are not independent.

The CPU stage measures the **machinery** — corpus, verifier, strategies, gates, UI,
deployment path — with a scripted model that derives its answers from the gold note and
corrupts them at a known rate. It says nothing about a real model's competence; that is
section 8, where Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct run the same strategies on
the same transcripts.

## 1. Corpus — 100 synthetic meetings with gold notes

[`corpus_stats.md`](experiments/corpus_stats.md) · `filenote corpus generate --n 100 --seed 11`

| | |
|---|---:|
| Meetings | 100 (initial 27, annual review 28, insurance review 26, retirement planning 19) |
| Transcript segments | 4 506 (45.1 per meeting, range 40–58); mean duration 6 min of dialogue |
| Gold claims | 1 669 (16.7 per meeting): 2.1 circumstance changes, 2.1 goals, 3.9 topics, 2.7 advice items, 1.3 decisions, 3.5 action items, 0.3 vulnerability indicators, 0.85 follow-ups |
| Explicitly deferred advice | 136 items; **every** meeting has at least one deferral (the "discussed but not decided" trap) |
| Small talk / admin segments never cited | 972 (9.7 per meeting), incl. 30 meetings with a contact-detail aside (phone / e-mail / address / DOB / TFN) |
| Couples / paraplanner present / vulnerability indicator | 46 / 35 / 30 meetings |

Numbers are spoken in several forms (`$85,000`, `$85k`, `eighty-five thousand dollars`,
`85 thousand`) and dates in four; the gold note always writes the canonical form. Invariants
checked by the test suite: every gold claim cites existing segments, small talk is never
cited, deferred advice never appears in `decisions`, every figure and date in a gold claim
appears in its cited segments after normalisation.

## 2. Verifier self-evaluation on planted hallucinations — the headline

[`verifier_selfeval.md`](experiments/verifier_selfeval.md) · `filenote eval-verifier --n 100 --gate`

One hallucination of a known kind is planted into each gold note (700 plants), and the
verifier runs on the corrupted note and on the untouched gold note.

| Planted hallucination | n | Marked *unsupported* (blocks approval) | Reason names the problem |
|---|---:|---:|---:|
| invented decision (text not in the transcript) | 100 | **100.0 %** [100, 100] | 100.0 % |
| changed figure (×0.5 / ×1.25 / ×1.5 / ×2) | 100 | **98.0 %** [95.0, 100] | 98.0 % |
| wrong action-item owner | 100 | **100.0 %** [100, 100] | 100.0 % |
| wrong due date (±2–5 weeks) | 100 | **100.0 %** [100, 100] | 100.0 % |
| deferred advice recorded as decided | 100 | **100.0 %** [100, 100] | 100.0 % |
| citation to the wrong segment | 100 | **100.0 %** [100, 100] | 99.0 % |
| small talk written into the note | 100 | **95.0 %** [90.0, 99.0] | 95.0 % |
| **False alarms: gold claims marked unsupported** | 1 669 | **0.0 %** [0.0, 0.0] | – |
| Gold claims marked *weak* (informational, does not block) | 1 669 | 6.1 % [5.2, 7.0] | – |

Support-score calibration (score as P(claim is genuine), 2 369 claims): ECE = 0.050. The
score is monotone but coarse — a hard failure is 0, everything else sits above 0.5 — so the
UI shows a status, never a probability.

Reading it honestly:

* **What is caught deterministically**: figures and dates (after normalising spoken forms),
  decision language ("we'll park that and revisit next time" contains "we'll" and still
  fails, because deferral wins), owner ("could you send me…" + "sure, I'll…" implies the
  client), unknown ids.
* **The 2 % of changed figures missed** are cases where the altered value happens to appear
  elsewhere in the cited segments (e.g. a cap halved into an amount that was also said).
* **The 5 % of small talk missed** carries a domain word — "let's go through your goals",
  "I just need to find that statement". Generic words (goals, review, statement, plan,
  appointment) no longer count on their own; what remains would need an entailment judge.
* **0 % false alarms is a lower bound.** Gold notes are template paraphrases of the
  dialogue, so lexical overlap is high; real adviser notes paraphrase more and would push
  more claims into the *weak* band (already 6 %). The hard checks that carry the approval
  rule do not depend on paraphrase.

## 3. Scripted model: what `verified` catches that `single_shot` cannot

[`fake_strategies_p0.1.md`](experiments/fake_strategies_p0.1.md) ·
[`fake_strategies_p0.3.md`](experiments/fake_strategies_p0.3.md) ·
`filenote eval --model fake --corruption {0.1,0.3} --strategies single_shot extract_then_compose verified`

The scripted model answers from the gold note and corrupts each item with probability *p*
(drop, changed figure, wrong citation, wrong owner, wrong date), adds invented decisions,
deferred-as-decided items and small-talk leaks with probability *p* per note, malforms the
JSON with probability *p* per response, and with probability *p* refuses to fix a flagged
claim in the repair pass. All three strategies see the same corruption on the same 100
transcripts.

| corruption 0.3 | single_shot | extract_then_compose | **verified** |
|---|---:|---:|---:|
| Macro F1 (changes, goals, decisions, action items) | 0.861 [0.840, 0.883] | 0.854 [0.829, 0.879] | **0.893 [0.872, 0.913]** |
| Decisions F1 | 0.745 [0.684, 0.805] | 0.738 [0.676, 0.799] | **0.895 [0.844, 0.941]** |
| Action items F1 | 0.899 [0.868, 0.930] | 0.917 [0.883, 0.949] | 0.917 [0.883, 0.949] |
| Hallucination rate (no gold match **and** verifier-unsupported) | 6.8 % [5.6, 8.0] | 11.7 % [10.5, 13.1] | **4.8 %** [3.7, 6.0] |
| Omission rate | 11.3 % [9.8, 12.8] | 12.9 % [11.2, 14.5] | 12.9 % [11.2, 14.5] |
| Hallucinated claims in final notes | 112 | 195 | 74 |
| … of which **surfaced to the adviser as unsupported** | 0 (0 %) | 0 (0 %) | **74 (100 %)** |
| Repair pass: re-cited / dropped by the model | – | – | 226 / 121 |
| Small-talk segments cited | 79 | 150 | 53 |
| Hallucination-free notes | 31 / 100 | 9 / 100 | 49 / 100 |
| Model calls / JSON repairs / parse failures | 110 / 25 / 0 | 423 / 70 / 0 | 531 / 88 / 0 |
| Prompt + completion tokens | 145 k | 290 k | 348 k |

| corruption 0.1 | single_shot | extract_then_compose | **verified** |
|---|---:|---:|---:|
| Macro F1 | 0.955 [0.940, 0.967] | 0.944 [0.929, 0.957] | **0.962 [0.949, 0.973]** |
| Decisions F1 | 0.911 [0.862, 0.951] | 0.879 [0.827, 0.924] | **0.952 [0.913, 0.981]** |
| Hallucination rate | 2.2 % [1.5, 2.9] | 4.1 % [3.2, 5.0] | **1.2 %** [0.6, 1.8] |
| Hallucinated claims / surfaced | 38 / 0 | 67 / 0 | 19 / **19 (100 %)** |
| Hallucination-free notes | 69 / 100 | 50 / 100 | 85 / 100 |

Paired comparisons on the same transcripts (`verified` − `single_shot`; McNemar on the
binary "hallucination-free note"):

| corruption | Metric | Δ | 95 % CI | wins / losses | McNemar p | Verdict |
|---|---|---:|:---:|---:|---:|---|
| 0.3 | macro F1 | +0.032 | [+0.001, +0.063] | 34 / 16 | 0.015 | better |
| 0.3 | decisions F1 | +0.150 | [+0.071, +0.233] | 46 / 14 | < 0.001 | better |
| 0.3 | hallucination rate | −0.020 | [−0.036, −0.003] | 50 / 30 | 0.033 | better |
| 0.1 | macro F1 | +0.007 | [−0.010, +0.024] | 26 / 10 | 0.011 | inconclusive |
| 0.1 | decisions F1 | +0.041 | [−0.009, +0.098] | 17 / 9 | 0.169 | inconclusive |
| 0.1 | hallucination rate | −0.010 | [−0.019, −0.001] | 27 / 14 | 0.060 | better |

What the mechanism check shows and does not show:

* The verifier + repair pass turns hallucinations the adviser would otherwise sign into
  either dropped claims (121 at p = 0.3) or **visibly flagged** ones (every one of the 74
  that remain is marked unsupported, so approval is blocked until the adviser acts). The
  decisions-F1 gain is the deferred-as-decided and invented-decision items being removed.
* Omission is *not* improved by verification — a dropped fact is invisible to a checker
  that only sees the note. That is the real model's job, and the metric is there so the GPU
  stage can show it.
* `extract_then_compose` scores slightly below `single_shot` here **by construction**: the
  scripted model corrupts per window, so more calls mean more corruption events, and the
  fake cannot show the context-window and grounding benefits the two-pass design exists
  for. With a real model that comparison is the interesting one (GPU stage).
* JSON malformation (fences, trailing commas, truncation) is repaired or retried in every
  case; 0 parse failures across 1 064 calls, 183 repairs counted.

## 4. Pseudonymisation no-harm check

[`pseudonymisation_check.md`](experiments/pseudonymisation_check.md) ·
`filenote eval --model fake --corruption 0.3 --strategies verified --pseudonymise both --margin 0.02`

Same 100 transcripts, same corrupted model behaviour, once with real names and once with
`CLIENT_1` / `ADVISER` / `PARAPLANNER` placeholders restored after drafting, compared
pairwise with a non-inferiority margin of 0.02:

| Metric | raw names | pseudonymised | Δ | Verdict |
|---|---:|---:|---:|---|
| Macro F1 | 0.893 | 0.893 | +0.000 [0, 0] | non-inferior |
| Decisions F1 | 0.895 | 0.895 | +0.000 | non-inferior |
| Action items F1 | 0.917 | 0.917 | +0.000 | non-inferior |
| Hallucination rate | 4.8 % | 4.8 % | 0.000 | non-inferior |
| Unsupported flags / repairs cited / dropped | 197 / 226 / 121 | 197 / 226 / 121 | – | identical |

The check earned its place: the first run flagged 238 claims under pseudonymisation against
197 raw. The verifier was reading the digit in `CLIENT_2` as a figure and marking every claim
about the second client as "figure not in cited segments". Identifiers are no longer figures
(`numbers.py`), and a regression case is in the test table. With the scripted model this is a
plumbing check; with a real model (GPU stage) it measures whether placeholders change what
the model writes.

## 5. Gates — what CI runs on every push

[`ci_gate.md`](experiments/ci_gate.md), [`verifier_selfeval.md`](experiments/verifier_selfeval.md)

| Gate | Command | Threshold | Result |
|---|---|---|---|
| Verifier | `filenote eval-verifier --n 100 --gate --min-detection 0.9 --max-false-alarm 0.02` | every kind ≥ 90 % detected; ≤ 2 % gold claims blocked | **PASS** (min 95 %, false alarms 0 %) |
| Drafting | `filenote eval --model fake --corruption 0.1 --strategies verified --gate --min-f1 0.9 --min-decisions-f1 0.9 --max-hallucination 0.03 --max-omission 0.10 --min-surfaced 0.95` | conservative interval bounds; ≥ 95 % of hallucinations surfaced | **PASS** (macro F1 lower bound 0.949; hallucination upper bound 1.8 %; omission upper bound 6.2 %; surfaced 100 %) |

Both gates are deterministic (seeded corpus, seeded corruption, seeded bootstrap) and fail
the build with a non-zero exit code.

## 6. Browser end-to-end run

[`e2e_playwright.log`](experiments/e2e_playwright.log) — chromium 151 (headless shell) via
Playwright, app on a random port with the scripted backend in a background thread:

```
tests/test_e2e_playwright.py::test_draft_streams_highlights_blocks_and_approves PASSED
tests/test_e2e_playwright.py::test_pure_functions_in_browser PASSED
tests/test_e2e_playwright.py::test_reload_by_draft_id_and_reconnect_handling PASSED
3 passed in 2.67s
```

The first test drives the whole accountability loop in a real browser: paste → SSE
progress → evidence chip highlights the right segment → the invented decision is flagged
(colour + icon + "Unsupported" + reason) and **Approve is disabled** → edit the claim →
saved as version 2 → Approve enabled → approval stored with the approver and a diff → thumbs
down with a marked claim recorded. The Python coverage gate (98 %) is met with these tests
excluded.

## 7. Terraform

[`terraform_validate.txt`](experiments/terraform_validate.txt) — through the
`hashicorp/terraform:1.9` Docker image (Terraform v1.9.8): `fmt -check -recursive` clean,
`init -backend=false` installs `hashicorp/google ~> 6.0`, `validate` → *Success! The
configuration is valid.* Nothing was applied to a GCP project.

## 8. Real-model runs — Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct

[`hf_qwen3_4b_instruct_2507_report.md`](experiments/hf_qwen3_4b_instruct_2507_report.md) ·
[`hf_qwen3_4b_instruct_2507_noharm_report.md`](experiments/hf_qwen3_4b_instruct_2507_noharm_report.md) ·
[`hf_qwen2_5_1_5b_instruct_report.md`](experiments/hf_qwen2_5_1_5b_instruct_report.md) ·
`STAGE=gpu N_GPU=20 bash scripts/run_experiments.sh`

Setup: the first 20 meetings of the seeded corpus (`--n 20 --seed 11`), names pseudonymised
before the model, one RTX 4070 (12 GB), bf16, greedy decoding through the in-process
`transformers` backend (≈ 13 tok/s for the 4 B model, so a meeting costs 60–400 s depending
on the strategy — the reason for 20 meetings rather than 100). Every greedy answer is cached
by request (`--cache`), so the two `verified` strategies re-use their base draft's calls and
only pay for the repair pass. Wall clock: 4 B four strategies 2 h 37 min, no-harm check
52 min, 1.5 B four strategies 33 min. Intervals are bootstrap over the 20 meetings, so they
are wide; paired comparisons are on identical transcripts.

### Qwen3-4B-Instruct-2507, pseudonymised, 20 meetings

| Metric | single_shot | extract_then_compose | verified (two-pass + verify) | verified_single_shot |
|---|---:|---:|---:|---:|
| Macro F1 (changes, goals, decisions, action items) | **0.545** [0.479, 0.613] | 0.434 [0.356, 0.504] | 0.440 [0.362, 0.508] | **0.546** [0.483, 0.613] |
| Decisions F1 | 0.557 [0.400, 0.680] | 0.293 [0.150, 0.445] | 0.318 [0.163, 0.487] | 0.560 [0.408, 0.682] |
| Action items F1 · due date within 3 days | 0.697 [0.564, 0.823] · 98 % | 0.697 | 0.697 | 0.700 |
| Compliance flags accuracy | 48.8 % | 52.5 % | 52.5 % | 48.8 % |
| Hallucination rate (no gold match **and** verifier-unsupported) | 17.1 % [13.3, 21.0] | 13.4 % [10.4, 16.4] | **11.0 %** [8.1, 13.9] | 14.7 % [11.0, 18.8] |
| Hallucinated claims in final notes · surfaced to the adviser | 52 · 0 | 51 · 0 | 41 · **41 (100 %)** | 44 · **44 (100 %)** |
| Unsupported flags left in final notes (incl. flags on gold-matching claims) | – | – | 49 | 52 |
| Omission rate | 64.6 % [59.6, 69.6] | 58.1 % [52.4, 64.6] | 58.1 % | 64.6 % |
| Verifier-supported fraction of claims | 65.5 % | 71.6 % | 74.8 % | 70.7 % |
| Numeric grounding rate | 95.3 % | 93.2 % | 93.2 % | 95.3 % |
| Small-talk segments cited | 3 | 3 | 2 | 2 |
| JSON repairs / parse failures / failed meetings | 0 / 0 / 0 | 0 / 1 / 1 | 15 / 1 / 1 | 17 / 0 / 0 |
| Model calls · prompt + completion tokens | 20 · 45.7 k + 21.7 k | 76 · 95.5 k + 50.8 k | 95 · 114.6 k + 53.0 k | 40 · 67.4 k + 24.3 k |
| Latency per meeting | 83 s [72, 97] | 373 s [200, 701] | base cached + 7 s repair | base cached + 8 s repair |

Paired comparisons on the same 20 transcripts (Δ = A − B; McNemar on the binary
"hallucination-free note" for macro F1, on the sign of the per-meeting difference otherwise):

| A | B | Metric | Δ | 95 % CI | McNemar p | Verdict |
|---|---|---|---:|:---:|---:|---|
| extract_then_compose | single_shot | macro F1 | −0.111 | [−0.183, −0.028] | – | **worse** |
| extract_then_compose | single_shot | decisions F1 | −0.263 | [−0.442, −0.080] | 0.092 | **worse** |
| extract_then_compose | single_shot | hallucination rate | −0.037 | [−0.092, +0.017] | 0.263 | inconclusive |
| verified | single_shot | macro F1 | −0.105 | [−0.177, −0.022] | – | worse (inherits the two-pass base) |
| verified | single_shot | hallucination rate | −0.062 | [−0.119, −0.004] | 0.041 | **better** |
| verified_single_shot | single_shot | macro F1 | +0.002 | [+0.000, +0.005] | – | non-inferior |
| verified_single_shot | single_shot | decisions F1 | +0.003 | [+0.000, +0.010] | 1.000 | non-inferior |
| verified_single_shot | single_shot | hallucination rate | −0.025 | [−0.047, −0.008] | 0.031 | **better** |

**Pseudonymisation no-harm check with the real model** (`verified`, raw names vs
pseudonymised, same 20 transcripts, margin 0.02):

| Metric | raw names | pseudonymised | Δ (raw − pseud) | 95 % CI | Verdict |
|---|---:|---:|---:|:---:|---|
| Macro F1 | 0.504 [0.436, 0.576] | 0.440 [0.362, 0.508] | +0.065 | [+0.013, +0.118] | **raw better — pseudonymisation is not free** |
| Decisions F1 | 0.365 | 0.318 | +0.047 | [−0.137, +0.217] | inconclusive |
| Action items F1 | 0.705 | 0.697 | +0.009 | [−0.043, +0.067] | inconclusive |
| Hallucination rate | 9.7 % | 11.0 % | −0.012 | [−0.050, +0.023] | inconclusive |
| Failed meetings (unparseable compose answer) | 0 | 1 | | | |

### Qwen2.5-1.5B-Instruct (baseline), pseudonymised, same 20 meetings

| Metric | single_shot | extract_then_compose | verified | verified_single_shot |
|---|---:|---:|---:|---:|
| Macro F1 | 0.336 [0.271, 0.399] | 0.033 [0.000, 0.075] | 0.033 | 0.166 [0.123, 0.214] |
| Decisions F1 | 0.195 [0.067, 0.333] | 0.133 | 0.133 | 0.083 |
| Hallucination rate · surfaced | 44.3 % [37.7, 50.8] · 0 | 77.1 % · 0 | 42.5 % · 13 (100 %) | **16.4 %** [9.6, 24.2] · 29 (100 %) |
| Omission rate | 78.9 % | 99.7 % | 99.7 % | 92.1 % |
| JSON repairs / parse failures / failed windows | 20 / 0 / 0 | 32 / 53 / 53 | 48 / 53 / 53 | 40 / 0 / 0 |
| Latency per meeting | 24 s | 65 s | cached + 3 s | cached + 8 s |

4 B vs 1.5 B, `single_shot`, paired on the same transcripts: macro F1 +0.208 [+0.128, +0.294],
decisions F1 +0.362 [+0.213, +0.517] (McNemar p = 0.001), hallucination rate −0.272
[−0.344, −0.199] (p < 0.001). Every strategy is better on the 4 B model.

### What the real runs answered

1. **`extract_then_compose` does not beat `single_shot` — it loses, on both models.** With
   the 4 B model the two-pass draft costs 0.11 macro F1 (CI excludes zero) and the damage is
   concentrated in *decisions* (recall 0.50 vs 0.83): the per-window fact list flattens the
   commitment language that separates "agreed to salary-sacrifice" from "discussed
   salary-sacrificing", so the composer files decisions under advice discussed. It does trim
   omission (58 % vs 65 %) and hallucination (13 % vs 17 %, not significant) at 4.5× the
   latency. On the 1.5 B model the design collapses: 53 of 171 window extractions are
   unparseable and the composed notes are nearly empty (99.7 % omission). The scripted-model
   section above could not have shown this — the fake answers every window from gold — which
   is exactly why the two runs are reported separately.
2. **Verification helps whichever draft it sits on, and its value is the flag, not the F1.**
   On top of the one-pass draft (`verified_single_shot`) the repair loop leaves macro F1 and
   decisions F1 unchanged (non-inferior within the margin) and lowers the hallucination rate
   from 17.1 % to 14.7 % (p = 0.031); on the 1.5 B model it cuts it from 44 % to 16 %
   (p < 0.001), largely by dropping claims the model cannot cite. Every hallucination that
   survives in a verified note is flagged in the UI (41 / 41 and 44 / 44), so the adviser
   sees it; the approval rule then refuses to save until each is resolved. The cost with real
   paraphrase: 8 of the 49 flags in the `verified` notes sit on claims that *do* match the
   gold — false alarms the 0 % on gold notes (section 2) could not reveal — so roughly one flag
   in six costs adviser attention rather than catching an error.
3. **Pseudonymisation is not free with a 4 B model.** Replacing names with `CLIENT_1` /
   `ADVISER` costs 0.065 macro F1 [0.013, 0.118] on the `verified` strategy (one of the 20
   pseudonymised drafts also failed to parse). Decisions, action items and hallucination are
   inconclusive. The scripted check in section 4 passed because the fake never reads the
   names; the real model does, and attributions with placeholders come out coarser. The
   product decision this supports: pseudonymise identifiers that carry risk (TFN, DOB,
   contact details — already redacted) and measure before pseudonymising *names* for a given
   model, rather than assuming it is harmless.
4. **JSON discipline scales with model size.** The 4 B model needed no repairs on 20
   one-pass drafts and failed to parse 1 of 76 two-pass answers; the repair pass (a list of
   resolutions) needed 15–17 repairs per run. The 1.5 B model needed a repair on every one-pass
   answer (20 / 20, fenced output) and produced 53 unparseable windows. Both are recorded as
   *missing*, never as a default note.

What the numbers do not say: the gold notes carry ≈ 17 fine-grained claims per meeting and
the matcher is one-to-one with an owner match on action items, so omission (55–65 %) and
compliance-flag accuracy (≈ 50 %, mostly the model leaving a flag unset) measure the model's
*granularity* against a demanding gold as much as its correctness; the 60 % of predicted
claims with no gold match are mostly paraphrases and splits that the verifier still finds
supported. Twenty meetings also give wide intervals — the verdicts above are the ones whose
intervals exclude zero.

## 9. Limitations of these numbers

* Synthetic dialogue: template variation, fillers and restatements, but not the real
  disfluency, cross-talk and transcription errors of a recorded meeting; speaker labels are
  given, whereas a whisper transcript has none.
* Gold notes are close paraphrases, so lexical false alarms are underestimated.
* The scripted model's corruption kinds are the ones I could think of; a real model's
  failure modes will include others, which is what the feedback endpoint and the audit trail
  are for.
* Latencies reported here are the scripted model's and are meaningless as serving numbers.
