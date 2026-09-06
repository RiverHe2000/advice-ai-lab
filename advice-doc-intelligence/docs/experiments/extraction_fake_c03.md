# Mechanism check: scripted model, corruption 0.3

Settings: corpus=data\corpus, n_docs=120, model=fake, model_name=-, corruption=0.3, noise=[0.0], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| llm | 120 | 0.358 [0.275, 0.442] | 0.890 [0.876, 0.903] | 0.926 [0.904, 0.950] | 0.911 [0.860, 0.953] | 185 | 61 | 56 | 0 (0) | 857 | 1364 | 1 ms |
| llm_validated | 120 | 0.508 [0.417, 0.600] | 0.925 [0.914, 0.937] | 0.939 [0.916, 0.960] | 0.911 [0.860, 0.953] | 191 | 61 | 56 | 58 (44) | 915 | 1474 | 2 ms |

## Per field (accuracy [95 % CI])

| Field | rules | llm | llm_validated |
|---|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 0.925 [0.875, 0.967] | 0.983 [0.958, 1.000] |
| adviser_name | 1.000 [1.000, 1.000] | 0.850 [0.791, 0.908] | 0.933 [0.892, 0.975] |
| licensee | 1.000 [1.000, 1.000] | 0.900 [0.842, 0.950] | 0.983 [0.958, 1.000] |
| advice_date | 1.000 [1.000, 1.000] | 0.858 [0.792, 0.917] | 0.975 [0.942, 1.000] |
| risk_profile | 1.000 [1.000, 1.000] | 0.867 [0.800, 0.925] | 0.867 [0.800, 0.925] |
| scope | 1.000 [1.000, 1.000] | 0.750 [0.675, 0.825] | 0.750 [0.675, 0.825] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 0.958 [0.925, 0.992] | 0.983 [0.958, 1.000] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 0.942 [0.900, 0.975] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 0.958 [0.925, 0.992] | 1.000 [1.000, 1.000] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 0.925 [0.875, 0.967] | 0.933 [0.892, 0.975] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 0.958 [0.925, 0.992] | 0.958 [0.925, 0.992] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 0.850 [0.792, 0.908] | 0.850 [0.792, 0.908] |
| recommendations | 1.000 [1.000, 1.000] | 0.733 [0.658, 0.808] | 0.783 [0.708, 0.850] |
| replacements | 1.000 [1.000, 1.000] | 0.875 [0.808, 0.925] | 0.875 [0.808, 0.925] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm | 0.971 [0.955, 0.984] | 0.904 [0.872, 0.934] | 0.926 [0.904, 0.950] | 0.918 [0.865, 0.960] | 0.907 [0.860, 0.951] | 0.911 [0.860, 0.953] |
| llm_validated | 0.984 [0.972, 0.994] | 0.917 [0.887, 0.947] | 0.939 [0.916, 0.960] | 0.918 [0.865, 0.960] | 0.907 [0.860, 0.951] | 0.911 [0.860, 0.953] |

## Validator violations by code

| Code | rules | llm | llm_validated |
|---|---:|---:|---:|
| amount_exceeds_available_funds | 0 | 3 | 0 |
| date_implausible | 0 | 5 | 1 |
| fee_arithmetic | 0 | 16 | 11 |
| fee_basis_inconsistent | 0 | 12 | 0 |
| missing_field | 0 | 31 | 4 |
| product_unknown | 0 | 3 | 0 |
| replacement_reason_missing | 0 | 12 | 12 |

## Missing sections (count of documents)

| Section | rules | llm | llm_validated |
|---|---:|---:|---:|
| authority | 25 | 28 | 28 |
| replacement | 14 | 14 | 14 |
| scope | 0 | 2 | 2 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 0.358 | +0.642 | [+0.550, +0.725] | 1.00 | 77 / 0 | 0.000 | better |
| rules vs llm_validated | 120 | 1.000 | 0.508 | +0.492 | [+0.408, +0.583] | 1.00 | 59 / 0 | 0.000 | better |
| llm vs llm_validated | 120 | 0.358 | 0.508 | -0.150 | [-0.217, -0.091] | 0.00 | 0 / 18 | 0.000 | worse |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 0.890 | +0.110 | [+0.096, +0.125] | 1.00 | 97 / 0 | 0.000 | better |
| rules vs llm_validated | 120 | 1.000 | 0.925 | +0.075 | [+0.064, +0.087] | 1.00 | 87 / 0 | 0.000 | better |
| llm vs llm_validated | 120 | 0.890 | 0.925 | -0.035 | [-0.048, -0.023] | 0.00 | 2 / 40 | 0.000 | worse |

## Notes

- MECHANISM CHECK, not a model result: the fake backend answers from the gold with corruption probability 0.3 per section.
