# File-note evaluation report

- created: 2026-09-06T12:14:48+00:00
- corpus: 100 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### single_shot (single_shot, fake[p=0.1], corruption 0.1, raw names)

- wall clock 0.5 s; model calls 105; JSON repairs 6; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 106487, completion 32422; latency per meeting 0.001 [0.001, 0.001] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 1.000 [1.000, 1.000] | 0.955 [0.928, 0.978] | **0.971 [0.954, 0.987]** |
| goals | 0.990 [0.970, 1.000] | 0.953 [0.918, 0.980] | **0.967 [0.939, 0.987]** |
| decisions | 0.894 [0.842, 0.938] | 0.985 [0.960, 1.000] | **0.911 [0.862, 0.951]** |
| action_items | 0.983 [0.969, 0.995] | 0.962 [0.942, 0.982] | **0.970 [0.954, 0.986]** |
| topics_discussed | | | 0.964 [0.950, 0.976] |
| advice_discussed | | | 0.986 [0.969, 0.998] |
| vulnerability_indicators | | | 1.000 [1.000, 1.000] |
| follow_up | | | 0.980 [0.950, 1.000] |
| **macro F1 (4 primary sections)** | | | **0.955 [0.940, 0.967]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 2.2% [1.5, 2.9] |
| Unmatched predicted claims | 2.3% [1.6, 3.0] |
| Omission rate | 3.5% [2.6, 4.3] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 86.4% [84.9, 88.0] |
| Numeric grounding rate | 97.7% [97.0, 98.4] |
| Action-item due date exact or within 3 days | 98.7% |
| Hallucinated claims (total) | 38 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 31 |
| Hallucination-free meetings | 69 / 100 |

### extract_then_compose (extract_then_compose, fake[p=0.1], corruption 0.1, raw names)

- wall clock 0.6 s; model calls 403; JSON repairs 22; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 208519, completion 66631; latency per meeting 0.002 [0.002, 0.002] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 1.000 [1.000, 1.000] | 0.935 [0.902, 0.963] | **0.958 [0.935, 0.977]** |
| goals | 0.997 [0.990, 1.000] | 0.973 [0.953, 0.990] | **0.982 [0.968, 0.993]** |
| decisions | 0.866 [0.812, 0.913] | 0.957 [0.918, 0.987] | **0.879 [0.827, 0.924]** |
| action_items | 0.971 [0.950, 0.988] | 0.944 [0.918, 0.968] | **0.955 [0.934, 0.975]** |
| topics_discussed | | | 0.926 [0.908, 0.943] |
| advice_discussed | | | 0.980 [0.964, 0.993] |
| vulnerability_indicators | | | 1.000 [1.000, 1.000] |
| follow_up | | | 0.930 [0.880, 0.970] |
| **macro F1 (4 primary sections)** | | | **0.944 [0.929, 0.957]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 4.1% [3.2, 5.0] |
| Unmatched predicted claims | 4.1% [3.2, 5.0] |
| Omission rate | 5.2% [4.2, 6.2] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 86.0% [84.5, 87.4] |
| Numeric grounding rate | 97.6% [96.8, 98.3] |
| Action-item due date exact or within 3 days | 98.6% |
| Hallucinated claims (total) | 67 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 50 |
| Hallucination-free meetings | 50 / 100 |

### verified (verified, fake[p=0.1], corruption 0.1, raw names)

- wall clock 1.2 s; model calls 478; JSON repairs 24; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 231453, completion 67469; latency per meeting 0.009 [0.008, 0.009] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 1.000 [1.000, 1.000] | 0.935 [0.902, 0.963] | **0.958 [0.935, 0.977]** |
| goals | 0.997 [0.990, 1.000] | 0.973 [0.953, 0.990] | **0.982 [0.968, 0.993]** |
| decisions | 0.958 [0.920, 0.988] | 0.957 [0.918, 0.987] | **0.952 [0.913, 0.981]** |
| action_items | 0.971 [0.950, 0.988] | 0.944 [0.918, 0.968] | **0.955 [0.934, 0.975]** |
| topics_discussed | | | 0.964 [0.950, 0.977] |
| advice_discussed | | | 0.980 [0.964, 0.993] |
| vulnerability_indicators | | | 1.000 [1.000, 1.000] |
| follow_up | | | 0.930 [0.880, 0.970] |
| **macro F1 (4 primary sections)** | | | **0.962 [0.949, 0.973]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 1.2% [0.6, 1.8] |
| Unmatched predicted claims | 1.2% [0.6, 1.8] |
| Omission rate | 5.2% [4.2, 6.2] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 90.6% [89.4, 91.8] |
| Numeric grounding rate | 97.6% [96.7, 98.3] |
| Action-item due date exact or within 3 days | 98.6% |
| Hallucinated claims (total) | 19 |
| ... surfaced to the adviser as unsupported | 19 (100.0%) |
| Unsupported flags left in final notes | 53 |
| Repair pass: cited / dropped | 78 / 48 |
| Small-talk segments cited | 6 |
| Hallucination-free meetings | 85 / 100 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| extract_then_compose | single_shot | macro_f1 | 0.944 | 0.955 | -0.011 | [-0.030, +0.007] | 0.11 | 13 / 32 | 0.007 | inconclusive |
| extract_then_compose | single_shot | decisions_f1 | 0.879 | 0.911 | -0.031 | [-0.097, +0.028] | 0.18 | 14 / 21 | 0.311 | inconclusive |
| extract_then_compose | single_shot | action_items_f1 | 0.955 | 0.970 | -0.015 | [-0.040, +0.007] | 0.09 | 10 / 16 | 0.327 | inconclusive |
| extract_then_compose | single_shot | hallucination_rate | 0.041 | 0.022 | +0.019 | [+0.009, +0.029] | 0.00 | 18 / 43 | 0.002 | worse |
| verified | single_shot | macro_f1 | 0.962 | 0.955 | +0.007 | [-0.010, +0.024] | 0.78 | 26 / 10 | 0.011 | inconclusive |
| verified | single_shot | decisions_f1 | 0.952 | 0.911 | +0.041 | [-0.009, +0.098] | 0.93 | 17 / 9 | 0.169 | inconclusive |
| verified | single_shot | action_items_f1 | 0.955 | 0.970 | -0.015 | [-0.040, +0.007] | 0.09 | 10 / 16 | 0.327 | inconclusive |
| verified | single_shot | hallucination_rate | 0.012 | 0.022 | -0.010 | [-0.019, -0.001] | 0.99 | 27 / 14 | 0.060 | better |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

