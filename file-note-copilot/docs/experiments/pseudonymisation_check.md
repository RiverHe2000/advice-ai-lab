# File-note evaluation report

- created: 2026-09-06T12:14:55+00:00
- corpus: 100 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### verified+pseud (verified, fake[p=0.3], corruption 0.3, pseudonymised)

- wall clock 1.5 s; model calls 531; JSON repairs 88; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 269268, completion 70456; latency per meeting 0.011 [0.010, 0.011] s

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

### verified (verified, fake[p=0.3], corruption 0.3, raw names)

- wall clock 1.4 s; model calls 531; JSON repairs 88; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 277500, completion 70857; latency per meeting 0.011 [0.010, 0.011] s

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
| verified | verified+pseud | macro_f1 | 0.893 | 0.893 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| verified | verified+pseud | decisions_f1 | 0.895 | 0.895 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| verified | verified+pseud | action_items_f1 | 0.917 | 0.917 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| verified | verified+pseud | hallucination_rate | 0.048 | 0.048 | -0.000 | [-0.000, -0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.

