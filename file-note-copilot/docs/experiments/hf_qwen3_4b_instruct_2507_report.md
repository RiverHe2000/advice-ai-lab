# File-note evaluation report

- created: 2026-09-06T15:24:22+00:00
- corpus: 20 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### single_shot (single_shot, hf[D:/models/Qwen3-4B-Instruct-2507], pseudonymised)

- wall clock 1666.0 s; model calls 20; JSON repairs 0; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 45677, completion 21672; latency per meeting 83.297 [72.129, 96.905] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.258 [0.117, 0.433] | 0.258 [0.117, 0.433] | **0.258 [0.117, 0.433]** |
| goals | 0.683 [0.525, 0.825] | 0.675 [0.517, 0.833] | **0.667 [0.508, 0.817]** |
| decisions | 0.477 [0.343, 0.600] | 0.833 [0.675, 0.958] | **0.557 [0.400, 0.680]** |
| action_items | 0.697 [0.555, 0.826] | 0.717 [0.590, 0.833] | **0.697 [0.564, 0.823]** |
| topics_discussed | | | 0.074 [0.024, 0.138] |
| advice_discussed | | | 0.162 [0.045, 0.295] |
| vulnerability_indicators | | | 0.100 [0.000, 0.250] |
| follow_up | | | 0.150 [0.000, 0.300] |
| **macro F1 (4 primary sections)** | | | **0.545 [0.479, 0.613]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 17.1% [13.3, 21.0] |
| Unmatched predicted claims | 60.5% [54.2, 66.9] |
| Omission rate | 64.6% [59.6, 69.6] |
| Compliance flags accuracy | 48.8% [40.0, 57.5] |
| Verifier-supported fraction | 65.5% [59.9, 71.0] |
| Numeric grounding rate | 95.3% [92.1, 98.3] |
| Action-item due date exact or within 3 days | 98.2% |
| Hallucinated claims (total) | 52 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 3 |
| Hallucination-free meetings | 0 / 20 |

### extract_then_compose (extract_then_compose, hf[D:/models/Qwen3-4B-Instruct-2507], pseudonymised)

- wall clock 7454.4 s; model calls 76; JSON repairs 0; parse failures 1; failed windows 0; failed meetings 1
- tokens: prompt 95520, completion 50752; latency per meeting 372.715 [200.094, 701.364] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.325 [0.175, 0.500] | 0.300 [0.150, 0.467] | **0.307 [0.157, 0.468]** |
| goals | 0.389 [0.252, 0.528] | 0.517 [0.350, 0.675] | **0.437 [0.292, 0.586]** |
| decisions | 0.242 [0.125, 0.367] | 0.500 [0.300, 0.700] | **0.293 [0.150, 0.445]** |
| action_items | 0.637 [0.527, 0.743] | 0.782 [0.652, 0.886] | **0.697 [0.584, 0.796]** |
| topics_discussed | | | 0.440 [0.314, 0.572] |
| advice_discussed | | | 0.057 [0.000, 0.127] |
| vulnerability_indicators | | | 0.300 [0.100, 0.500] |
| follow_up | | | 0.450 [0.250, 0.650] |
| **macro F1 (4 primary sections)** | | | **0.434 [0.356, 0.504]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 13.4% [10.4, 16.4] |
| Unmatched predicted claims | 57.2% [49.5, 63.6] |
| Omission rate | 58.1% [52.4, 64.6] |
| Compliance flags accuracy | 52.5% [43.8, 61.3] |
| Verifier-supported fraction | 71.6% [62.5, 78.2] |
| Numeric grounding rate | 93.2% [82.9, 98.9] |
| Action-item due date exact or within 3 days | 98.2% |
| Hallucinated claims (total) | 51 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 3 |
| Hallucination-free meetings | 1 / 20 |

### verified (verified, hf[D:/models/Qwen3-4B-Instruct-2507], pseudonymised)

- wall clock 138.1 s; model calls 95; JSON repairs 15; parse failures 1; failed windows 0; failed meetings 1
- tokens: prompt 114646, completion 52969; latency per meeting 6.899 [5.240, 8.656] s

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

### verified_single_shot (verified_single_shot, hf[D:/models/Qwen3-4B-Instruct-2507], pseudonymised)

- wall clock 169.5 s; model calls 40; JSON repairs 17; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 67359, completion 24281; latency per meeting 8.469 [6.660, 10.361] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.258 [0.117, 0.433] | 0.258 [0.117, 0.433] | **0.258 [0.117, 0.433]** |
| goals | 0.683 [0.525, 0.825] | 0.675 [0.517, 0.833] | **0.667 [0.508, 0.817]** |
| decisions | 0.479 [0.346, 0.604] | 0.833 [0.675, 0.958] | **0.560 [0.408, 0.682]** |
| action_items | 0.701 [0.563, 0.826] | 0.717 [0.590, 0.833] | **0.700 [0.570, 0.823]** |
| topics_discussed | | | 0.074 [0.024, 0.138] |
| advice_discussed | | | 0.162 [0.045, 0.295] |
| vulnerability_indicators | | | 0.200 [0.050, 0.400] |
| follow_up | | | 0.150 [0.000, 0.300] |
| **macro F1 (4 primary sections)** | | | **0.546 [0.483, 0.613]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 14.7% [11.0, 18.8] |
| Unmatched predicted claims | 60.1% [53.9, 66.4] |
| Omission rate | 64.6% [59.6, 69.6] |
| Compliance flags accuracy | 48.8% [40.0, 57.5] |
| Verifier-supported fraction | 70.7% [64.6, 76.5] |
| Numeric grounding rate | 95.3% [92.1, 98.3] |
| Action-item due date exact or within 3 days | 98.2% |
| Hallucinated claims (total) | 44 |
| ... surfaced to the adviser as unsupported | 44 (100.0%) |
| Unsupported flags left in final notes | 52 |
| Repair pass: cited / dropped | 65 / 4 |
| Small-talk segments cited | 2 |
| Hallucination-free meetings | 0 / 20 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| extract_then_compose | single_shot | macro_f1 | 0.434 | 0.545 | -0.111 | [-0.183, -0.028] | 0.00 | 1 / 0 | 1.000 | worse |
| extract_then_compose | single_shot | decisions_f1 | 0.293 | 0.557 | -0.263 | [-0.442, -0.080] | 0.00 | 3 / 10 | 0.092 | worse |
| extract_then_compose | single_shot | action_items_f1 | 0.697 | 0.697 | +0.000 | [-0.129, +0.136] | 0.52 | 8 / 8 | 1.000 | inconclusive |
| extract_then_compose | single_shot | hallucination_rate | 0.134 | 0.171 | -0.037 | [-0.092, +0.017] | 0.92 | 13 / 7 | 0.263 | inconclusive |
| verified | single_shot | macro_f1 | 0.440 | 0.545 | -0.105 | [-0.177, -0.022] | 0.00 | 1 / 0 | 1.000 | worse |
| verified | single_shot | decisions_f1 | 0.318 | 0.557 | -0.238 | [-0.427, -0.027] | 0.01 | 3 / 10 | 0.092 | worse |
| verified | single_shot | action_items_f1 | 0.697 | 0.697 | +0.000 | [-0.129, +0.136] | 0.52 | 8 / 8 | 1.000 | inconclusive |
| verified | single_shot | hallucination_rate | 0.110 | 0.171 | -0.062 | [-0.119, -0.004] | 0.99 | 15 / 5 | 0.041 | better |
| verified_single_shot | single_shot | macro_f1 | 0.546 | 0.545 | +0.002 | [+0.000, +0.005] | 0.66 | 0 / 0 | 1.000 | non-inferior |
| verified_single_shot | single_shot | decisions_f1 | 0.560 | 0.557 | +0.003 | [+0.000, +0.010] | 0.66 | 1 / 0 | 1.000 | non-inferior |
| verified_single_shot | single_shot | action_items_f1 | 0.700 | 0.697 | +0.003 | [+0.000, +0.010] | 0.66 | 1 / 0 | 1.000 | non-inferior |
| verified_single_shot | single_shot | hallucination_rate | 0.147 | 0.171 | -0.025 | [-0.047, -0.008] | 1.00 | 6 / 0 | 0.031 | better |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

