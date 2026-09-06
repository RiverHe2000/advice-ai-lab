# File-note evaluation report

- created: 2026-09-06T12:14:57+00:00
- corpus: 100 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### verified (verified, fake[p=0.1], corruption 0.1, raw names)

- wall clock 1.3 s; model calls 478; JSON repairs 24; parse failures 0; failed windows 0; failed meetings 0
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

## Gate on `verified`: **PASS**

