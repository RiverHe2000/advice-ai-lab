# Real model Qwen/Qwen2.5-1.5B-Instruct: rules vs llm vs llm_validated on 40 SoAs

Settings: corpus=data\corpus, n_docs=40, model=hf, model_name=Qwen/Qwen2.5-1.5B-Instruct, corruption=-, noise=[0.0], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 40 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| llm | 40 | 0.000 [0.000, 0.000] | 0.758 [0.735, 0.783] | 0.211 [0.111, 0.322] | 0.263 [0.138, 0.400] | 42 | 99 | 67 | 0 (0) | 338 | 3720 | 16973 ms |
| llm_validated | 40 | 0.050 [0.000, 0.125] | 0.767 [0.742, 0.792] | 0.231 [0.136, 0.338] | 0.263 [0.138, 0.400] | 46 | 105 | 71 | 46 (10) | 388 | 4495 | 3368 ms |

## Per field (accuracy [95 % CI])

| Field | rules | llm | llm_validated |
|---|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| adviser_name | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| licensee | 1.000 [1.000, 1.000] | 0.850 [0.725, 0.950] | 0.850 [0.725, 0.950] |
| advice_date | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| risk_profile | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| scope | 1.000 [1.000, 1.000] | 0.900 [0.800, 0.975] | 0.900 [0.800, 0.975] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 0.975 [0.925, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 0.975 [0.900, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 0.900 [0.800, 0.975] | 0.925 [0.850, 1.000] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 0.425 [0.275, 0.575] | 0.425 [0.275, 0.575] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 0.725 [0.600, 0.850] | 0.725 [0.600, 0.850] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 0.900 [0.800, 0.975] | 0.900 [0.800, 0.975] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 0.450 [0.300, 0.600] | 0.450 [0.300, 0.600] |
| recommendations | 1.000 [1.000, 1.000] | 0.025 [0.000, 0.075] | 0.075 [0.000, 0.175] |
| replacements | 1.000 [1.000, 1.000] | 0.250 [0.125, 0.400] | 0.250 [0.125, 0.400] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm | 0.219 [0.124, 0.325] | 0.209 [0.113, 0.314] | 0.211 [0.111, 0.322] | 0.263 [0.138, 0.400] | 0.263 [0.125, 0.400] | 0.263 [0.138, 0.400] |
| llm_validated | 0.255 [0.150, 0.378] | 0.221 [0.126, 0.324] | 0.231 [0.136, 0.338] | 0.263 [0.138, 0.400] | 0.263 [0.125, 0.400] | 0.263 [0.138, 0.400] |

## Validator violations by code

| Code | rules | llm | llm_validated |
|---|---:|---:|---:|
| fee_arithmetic | 0 | 4 | 6 |
| fee_basis_inconsistent | 0 | 20 | 20 |
| missing_field | 0 | 15 | 15 |
| product_type_mismatch | 0 | 25 | 22 |
| product_unknown | 0 | 20 | 6 |

## Missing sections (count of documents)

| Section | rules | llm | llm_validated |
|---|---:|---:|---:|
| authority | 5 | 5 | 5 |
| fees | 0 | 1 | 0 |
| recommendations | 0 | 13 | 0 |
| replacement | 4 | 22 | 22 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 40 | 1.000 | 0.000 | +1.000 | [+1.000, +1.000] | 1.00 | 40 / 0 | 0.000 | better |
| rules vs llm_validated | 40 | 1.000 | 0.050 | +0.950 | [+0.875, +1.000] | 1.00 | 38 / 0 | 0.000 | better |
| llm vs llm_validated | 40 | 0.000 | 0.050 | -0.050 | [-0.125, +0.000] | 0.00 | 0 / 2 | 0.500 | inconclusive |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 40 | 1.000 | 0.758 | +0.242 | [+0.217, +0.268] | 1.00 | 40 / 0 | 0.000 | better |
| rules vs llm_validated | 40 | 1.000 | 0.767 | +0.233 | [+0.208, +0.262] | 1.00 | 39 / 0 | 0.000 | better |
| llm vs llm_validated | 40 | 0.758 | 0.767 | -0.008 | [-0.022, +0.000] | 0.00 | 0 / 3 | 0.250 | inconclusive |

## Notes

- The first 40 of the 120 gold SoAs (manifest order); greedy decoding; answers cached per request.
