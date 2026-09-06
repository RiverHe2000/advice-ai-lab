# Monitor self-evaluation

Scenarios: steady, latency_spike, error_burst, regressed_prompt, topic_shift, cost_creep, pii_leak; seeds: [1, 2, 3]; 240 simulated minutes per run.

| Incident kind | Runs | Detected | Detection rate [95% CI] | Time-to-detect (min) mean [95% CI] | TTD values |
|---|---:|---:|---|---|---|
| cost_creep | 3 | 3 | 1.00 [1.0, 1.0] | 8.3 [5.0, 10.0] | 10, 10, 5 |
| error_burst | 3 | 3 | 1.00 [1.0, 1.0] | 5.0 [5.0, 5.0] | 5, 5, 5 |
| latency_spike | 3 | 3 | 1.00 [1.0, 1.0] | 13.3 [10.0, 20.0] | 10, 10, 20 |
| pii_leak | 3 | 3 | 1.00 [1.0, 1.0] | 5.0 [5.0, 5.0] | 5, 5, 5 |
| regressed_prompt | 3 | 3 | 1.00 [1.0, 1.0] | 6.7 [5.0, 10.0] | 5, 10, 5 |
| topic_shift | 3 | 3 | 1.00 [1.0, 1.0] | 13.3 [5.0, 20.0] | 15, 20, 5 |

False-alarm rate on quiet ticks: **0.0022** [0.0, 0.0066] (1/459 ticks)

False alarms by alert: topic_drift: 1

Gate: detection >= 0.9 for every kind and false alarms <= 0.05 -> **PASS**

## Per-run incidents

| Scenario | Seed | Kind | Window (min) | Detected | TTD (min) | First alert | Alerts during incident |
|---|---:|---|---|---|---:|---|---|
| latency_spike | 1 | latency_spike | 90-130 | yes | 10.0 | latency_p95 | latency_p95 x7 |
| latency_spike | 2 | latency_spike | 90-130 | yes | 10.0 | latency_p95 | latency_p95 x5, topic_drift x2 |
| latency_spike | 3 | latency_spike | 90-130 | yes | 20.0 | latency_p95 | latency_p95 x7 |
| error_burst | 1 | error_burst | 100-130 | yes | 5.0 | error_rate | error_rate x11 |
| error_burst | 2 | error_burst | 100-130 | yes | 5.0 | error_rate | error_rate x8 |
| error_burst | 3 | error_burst | 100-130 | yes | 5.0 | error_rate | error_rate x11 |
| regressed_prompt | 1 | regressed_prompt | 90-150 | yes | 5.0 | quality_mean | grounding_rate x16, json_validity x7, negative_feedback_rate x4, quality_mean x15, refusal_rate x5 |
| regressed_prompt | 2 | regressed_prompt | 90-150 | yes | 10.0 | quality_mean | grounding_rate x13, json_validity x9, negative_feedback_rate x7, quality_mean x13, refusal_rate x9, topic_drift x4 |
| regressed_prompt | 3 | regressed_prompt | 90-150 | yes | 5.0 | grounding_rate | grounding_rate x14, json_validity x11, negative_feedback_rate x3, quality_mean x13, refusal_rate x8, topic_drift x2 |
| topic_shift | 1 | topic_shift | 120-240 | yes | 15.0 | topic_drift | negative_feedback_rate x11, quality_mean x22, refusal_rate x24, topic_drift x17 |
| topic_shift | 2 | topic_shift | 120-240 | yes | 20.0 | topic_drift | error_rate x3, negative_feedback_rate x5, quality_mean x18, refusal_rate x23, topic_drift x16 |
| topic_shift | 3 | topic_shift | 120-240 | yes | 5.0 | topic_drift | negative_feedback_rate x13, quality_mean x20, refusal_rate x24, topic_drift x24 |
| cost_creep | 1 | cost_creep | 90-180 | yes | 10.0 | cost_per_request | cost_per_request x19 |
| cost_creep | 2 | cost_creep | 90-180 | yes | 10.0 | cost_per_request | cost_per_request x19, topic_drift x3 |
| cost_creep | 3 | cost_creep | 90-180 | yes | 5.0 | cost_per_request | cost_per_request x20 |
| pii_leak | 1 | pii_leak | 100-140 | yes | 5.0 | pii_leak_rate | pii_leak_rate x10, topic_drift x1 |
| pii_leak | 2 | pii_leak | 100-140 | yes | 5.0 | pii_leak_rate | pii_leak_rate x10, topic_drift x3 |
| pii_leak | 3 | pii_leak | 100-140 | yes | 5.0 | pii_leak_rate | pii_leak_rate x10 |

## Quiet ticks per run

| Scenario | Seed | Requests | Ticks | Quiet ticks | Quiet ticks with an alert |
|---|---:|---:|---:|---:|---:|
| steady | 1 | 1140 | 48 | 47 | 1 |
| steady | 2 | 1214 | 48 | 47 | 0 |
| steady | 3 | 1236 | 48 | 47 | 0 |
| latency_spike | 1 | 1266 | 48 | 16 | 0 |
| latency_spike | 2 | 1199 | 48 | 16 | 0 |
| latency_spike | 3 | 1203 | 48 | 16 | 0 |
| error_burst | 1 | 1175 | 48 | 18 | 0 |
| error_burst | 2 | 1261 | 48 | 18 | 0 |
| error_burst | 3 | 1184 | 48 | 18 | 0 |
| regressed_prompt | 1 | 1168 | 48 | 16 | 0 |
| regressed_prompt | 2 | 1206 | 48 | 16 | 0 |
| regressed_prompt | 3 | 1231 | 48 | 16 | 0 |
| topic_shift | 1 | 1215 | 48 | 22 | 0 |
| topic_shift | 2 | 1162 | 48 | 22 | 0 |
| topic_shift | 3 | 1196 | 48 | 22 | 0 |
| cost_creep | 1 | 1212 | 48 | 16 | 0 |
| cost_creep | 2 | 1244 | 48 | 16 | 0 |
| cost_creep | 3 | 1226 | 48 | 16 | 0 |
| pii_leak | 1 | 1255 | 48 | 18 | 0 |
| pii_leak | 2 | 1172 | 48 | 18 | 0 |
| pii_leak | 3 | 1128 | 48 | 18 | 0 |
