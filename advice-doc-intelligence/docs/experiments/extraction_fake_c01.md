# Mechanism check: scripted model, corruption 0.1

Settings: corpus=data\corpus, n_docs=120, model=fake, model_name=-, corruption=0.1, noise=[0.0], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| llm | 120 | 0.725 [0.650, 0.800] | 0.961 [0.951, 0.971] | 0.973 [0.955, 0.988] | 0.968 [0.935, 0.990] | 165 | 20 | 19 | 0 (0) | 820 | 1312 | 1 ms |
| llm_validated | 120 | 0.817 [0.742, 0.883] | 0.975 [0.967, 0.982] | 0.981 [0.967, 0.993] | 0.968 [0.935, 0.990] | 167 | 20 | 19 | 23 (19) | 843 | 1356 | 2 ms |

## Per field (accuracy [95 % CI])

| Field | rules | llm | llm_validated |
|---|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 0.958 [0.925, 0.992] | 1.000 [1.000, 1.000] |
| adviser_name | 1.000 [1.000, 1.000] | 0.925 [0.875, 0.967] | 0.958 [0.925, 0.992] |
| licensee | 1.000 [1.000, 1.000] | 0.967 [0.933, 0.992] | 1.000 [1.000, 1.000] |
| advice_date | 1.000 [1.000, 1.000] | 0.958 [0.925, 0.992] | 1.000 [1.000, 1.000] |
| risk_profile | 1.000 [1.000, 1.000] | 0.958 [0.917, 0.992] | 0.958 [0.917, 0.992] |
| scope | 1.000 [1.000, 1.000] | 0.900 [0.842, 0.950] | 0.900 [0.842, 0.950] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 0.975 [0.942, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 0.983 [0.958, 1.000] | 1.000 [1.000, 1.000] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 0.983 [0.958, 1.000] | 0.975 [0.942, 1.000] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 0.992 [0.975, 1.000] | 0.992 [0.975, 1.000] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 0.967 [0.933, 0.992] | 0.967 [0.933, 0.992] |
| recommendations | 1.000 [1.000, 1.000] | 0.908 [0.850, 0.950] | 0.933 [0.883, 0.975] |
| replacements | 1.000 [1.000, 1.000] | 0.942 [0.900, 0.983] | 0.942 [0.900, 0.983] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm | 0.988 [0.977, 0.997] | 0.965 [0.941, 0.985] | 0.973 [0.955, 0.988] | 0.972 [0.943, 0.993] | 0.965 [0.935, 0.989] | 0.968 [0.935, 0.990] |
| llm_validated | 0.997 [0.992, 1.000] | 0.974 [0.952, 0.992] | 0.981 [0.967, 0.993] | 0.972 [0.943, 0.993] | 0.965 [0.935, 0.989] | 0.968 [0.935, 0.990] |

## Validator violations by code

| Code | rules | llm | llm_validated |
|---|---:|---:|---:|
| amount_exceeds_available_funds | 0 | 2 | 0 |
| date_implausible | 0 | 1 | 0 |
| fee_arithmetic | 0 | 5 | 4 |
| fee_basis_inconsistent | 0 | 5 | 0 |
| missing_field | 0 | 13 | 0 |
| product_unknown | 0 | 1 | 0 |
| replacement_reason_missing | 0 | 3 | 3 |

## Missing sections (count of documents)

| Section | rules | llm | llm_validated |
|---|---:|---:|---:|
| authority | 25 | 26 | 26 |
| replacement | 14 | 14 | 14 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 0.725 | +0.275 | [+0.200, +0.358] | 1.00 | 33 / 0 | 0.000 | better |
| rules vs llm_validated | 120 | 1.000 | 0.817 | +0.183 | [+0.117, +0.258] | 1.00 | 22 / 0 | 0.000 | better |
| llm vs llm_validated | 120 | 0.725 | 0.817 | -0.092 | [-0.150, -0.050] | 0.00 | 0 / 11 | 0.001 | worse |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 0.961 | +0.039 | [+0.029, +0.050] | 1.00 | 48 / 0 | 0.000 | better |
| rules vs llm_validated | 120 | 1.000 | 0.975 | +0.025 | [+0.018, +0.033] | 1.00 | 37 / 0 | 0.000 | better |
| llm vs llm_validated | 120 | 0.961 | 0.975 | -0.014 | [-0.022, -0.008] | 0.00 | 0 / 17 | 0.000 | worse |

## Notes

- MECHANISM CHECK, not a model result: the fake backend answers from the gold with corruption probability 0.1 per section.
