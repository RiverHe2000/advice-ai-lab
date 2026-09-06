# Rules extractor on 120 SoAs (clean and noisy text)

Settings: corpus=data\corpus, n_docs=120, model=-, model_name=-, corruption=0.0, noise=[0.0, 0.02, 0.05, 0.1], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| rules@noise0.02 | 120 | 0.158 [0.100, 0.225] | 0.814 [0.787, 0.838] | 0.840 [0.795, 0.881] | 0.714 [0.634, 0.793] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| rules@noise0.05 | 120 | 0.008 [0.000, 0.025] | 0.603 [0.569, 0.634] | 0.641 [0.588, 0.695] | 0.397 [0.314, 0.478] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| rules@noise0.1 | 120 | 0.000 [0.000, 0.000] | 0.365 [0.342, 0.389] | 0.360 [0.301, 0.420] | 0.214 [0.150, 0.285] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |

## Per field (accuracy [95 % CI])

| Field | rules | rules@noise0.02 | rules@noise0.05 | rules@noise0.1 |
|---|---:|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 0.758 [0.683, 0.833] | 0.567 [0.483, 0.658] | 0.267 [0.192, 0.350] |
| adviser_name | 1.000 [1.000, 1.000] | 0.808 [0.733, 0.875] | 0.658 [0.575, 0.742] | 0.358 [0.275, 0.450] |
| licensee | 1.000 [1.000, 1.000] | 0.833 [0.767, 0.900] | 0.675 [0.600, 0.758] | 0.358 [0.283, 0.450] |
| advice_date | 1.000 [1.000, 1.000] | 0.883 [0.825, 0.942] | 0.750 [0.675, 0.825] | 0.567 [0.475, 0.650] |
| risk_profile | 1.000 [1.000, 1.000] | 0.975 [0.942, 1.000] | 0.875 [0.817, 0.933] | 0.750 [0.675, 0.825] |
| scope | 1.000 [1.000, 1.000] | 0.800 [0.725, 0.867] | 0.600 [0.517, 0.692] | 0.417 [0.333, 0.500] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 0.825 [0.758, 0.892] | 0.533 [0.450, 0.617] | 0.175 [0.108, 0.250] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 0.817 [0.750, 0.875] | 0.517 [0.433, 0.608] | 0.133 [0.075, 0.192] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 0.858 [0.792, 0.917] | 0.575 [0.491, 0.658] | 0.175 [0.108, 0.242] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 0.917 [0.867, 0.958] | 0.808 [0.733, 0.875] | 0.633 [0.550, 0.725] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 0.733 [0.642, 0.808] | 0.358 [0.275, 0.442] | 0.100 [0.050, 0.159] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 0.875 [0.817, 0.933] | 0.692 [0.608, 0.775] | 0.500 [0.417, 0.583] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 0.900 [0.842, 0.950] | 0.875 [0.817, 0.933] | 0.775 [0.700, 0.850] |
| recommendations | 1.000 [1.000, 1.000] | 0.550 [0.458, 0.642] | 0.225 [0.150, 0.300] | 0.067 [0.025, 0.117] |
| replacements | 1.000 [1.000, 1.000] | 0.675 [0.583, 0.758] | 0.342 [0.266, 0.425] | 0.200 [0.133, 0.267] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| rules@noise0.02 | 0.870 [0.821, 0.913] | 0.820 [0.774, 0.865] | 0.840 [0.795, 0.881] | 0.725 [0.646, 0.796] | 0.708 [0.628, 0.785] | 0.714 [0.634, 0.793] |
| rules@noise0.05 | 0.715 [0.654, 0.770] | 0.599 [0.543, 0.653] | 0.641 [0.588, 0.695] | 0.414 [0.329, 0.496] | 0.390 [0.307, 0.474] | 0.397 [0.314, 0.478] |
| rules@noise0.1 | 0.452 [0.380, 0.526] | 0.319 [0.263, 0.375] | 0.360 [0.301, 0.420] | 0.214 [0.142, 0.282] | 0.214 [0.146, 0.285] | 0.214 [0.150, 0.285] |

## Validator violations by code

| Code | rules | rules@noise0.02 | rules@noise0.05 | rules@noise0.1 |
|---|---:|---:|---:|---:|
| amount_exceeds_available_funds | 0 | 3 | 8 | 5 |
| fee_arithmetic | 0 | 12 | 19 | 6 |
| missing_field | 0 | 46 | 122 | 244 |
| product_unknown | 0 | 0 | 0 | 1 |
| replacement_reason_missing | 0 | 14 | 13 | 8 |

## Missing sections (count of documents)

| Section | rules | rules@noise0.02 | rules@noise0.05 | rules@noise0.1 |
|---|---:|---:|---:|---:|
| authority | 25 | 25 | 25 | 26 |
| fees | 0 | 0 | 1 | 2 |
| recommendations | 0 | 0 | 0 | 1 |
| replacement | 14 | 14 | 14 | 14 |
| risk | 0 | 0 | 0 | 2 |
| scope | 0 | 0 | 0 | 5 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs rules@noise0.02 | 120 | 1.000 | 0.158 | +0.842 | [+0.775, +0.900] | 1.00 | 101 / 0 | 0.000 | better |
| rules vs rules@noise0.05 | 120 | 1.000 | 0.008 | +0.992 | [+0.975, +1.000] | 1.00 | 119 / 0 | 0.000 | better |
| rules vs rules@noise0.1 | 120 | 1.000 | 0.000 | +1.000 | [+1.000, +1.000] | 1.00 | 120 / 0 | 0.000 | better |
| rules@noise0.02 vs rules@noise0.05 | 120 | 0.158 | 0.008 | +0.150 | [+0.100, +0.217] | 1.00 | 18 / 0 | 0.000 | better |
| rules@noise0.02 vs rules@noise0.1 | 120 | 0.158 | 0.000 | +0.158 | [+0.100, +0.225] | 1.00 | 19 / 0 | 0.000 | better |
| rules@noise0.05 vs rules@noise0.1 | 120 | 0.008 | 0.000 | +0.008 | [+0.000, +0.025] | 0.62 | 1 / 0 | 1.000 | non-inferior |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs rules@noise0.02 | 120 | 1.000 | 0.814 | +0.186 | [+0.161, +0.213] | 1.00 | 112 / 0 | 0.000 | better |
| rules vs rules@noise0.05 | 120 | 1.000 | 0.603 | +0.397 | [+0.364, +0.431] | 1.00 | 120 / 0 | 0.000 | better |
| rules vs rules@noise0.1 | 120 | 1.000 | 0.365 | +0.635 | [+0.609, +0.659] | 1.00 | 120 / 0 | 0.000 | better |
| rules@noise0.02 vs rules@noise0.05 | 120 | 0.814 | 0.603 | +0.211 | [+0.182, +0.238] | 1.00 | 110 / 0 | 0.000 | better |
| rules@noise0.02 vs rules@noise0.1 | 120 | 0.814 | 0.365 | +0.449 | [+0.421, +0.478] | 1.00 | 119 / 0 | 0.000 | better |
| rules@noise0.05 vs rules@noise0.1 | 120 | 0.603 | 0.365 | +0.238 | [+0.208, +0.270] | 1.00 | 110 / 0 | 0.000 | better |

## Notes

- Text comes from the rendered PDFs through pdfplumber; noise is applied to that text.
