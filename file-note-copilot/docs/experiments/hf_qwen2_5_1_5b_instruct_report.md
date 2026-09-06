# File-note evaluation report

- created: 2026-09-06T16:49:32+00:00
- corpus: 20 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### single_shot (single_shot, hf[Qwen/Qwen2.5-1.5B-Instruct], pseudonymised)

- wall clock 484.1 s; model calls 20; JSON repairs 20; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 45677, completion 17031; latency per meeting 24.202 [21.321, 27.195] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.150 [0.025, 0.300] | 0.142 [0.025, 0.292] | **0.145 [0.025, 0.295]** |
| goals | 0.617 [0.425, 0.792] | 0.492 [0.325, 0.650] | **0.528 [0.353, 0.688]** |
| decisions | 0.187 [0.055, 0.337] | 0.392 [0.192, 0.617] | **0.195 [0.067, 0.333]** |
| action_items | 0.470 [0.345, 0.587] | 0.513 [0.356, 0.668] | **0.477 [0.343, 0.608]** |
| topics_discussed | | | 0.035 [0.000, 0.092] |
| advice_discussed | | | 0.078 [0.017, 0.145] |
| vulnerability_indicators | | | 0.550 [0.350, 0.750] |
| follow_up | | | 0.000 [0.000, 0.000] |
| **macro F1 (4 primary sections)** | | | **0.336 [0.271, 0.399]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 44.3% [37.7, 50.8] |
| Unmatched predicted claims | 74.2% [69.6, 79.1] |
| Omission rate | 78.9% [74.5, 83.0] |
| Compliance flags accuracy | 42.5% [33.8, 50.0] |
| Verifier-supported fraction | 28.3% [23.0, 33.6] |
| Numeric grounding rate | 100.0% [100.0, 100.0] |
| Action-item due date exact or within 3 days | 75.9% |
| Hallucinated claims (total) | 127 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 48 |
| Hallucination-free meetings | 0 / 20 |

### extract_then_compose (extract_then_compose, hf[Qwen/Qwen2.5-1.5B-Instruct], pseudonymised)

- wall clock 1303.6 s; model calls 191; JSON repairs 32; parse failures 53; failed windows 53; failed meetings 0
- tokens: prompt 238971, completion 45787; latency per meeting 65.177 [59.853, 70.371] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| goals | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| decisions | 0.150 [0.000, 0.301] | 0.125 [0.000, 0.300] | **0.133 [0.000, 0.300]** |
| action_items | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| topics_discussed | | | 0.000 [0.000, 0.000] |
| advice_discussed | | | 0.000 [0.000, 0.000] |
| vulnerability_indicators | | | 0.550 [0.350, 0.750] |
| follow_up | | | 0.050 [0.000, 0.150] |
| **macro F1 (4 primary sections)** | | | **0.033 [0.000, 0.075]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 77.1% [58.8, 94.2] |
| Unmatched predicted claims | 85.0% [70.0, 100.0] |
| Omission rate | 99.7% [99.1, 100.0] |
| Compliance flags accuracy | 21.2% [13.8, 28.7] |
| Verifier-supported fraction | 16.2% [1.2, 32.5] |
| Numeric grounding rate | 85.0% [65.0, 100.0] |
| Action-item due date exact or within 3 days | 100.0% |
| Hallucinated claims (total) | 58 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 10 |
| Hallucination-free meetings | 4 / 20 |

### verified (verified, hf[Qwen/Qwen2.5-1.5B-Instruct], pseudonymised)

- wall clock 50.2 s; model calls 207; JSON repairs 48; parse failures 53; failed windows 53; failed meetings 0
- tokens: prompt 252017, completion 47543; latency per meeting 2.507 [1.810, 3.211] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| goals | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| decisions | 0.150 [0.000, 0.301] | 0.125 [0.000, 0.300] | **0.133 [0.000, 0.300]** |
| action_items | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | **0.000 [0.000, 0.000]** |
| topics_discussed | | | 0.000 [0.000, 0.000] |
| advice_discussed | | | 0.000 [0.000, 0.000] |
| vulnerability_indicators | | | 0.550 [0.350, 0.750] |
| follow_up | | | 0.100 [0.000, 0.250] |
| **macro F1 (4 primary sections)** | | | **0.033 [0.000, 0.075]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 42.5% [22.5, 62.6] |
| Unmatched predicted claims | 60.0% [40.0, 80.0] |
| Omission rate | 99.7% [99.1, 100.0] |
| Compliance flags accuracy | 21.2% [13.8, 28.7] |
| Verifier-supported fraction | 42.5% [22.5, 62.5] |
| Numeric grounding rate | 85.0% [65.0, 100.0] |
| Action-item due date exact or within 3 days | 100.0% |
| Hallucinated claims (total) | 13 |
| ... surfaced to the adviser as unsupported | 13 (100.0%) |
| Unsupported flags left in final notes | 13 |
| Repair pass: cited / dropped | 15 / 43 |
| Small-talk segments cited | 5 |
| Hallucination-free meetings | 10 / 20 |

### verified_single_shot (verified_single_shot, hf[Qwen/Qwen2.5-1.5B-Instruct], pseudonymised)

- wall clock 161.5 s; model calls 40; JSON repairs 40; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 82429, completion 22765; latency per meeting 8.073 [6.436, 9.919] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.075 [0.000, 0.200] | 0.075 [0.000, 0.200] | **0.075 [0.000, 0.200]** |
| goals | 0.558 [0.350, 0.767] | 0.358 [0.208, 0.517] | **0.413 [0.250, 0.575]** |
| decisions | 0.075 [0.000, 0.200] | 0.150 [0.000, 0.350] | **0.083 [0.000, 0.217]** |
| action_items | 0.092 [0.000, 0.192] | 0.092 [0.000, 0.192] | **0.092 [0.000, 0.192]** |
| topics_discussed | | | 0.042 [0.000, 0.108] |
| advice_discussed | | | 0.046 [0.000, 0.096] |
| vulnerability_indicators | | | 0.550 [0.350, 0.750] |
| follow_up | | | 0.100 [0.000, 0.250] |
| **macro F1 (4 primary sections)** | | | **0.166 [0.123, 0.214]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 16.4% [9.6, 24.2] |
| Unmatched predicted claims | 80.6% [74.4, 85.9] |
| Omission rate | 92.1% [89.4, 94.6] |
| Compliance flags accuracy | 42.5% [33.8, 50.0] |
| Verifier-supported fraction | 61.0% [51.7, 70.8] |
| Numeric grounding rate | 100.0% [100.0, 100.0] |
| Action-item due date exact or within 3 days | 100.0% |
| Hallucinated claims (total) | 29 |
| ... surfaced to the adviser as unsupported | 29 (100.0%) |
| Unsupported flags left in final notes | 38 |
| Repair pass: cited / dropped | 36 / 143 |
| Small-talk segments cited | 32 |
| Hallucination-free meetings | 10 / 20 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| extract_then_compose | single_shot | macro_f1 | 0.033 | 0.336 | -0.303 | [-0.377, -0.221] | 0.00 | 4 / 0 | 0.125 | worse |
| extract_then_compose | single_shot | decisions_f1 | 0.133 | 0.195 | -0.062 | [-0.250, +0.155] | 0.28 | 2 / 6 | 0.289 | inconclusive |
| extract_then_compose | single_shot | action_items_f1 | 0.000 | 0.477 | -0.477 | [-0.608, -0.343] | 0.00 | 0 / 18 | 0.000 | worse |
| extract_then_compose | single_shot | hallucination_rate | 0.771 | 0.443 | +0.328 | [+0.160, +0.479] | 0.00 | 4 / 16 | 0.012 | worse |
| verified | single_shot | macro_f1 | 0.033 | 0.336 | -0.303 | [-0.377, -0.221] | 0.00 | 10 / 0 | 0.002 | worse |
| verified | single_shot | decisions_f1 | 0.133 | 0.195 | -0.062 | [-0.250, +0.155] | 0.28 | 2 / 6 | 0.289 | inconclusive |
| verified | single_shot | action_items_f1 | 0.000 | 0.477 | -0.477 | [-0.608, -0.343] | 0.00 | 0 / 18 | 0.000 | worse |
| verified | single_shot | hallucination_rate | 0.425 | 0.443 | -0.018 | [-0.228, +0.205] | 0.53 | 12 / 8 | 0.503 | inconclusive |
| verified_single_shot | single_shot | macro_f1 | 0.166 | 0.336 | -0.170 | [-0.236, -0.101] | 0.00 | 10 / 0 | 0.002 | worse |
| verified_single_shot | single_shot | decisions_f1 | 0.083 | 0.195 | -0.112 | [-0.287, +0.083] | 0.12 | 2 / 6 | 0.289 | inconclusive |
| verified_single_shot | single_shot | action_items_f1 | 0.092 | 0.477 | -0.385 | [-0.519, -0.255] | 0.00 | 0 / 16 | 0.000 | worse |
| verified_single_shot | single_shot | hallucination_rate | 0.164 | 0.443 | -0.279 | [-0.368, -0.187] | 1.00 | 18 / 1 | 0.000 | better |
| single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.336 | 0.545 | -0.208 | [-0.294, -0.128] | 0.00 | 0 / 0 | 1.000 | worse |
| single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.195 | 0.557 | -0.362 | [-0.517, -0.213] | 0.00 | 1 / 14 | 0.001 | worse |
| single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.477 | 0.697 | -0.220 | [-0.375, -0.071] | 0.00 | 3 / 14 | 0.013 | worse |
| single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.443 | 0.171 | +0.272 | [+0.199, +0.344] | 0.00 | 1 / 17 | 0.000 | worse |
| single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.336 | 0.434 | -0.097 | [-0.191, -0.010] | 0.01 | 0 / 1 | 1.000 | worse |
| single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.195 | 0.293 | -0.098 | [-0.237, +0.028] | 0.06 | 3 / 7 | 0.344 | inconclusive |
| single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.477 | 0.697 | -0.220 | [-0.404, -0.048] | 0.01 | 7 / 12 | 0.359 | worse |
| single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.443 | 0.134 | +0.309 | [+0.234, +0.389] | 0.00 | 0 / 20 | 0.000 | worse |
| single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.336 | 0.440 | -0.104 | [-0.196, -0.015] | 0.01 | 0 / 1 | 1.000 | worse |
| single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.195 | 0.318 | -0.123 | [-0.285, +0.013] | 0.04 | 2 / 7 | 0.180 | inconclusive |
| single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.477 | 0.697 | -0.220 | [-0.404, -0.048] | 0.01 | 7 / 12 | 0.359 | worse |
| single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.443 | 0.110 | +0.333 | [+0.261, +0.411] | 0.00 | 0 / 20 | 0.000 | worse |
| single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.336 | 0.546 | -0.210 | [-0.295, -0.131] | 0.00 | 0 / 0 | 1.000 | worse |
| single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.195 | 0.560 | -0.365 | [-0.517, -0.217] | 0.00 | 1 / 15 | 0.001 | worse |
| single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.477 | 0.700 | -0.223 | [-0.377, -0.072] | 0.00 | 3 / 14 | 0.013 | worse |
| single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.443 | 0.147 | +0.296 | [+0.226, +0.368] | 0.00 | 1 / 18 | 0.000 | worse |
| extract_then_compose | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.545 | -0.511 | [-0.590, -0.422] | 0.00 | 4 / 0 | 0.125 | worse |
| extract_then_compose | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.557 | -0.423 | [-0.633, -0.158] | 0.00 | 2 / 16 | 0.001 | worse |
| extract_then_compose | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.823, -0.564] | 0.00 | 0 / 19 | 0.000 | worse |
| extract_then_compose | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.771 | 0.171 | +0.599 | [+0.420, +0.778] | 0.00 | 4 / 16 | 0.012 | worse |
| extract_then_compose | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.434 | -0.400 | [-0.482, -0.316] | 0.00 | 4 / 1 | 0.375 | worse |
| extract_then_compose | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.293 | -0.160 | [-0.362, +0.087] | 0.08 | 2 / 9 | 0.065 | inconclusive |
| extract_then_compose | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.796, -0.584] | 0.00 | 0 / 19 | 0.000 | worse |
| extract_then_compose | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.771 | 0.134 | +0.637 | [+0.457, +0.805] | 0.00 | 4 / 16 | 0.012 | worse |
| extract_then_compose | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.440 | -0.406 | [-0.489, -0.324] | 0.00 | 4 / 1 | 0.375 | worse |
| extract_then_compose | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.318 | -0.185 | [-0.407, +0.070] | 0.07 | 2 / 9 | 0.065 | inconclusive |
| extract_then_compose | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.796, -0.584] | 0.00 | 0 / 19 | 0.000 | worse |
| extract_then_compose | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.771 | 0.110 | +0.661 | [+0.483, +0.828] | 0.00 | 4 / 16 | 0.012 | worse |
| extract_then_compose | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.546 | -0.513 | [-0.591, -0.425] | 0.00 | 4 / 0 | 0.125 | worse |
| extract_then_compose | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.560 | -0.427 | [-0.637, -0.163] | 0.00 | 2 / 16 | 0.001 | worse |
| extract_then_compose | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.700 | -0.700 | [-0.823, -0.570] | 0.00 | 0 / 19 | 0.000 | worse |
| extract_then_compose | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.771 | 0.147 | +0.624 | [+0.435, +0.807] | 0.00 | 4 / 16 | 0.012 | worse |
| verified | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.545 | -0.511 | [-0.590, -0.422] | 0.00 | 10 / 0 | 0.002 | worse |
| verified | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.557 | -0.423 | [-0.633, -0.158] | 0.00 | 2 / 16 | 0.001 | worse |
| verified | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.823, -0.564] | 0.00 | 0 / 19 | 0.000 | worse |
| verified | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.425 | 0.171 | +0.254 | [+0.043, +0.472] | 0.01 | 10 / 10 | 1.000 | worse |
| verified | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.434 | -0.400 | [-0.482, -0.316] | 0.00 | 10 / 1 | 0.012 | worse |
| verified | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.293 | -0.160 | [-0.362, +0.087] | 0.08 | 2 / 9 | 0.065 | inconclusive |
| verified | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.796, -0.584] | 0.00 | 0 / 19 | 0.000 | worse |
| verified | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.425 | 0.134 | +0.291 | [+0.090, +0.495] | 0.00 | 10 / 10 | 1.000 | worse |
| verified | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.440 | -0.406 | [-0.489, -0.324] | 0.00 | 10 / 1 | 0.012 | worse |
| verified | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.318 | -0.185 | [-0.407, +0.070] | 0.07 | 2 / 9 | 0.065 | inconclusive |
| verified | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.697 | -0.697 | [-0.796, -0.584] | 0.00 | 0 / 19 | 0.000 | worse |
| verified | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.425 | 0.110 | +0.315 | [+0.118, +0.517] | 0.00 | 10 / 10 | 1.000 | worse |
| verified | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.033 | 0.546 | -0.513 | [-0.591, -0.425] | 0.00 | 10 / 0 | 0.002 | worse |
| verified | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.133 | 0.560 | -0.427 | [-0.637, -0.163] | 0.00 | 2 / 16 | 0.001 | worse |
| verified | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.000 | 0.700 | -0.700 | [-0.823, -0.570] | 0.00 | 0 / 19 | 0.000 | worse |
| verified | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.425 | 0.147 | +0.278 | [+0.061, +0.499] | 0.01 | 10 / 10 | 1.000 | worse |
| verified_single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.166 | 0.545 | -0.379 | [-0.467, -0.287] | 0.00 | 10 / 0 | 0.002 | worse |
| verified_single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.083 | 0.557 | -0.473 | [-0.648, -0.233] | 0.00 | 1 / 15 | 0.001 | worse |
| verified_single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.092 | 0.697 | -0.605 | [-0.740, -0.456] | 0.00 | 0 / 18 | 0.000 | worse |
| verified_single_shot | single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.164 | 0.171 | -0.008 | [-0.088, +0.076] | 0.57 | 11 / 9 | 0.824 | inconclusive |
| verified_single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.166 | 0.434 | -0.268 | [-0.354, -0.177] | 0.00 | 10 / 1 | 0.012 | worse |
| verified_single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.083 | 0.293 | -0.210 | [-0.412, +0.018] | 0.04 | 2 / 9 | 0.065 | inconclusive |
| verified_single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.092 | 0.697 | -0.605 | [-0.735, -0.454] | 0.00 | 1 / 17 | 0.000 | worse |
| verified_single_shot | extract_then_compose@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.164 | 0.134 | +0.030 | [-0.050, +0.118] | 0.25 | 9 / 10 | 1.000 | inconclusive |
| verified_single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.166 | 0.440 | -0.274 | [-0.362, -0.179] | 0.00 | 10 / 1 | 0.012 | worse |
| verified_single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.083 | 0.318 | -0.235 | [-0.455, -0.003] | 0.02 | 2 / 9 | 0.065 | worse |
| verified_single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.092 | 0.697 | -0.605 | [-0.735, -0.454] | 0.00 | 1 / 17 | 0.000 | worse |
| verified_single_shot | verified@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.164 | 0.110 | +0.054 | [-0.019, +0.137] | 0.08 | 9 / 10 | 1.000 | inconclusive |
| verified_single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | macro_f1 | 0.166 | 0.546 | -0.380 | [-0.468, -0.290] | 0.00 | 10 / 0 | 0.002 | worse |
| verified_single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | decisions_f1 | 0.083 | 0.560 | -0.477 | [-0.652, -0.237] | 0.00 | 1 / 15 | 0.001 | worse |
| verified_single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | action_items_f1 | 0.092 | 0.700 | -0.608 | [-0.743, -0.464] | 0.00 | 0 / 18 | 0.000 | worse |
| verified_single_shot | verified_single_shot@hf[D:/models/Qwen3-4B-Instruct-2507] | hallucination_rate | 0.164 | 0.147 | +0.017 | [-0.067, +0.105] | 0.36 | 10 / 9 | 1.000 | inconclusive |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

