# Verifier self-evaluation on planted hallucinations

- meetings: 100; untouched gold claims: 1669
- false-alarm rate (gold claim marked *unsupported*): **0.0% [0.0, 0.0]**
- gold claims marked weak or unsupported: 6.1% [5.2, 7.0]
- intervals: 95 % cluster bootstrap over meetings, 1000 resamples

| Planted hallucination | n | Detected (unsupported) | Flagged (weak or worse) | Reason names the problem |
|---|---:|---:|---:|---:|
| invented_decision | 100 | **100.0% [100.0, 100.0]** | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| changed_number | 100 | **98.0% [95.0, 100.0]** | 98.0% [95.0, 100.0] | 98.0% [95.0, 100.0] |
| wrong_owner | 100 | **100.0% [100.0, 100.0]** | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| wrong_date | 100 | **100.0% [100.0, 100.0]** | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| deferred_as_decided | 100 | **100.0% [100.0, 100.0]** | 100.0% [100.0, 100.0] | 100.0% [100.0, 100.0] |
| wrong_citation | 100 | **100.0% [100.0, 100.0]** | 100.0% [100.0, 100.0] | 99.0% [97.0, 100.0] |
| small_talk_leakage | 100 | **95.0% [90.0, 99.0]** | 95.0% [90.0, 99.0] | 95.0% [90.0, 99.0] |

| Section | Gold claims | False alarms (unsupported) |
|---|---:|---:|
| circumstance_changes | 214 | 0.0% [0.0, 0.0] |
| goals | 206 | 0.0% [0.0, 0.0] |
| topics_discussed | 387 | 0.0% [0.0, 0.0] |
| advice_discussed | 268 | 0.0% [0.0, 0.0] |
| decisions | 132 | 0.0% [0.0, 0.0] |
| action_items | 347 | 0.0% [0.0, 0.0] |
| vulnerability_indicators | 30 | 0.0% [0.0, 0.0] |
| follow_up | 85 | 0.0% [0.0, 0.0] |

Support score calibration (score as P(claim is genuine), genuine = gold claim, not genuine = planted): ECE = 0.050 over 2369 claims.

| Score bin | n | Mean score | Fraction genuine |
|---|---:|---:|---:|
| 0.0-0.1 | 693 | 0.000 | 0.000 |
| 0.5-0.6 | 31 | 0.582 | 1.000 |
| 0.6-0.7 | 70 | 0.622 | 1.000 |
| 0.8-0.9 | 334 | 0.864 | 0.994 |
| 0.9-1.0 | 1241 | 0.967 | 0.996 |

Gate: **PASS**
