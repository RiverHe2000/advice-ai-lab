# File-note evaluation report

- created: 2026-09-06T12:14:52+00:00
- corpus: 100 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### single_shot (single_shot, fake[p=0.3], corruption 0.3, raw names)

- wall clock 0.5 s; model calls 110; JSON repairs 25; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 112436, completion 32526; latency per meeting 0.001 [0.001, 0.001] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.950 [0.900, 0.990] | 0.840 [0.785, 0.892] | **0.878 [0.829, 0.923]** |
| goals | 0.970 [0.930, 1.000] | 0.898 [0.850, 0.940] | **0.923 [0.882, 0.958]** |
| decisions | 0.697 [0.627, 0.764] | 0.925 [0.877, 0.970] | **0.745 [0.684, 0.805]** |
| action_items | 0.934 [0.905, 0.962] | 0.876 [0.838, 0.912] | **0.899 [0.868, 0.930]** |
| topics_discussed | | | 0.888 [0.860, 0.915] |
| advice_discussed | | | 0.936 [0.902, 0.966] |
| vulnerability_indicators | | | 0.990 [0.970, 1.000] |
| follow_up | | | 0.910 [0.850, 0.960] |
| **macro F1 (4 primary sections)** | | | **0.861 [0.840, 0.883]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 6.8% [5.6, 8.0] |
| Unmatched predicted claims | 7.0% [5.8, 8.2] |
| Omission rate | 11.3% [9.8, 12.8] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 72.2% [69.9, 74.3] |
| Numeric grounding rate | 92.6% [91.0, 94.0] |
| Action-item due date exact or within 3 days | 92.2% |
| Hallucinated claims (total) | 112 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 79 |
| Hallucination-free meetings | 31 / 100 |

### extract_then_compose (extract_then_compose, fake[p=0.3], corruption 0.3, raw names)

- wall clock 0.6 s; model calls 423; JSON repairs 70; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 221692, completion 68299; latency per meeting 0.002 [0.002, 0.002] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.944 [0.897, 0.982] | 0.833 [0.777, 0.885] | **0.869 [0.820, 0.912]** |
| goals | 0.957 [0.913, 0.990] | 0.860 [0.808, 0.908] | **0.892 [0.846, 0.932]** |
| decisions | 0.691 [0.624, 0.759] | 0.944 [0.904, 0.977] | **0.738 [0.676, 0.799]** |
| action_items | 0.945 [0.912, 0.973] | 0.900 [0.863, 0.935] | **0.917 [0.883, 0.949]** |
| topics_discussed | | | 0.782 [0.750, 0.812] |
| advice_discussed | | | 0.933 [0.901, 0.960] |
| vulnerability_indicators | | | 0.950 [0.900, 0.990] |
| follow_up | | | 0.840 [0.770, 0.910] |
| **macro F1 (4 primary sections)** | | | **0.854 [0.829, 0.879]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 11.7% [10.5, 13.1] |
| Unmatched predicted claims | 11.9% [10.7, 13.3] |
| Omission rate | 12.9% [11.2, 14.5] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 70.5% [68.5, 72.4] |
| Numeric grounding rate | 91.9% [90.4, 93.3] |
| Action-item due date exact or within 3 days | 94.5% |
| Hallucinated claims (total) | 195 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 150 |
| Hallucination-free meetings | 9 / 100 |

### verified (verified, fake[p=0.3], corruption 0.3, raw names)

- wall clock 1.4 s; model calls 531; JSON repairs 88; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 277500, completion 70857; latency per meeting 0.010 [0.010, 0.011] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.944 [0.897, 0.982] | 0.833 [0.777, 0.885] | **0.869 [0.820, 0.912]** |
| goals | 0.957 [0.913, 0.990] | 0.860 [0.808, 0.908] | **0.892 [0.846, 0.932]** |
| decisions | 0.901 [0.847, 0.948] | 0.944 [0.904, 0.977] | **0.895 [0.844, 0.941]** |
| action_items | 0.945 [0.912, 0.973] | 0.900 [0.863, 0.935] | **0.917 [0.883, 0.949]** |
| topics_discussed | | | 0.856 [0.824, 0.884] |
| advice_discussed | | | 0.933 [0.901, 0.960] |
| vulnerability_indicators | | | 0.950 [0.900, 0.990] |
| follow_up | | | 0.840 [0.770, 0.910] |
| **macro F1 (4 primary sections)** | | | **0.893 [0.872, 0.913]** |

| Metric | Value |
|---|---:|
| Hallucination rate (no gold match AND verifier-unsupported) | 4.8% [3.7, 6.0] |
| Unmatched predicted claims | 4.9% [3.9, 6.2] |
| Omission rate | 12.9% [11.2, 14.5] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 81.4% [79.4, 83.1] |
| Numeric grounding rate | 92.3% [90.8, 93.6] |
| Action-item due date exact or within 3 days | 94.5% |
| Hallucinated claims (total) | 74 |
| ... surfaced to the adviser as unsupported | 74 (100.0%) |
| Unsupported flags left in final notes | 197 |
| Repair pass: cited / dropped | 226 / 121 |
| Small-talk segments cited | 53 |
| Hallucination-free meetings | 49 / 100 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| extract_then_compose | single_shot | macro_f1 | 0.854 | 0.861 | -0.007 | [-0.041, +0.026] | 0.34 | 5 / 27 | 0.000 | inconclusive |
| extract_then_compose | single_shot | decisions_f1 | 0.738 | 0.745 | -0.007 | [-0.091, +0.073] | 0.42 | 33 / 30 | 0.801 | inconclusive |
| extract_then_compose | single_shot | action_items_f1 | 0.917 | 0.899 | +0.018 | [-0.031, +0.068] | 0.78 | 29 / 21 | 0.322 | inconclusive |
| extract_then_compose | single_shot | hallucination_rate | 0.117 | 0.068 | +0.050 | [+0.033, +0.065] | 0.00 | 20 / 72 | 0.000 | worse |
| verified | single_shot | macro_f1 | 0.893 | 0.861 | +0.032 | [+0.001, +0.063] | 0.98 | 34 / 16 | 0.015 | better |
| verified | single_shot | decisions_f1 | 0.895 | 0.745 | +0.150 | [+0.071, +0.233] | 1.00 | 46 / 14 | 0.000 | better |
| verified | single_shot | action_items_f1 | 0.917 | 0.899 | +0.018 | [-0.031, +0.068] | 0.78 | 29 / 21 | 0.322 | inconclusive |
| verified | single_shot | hallucination_rate | 0.048 | 0.068 | -0.020 | [-0.036, -0.003] | 0.99 | 50 / 30 | 0.033 | better |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

