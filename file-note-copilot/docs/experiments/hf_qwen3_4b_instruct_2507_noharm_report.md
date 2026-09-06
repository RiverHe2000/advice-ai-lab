# File-note evaluation report

- created: 2026-09-06T16:16:11+00:00
- corpus: 20 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### verified+pseud (verified, hf[D:/models/Qwen3-4B-Instruct-2507], pseudonymised)

- wall clock 0.3 s; model calls 95; JSON repairs 15; parse failures 1; failed windows 0; failed meetings 1
- tokens: prompt 114646, completion 52969; latency per meeting 0.009 [0.008, 0.011] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.325 [0.175, 0.500] | 0.300 [0.150, 0.467] | **0.307 [0.157, 0.468]** |
| goals | 0.389 [0.252, 0.528] | 0.517 [0.350, 0.675] | **0.437 [0.292, 0.586]** |
| decisions | 0.292 [0.142, 0.458] | 0.500 [0.300, 0.700] | **0.318 [0.163, 0.487]** |
| action_items | 0.637 [0.527, 0.743] | 0.782 [0.652, 0.886] | **0.697 [0.584, 0.796]** |
| topics_discussed | | | 0.440 [0.314, 0.572] |
| advice_discussed | | | 0.057 [0.000, 0.127] |
| vulnerability_indicators | | | 0.300 [0.100, 0.500] |
| follow_up | | | 0.450 [0.250, 0.650] |
| **macro F1 (4 primary sections)** | | | **0.440 [0.362, 0.508]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 11.0% [8.1, 13.9] |
| Unmatched predicted claims | 56.7% [48.7, 63.0] |
| Omission rate | 58.1% [52.4, 64.6] |
| Compliance flags accuracy | 52.5% [43.8, 61.3] |
| Verifier-supported fraction | 74.8% [65.9, 81.5] |
| Numeric grounding rate | 93.2% [82.9, 98.9] |
| Action-item due date exact or within 3 days | 98.2% |
| Hallucinated claims (total) | 41 |
| ... surfaced to the adviser as unsupported | 41 (100.0%) |
| Unsupported flags left in final notes | 49 |
| Repair pass: cited / dropped | 57 / 5 |
| Small-talk segments cited | 2 |
| Hallucination-free meetings | 1 / 20 |

### verified (verified, hf[D:/models/Qwen3-4B-Instruct-2507], raw names)

- wall clock 3106.6 s; model calls 101; JSON repairs 15; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 124141, completion 57225; latency per meeting 155.326 [140.984, 172.572] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.471 [0.317, 0.625] | 0.458 [0.317, 0.617] | **0.454 [0.307, 0.603]** |
| goals | 0.439 [0.324, 0.558] | 0.583 [0.425, 0.733] | **0.493 [0.363, 0.620]** |
| decisions | 0.333 [0.167, 0.500] | 0.558 [0.350, 0.758] | **0.365 [0.198, 0.532]** |
| action_items | 0.668 [0.576, 0.758] | 0.767 [0.671, 0.849] | **0.705 [0.616, 0.786]** |
| topics_discussed | | | 0.452 [0.363, 0.549] |
| advice_discussed | | | 0.081 [0.017, 0.162] |
| vulnerability_indicators | | | 0.200 [0.050, 0.400] |
| follow_up | | | 0.400 [0.200, 0.650] |
| **macro F1 (4 primary sections)** | | | **0.504 [0.436, 0.576]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 9.7% [7.4, 12.1] |
| Unmatched predicted claims | 58.5% [53.9, 63.7] |
| Omission rate | 54.2% [49.9, 59.1] |
| Compliance flags accuracy | 56.2% [48.8, 62.5] |
| Verifier-supported fraction | 78.2% [74.6, 81.7] |
| Numeric grounding rate | 99.7% [99.0, 100.0] |
| Action-item due date exact or within 3 days | 98.3% |
| Hallucinated claims (total) | 38 |
| ... surfaced to the adviser as unsupported | 38 (100.0%) |
| Unsupported flags left in final notes | 40 |
| Repair pass: cited / dropped | 61 / 2 |
| Small-talk segments cited | 4 |
| Hallucination-free meetings | 2 / 20 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| verified | verified+pseud | macro_f1 | 0.504 | 0.440 | +0.065 | [+0.013, +0.118] | 0.99 | 2 / 1 | 1.000 | better |
| verified | verified+pseud | decisions_f1 | 0.365 | 0.318 | +0.047 | [-0.137, +0.217] | 0.69 | 5 / 3 | 0.727 | inconclusive |
| verified | verified+pseud | action_items_f1 | 0.705 | 0.697 | +0.009 | [-0.043, +0.067] | 0.60 | 4 / 5 | 1.000 | inconclusive |
| verified | verified+pseud | hallucination_rate | 0.097 | 0.110 | -0.012 | [-0.050, +0.023] | 0.74 | 9 / 10 | 1.000 | inconclusive |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

