# Real model D:/models/Qwen3-4B-Instruct-2507: rules vs llm vs llm_validated on 40 SoAs

Settings: corpus=data\corpus, n_docs=40, model=hf, model_name=D:/models/Qwen3-4B-Instruct-2507, corruption=-, noise=[0.0], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 40 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| llm | 40 | 0.725 [0.600, 0.850] | 0.945 [0.930, 0.960] | 0.982 [0.953, 1.000] | 0.775 [0.650, 0.900] | 0 | 34 | 25 | 0 (0) | 296 | 3020 | 23117 ms |
| llm_validated | 40 | 0.725 [0.599, 0.850] | 0.945 [0.928, 0.960] | 0.989 [0.970, 1.000] | 0.775 [0.650, 0.900] | 0 | 34 | 25 | 7 (6) | 303 | 3124 | 1254 ms |

## Per field (accuracy [95 % CI])

| Field | rules | llm | llm_validated |
|---|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| adviser_name | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| licensee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| advice_date | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| risk_profile | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| scope | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 0.450 [0.300, 0.600] | 0.450 [0.300, 0.600] |
| recommendations | 1.000 [1.000, 1.000] | 0.950 [0.875, 1.000] | 0.950 [0.875, 1.000] |
| replacements | 1.000 [1.000, 1.000] | 0.775 [0.625, 0.900] | 0.775 [0.625, 0.900] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm | 0.982 [0.953, 1.000] | 0.982 [0.953, 1.000] | 0.982 [0.953, 1.000] | 0.775 [0.650, 0.900] | 0.775 [0.625, 0.900] | 0.775 [0.650, 0.900] |
| llm_validated | 0.989 [0.972, 1.000] | 0.989 [0.971, 1.000] | 0.989 [0.970, 1.000] | 0.775 [0.650, 0.900] | 0.775 [0.625, 0.900] | 0.775 [0.650, 0.900] |

## Validator violations by code

| Code | rules | llm | llm_validated |
|---|---:|---:|---:|
| product_type_mismatch | 0 | 7 | 0 |
| product_unknown | 0 | 2 | 1 |

## Missing sections (count of documents)

| Section | rules | llm | llm_validated |
|---|---:|---:|---:|
| authority | 5 | 5 | 5 |
| replacement | 4 | 13 | 13 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 40 | 1.000 | 0.725 | +0.275 | [+0.150, +0.425] | 1.00 | 11 / 0 | 0.001 | better |
| rules vs llm_validated | 40 | 1.000 | 0.725 | +0.275 | [+0.125, +0.400] | 1.00 | 11 / 0 | 0.001 | better |
| llm vs llm_validated | 40 | 0.725 | 0.725 | +0.000 | [-0.075, +0.075] | 0.33 | 1 / 1 | 1.000 | inconclusive |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 40 | 1.000 | 0.945 | +0.055 | [+0.040, +0.070] | 1.00 | 25 / 0 | 0.000 | better |
| rules vs llm_validated | 40 | 1.000 | 0.945 | +0.055 | [+0.040, +0.070] | 1.00 | 25 / 0 | 0.000 | better |
| llm vs llm_validated | 40 | 0.945 | 0.945 | +0.000 | [-0.005, +0.005] | 0.33 | 1 / 1 | 1.000 | inconclusive |

## Notes

- The first 40 of the 120 gold SoAs (manifest order); greedy decoding; answers cached per request.
