# File-note evaluation report

- created: 2026-09-27T03:42:45+00:00
- metric definition: gold_disagreement_v2
- v2 counts every gold-unmatched predicted claim regardless of verifier output; matching requires numbers/dates to agree and owners to agree for actions. This is an approximate reference-matching measure, not human-adjudicated hallucination recall. Legacy v1 reports conditioned the denominator on verifier detection and are not comparable.
- corpus: 100 meetings, seed 11
- intervals: 95 % bootstrap over meetings, 1000 resamples; the gate uses the conservative bound

## Runs

### single_shot (single_shot, fake[p=0.3], corruption 0.3, raw names)

- wall clock 0.7 s; model calls 110; JSON repairs 25; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 112436, completion 32526; latency per meeting 0.001 [0.001, 0.001] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.900 [0.840, 0.950] | 0.798 [0.737, 0.855] | **0.834 [0.774, 0.887]** |
| goals | 0.835 [0.770, 0.888] | 0.780 [0.712, 0.837] | **0.798 [0.735, 0.852]** |
| decisions | 0.675 [0.602, 0.746] | 0.885 [0.828, 0.938] | **0.719 [0.651, 0.783]** |
| action_items | 0.934 [0.905, 0.962] | 0.876 [0.838, 0.912] | **0.899 [0.868, 0.930]** |
| topics_discussed | | | 0.795 [0.754, 0.831] |
| advice_discussed | | | 0.885 [0.840, 0.924] |
| vulnerability_indicators | | | 0.990 [0.970, 1.000] |
| follow_up | | | 0.820 [0.740, 0.890] |
| **macro F1 (4 primary sections)** | | | **0.812 [0.783, 0.840]** |

| Metric | Value |
|---|---:|
| Gold-disagreement rate (independent of verifier; legacy key hallucination_rate) | 13.1% [11.5, 14.8] |
| Unmatched predicted claims | 13.1% [11.5, 14.8] |
| Omission rate | 17.1% [15.4, 18.9] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 72.2% [69.9, 74.3] |
| Numeric grounding rate | 92.6% [91.0, 94.0] |
| Action-item due date exact or within 3 days | 92.2% |
| Hallucinated claims (total) | 213 |
| ... surfaced to the adviser as unsupported | 0 (0.0%) |
| Unsupported flags left in final notes | 0 |
| Repair pass: cited / dropped | 0 / 0 |
| Small-talk segments cited | 79 |
| Hallucination-free meetings | 12 / 100 |

### verified_single_shot (verified_single_shot, fake[p=0.3], corruption 0.3, raw names)

- wall clock 1.5 s; model calls 209; JSON repairs 47; parse failures 0; failed windows 0; failed meetings 0
- tokens: prompt 163502, completion 35023; latency per meeting 0.009 [0.008, 0.009] s

| Section | Precision | Recall | F1 |
|---|---:|---:|---:|
| circumstance_changes | 0.900 [0.840, 0.950] | 0.798 [0.737, 0.855] | **0.834 [0.774, 0.887]** |
| goals | 0.835 [0.770, 0.888] | 0.780 [0.712, 0.837] | **0.798 [0.735, 0.852]** |
| decisions | 0.848 [0.782, 0.908] | 0.885 [0.828, 0.938] | **0.849 [0.792, 0.907]** |
| action_items | 0.934 [0.905, 0.962] | 0.876 [0.838, 0.912] | **0.899 [0.868, 0.930]** |
| topics_discussed | | | 0.815 [0.774, 0.851] |
| advice_discussed | | | 0.885 [0.840, 0.924] |
| vulnerability_indicators | | | 0.990 [0.970, 1.000] |
| follow_up | | | 0.820 [0.740, 0.890] |
| **macro F1 (4 primary sections)** | | | **0.845 [0.816, 0.872]** |

| Metric | Value |
|---|---:|
| Gold-disagreement rate (independent of verifier; legacy key hallucination_rate) | 9.7% [8.3, 11.1] |
| Unmatched predicted claims | 9.7% [8.3, 11.1] |
| Omission rate | 17.1% [15.4, 18.9] |
| Compliance flags accuracy | 100.0% [100.0, 100.0] |
| Verifier-supported fraction | 83.8% [82.1, 85.5] |
| Numeric grounding rate | 93.0% [91.4, 94.3] |
| Action-item due date exact or within 3 days | 92.2% |
| Hallucinated claims (total) | 149 |
| ... surfaced to the adviser as unsupported | 143 (96.0%) |
| Unsupported flags left in final notes | 164 |
| Repair pass: cited / dropped | 284 / 64 |
| Small-talk segments cited | 16 |
| Hallucination-free meetings | 22 / 100 |

## Paired comparisons (same transcripts)

| A | B | Metric | A | B | A - B | 95% CI | P(A>B) | wins / losses | McNemar p | Verdict |
|---|---|---|---:|---:|---:|:---:|---:|---:|---:|---|
| verified_single_shot | single_shot | macro_f1 | 0.845 | 0.812 | +0.033 | [+0.021, +0.046] | 1.00 | 10 / 0 | 0.002 | better |
| verified_single_shot | single_shot | decisions_f1 | 0.849 | 0.719 | +0.131 | [+0.086, +0.184] | 1.00 | 32 / 0 | 0.000 | better |
| verified_single_shot | single_shot | action_items_f1 | 0.899 | 0.899 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| verified_single_shot | single_shot | hallucination_rate | 0.097 | 0.131 | -0.035 | [-0.043, -0.027] | 1.00 | 50 / 0 | 0.000 | better |

McNemar pairs are the binary per-meeting outcome *hallucination-free note* (reported on the macro-F1 row); other rows use the sign of the per-meeting difference.
