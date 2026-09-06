# Review router evaluation

40 documents, 328 critical fields; base field error 0.034, base document error 0.275; probabilities are out-of-fold (GroupKFold by document).

| Metric | Value [95 % CI] |
|---|---:|
| ECE of P(field correct) | 0.002 |
| Area under risk-coverage curve (lower is better) | 0.045 [0.010, 0.098] |
| Target residual error | 0.010 |
| Chosen tau | 0.995 |
| Review rate at tau | 0.275 [0.125, 0.400] |
| Residual error at tau | 0.000 [0.000, 0.000] |

## Policies

| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |
|---|---:|---:|
| router@tau | 0.275 [0.125, 0.400] | 0.000 [0.000, 0.000] |
| review_all | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |
| review_none | 0.000 [0.000, 0.000] | 0.275 [0.150, 0.425] |
| review_if_validator_fails | 0.025 [0.000, 0.075] | 0.256 [0.128, 0.400] |

## Reliability table (P(field correct))

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 9 | 0.003 | 0.000 | -0.003 |
| [0.1, 0.2) | 0 | - | - | - |
| [0.2, 0.3) | 1 | 0.259 | 0.000 | -0.259 |
| [0.3, 0.4) | 1 | 0.332 | 0.000 | -0.332 |
| [0.4, 0.5) | 0 | - | - | - |
| [0.5, 0.6) | 0 | - | - | - |
| [0.6, 0.7) | 0 | - | - | - |
| [0.7, 0.8) | 0 | - | - | - |
| [0.8, 0.9) | 0 | - | - | - |
| [0.9, 1.0) | 317 | 1.000 | 1.000 | +0.000 |

## Risk-coverage curve (every 5th point)

| tau | coverage | review rate | residual error |
|---:|---:|---:|---:|
| 1.000 | 0.000 | 1.000 | 0.000 |
| 1.000 | 0.125 | 0.875 | 0.000 |
| 1.000 | 0.250 | 0.750 | 0.000 |
| 1.000 | 0.375 | 0.625 | 0.000 |
| 1.000 | 0.500 | 0.500 | 0.000 |
| 0.998 | 0.625 | 0.375 | 0.000 |
| 0.332 | 0.750 | 0.250 | 0.033 |
| 0.006 | 0.875 | 0.125 | 0.171 |
| 0.000 | 1.000 | 0.000 | 0.275 |

## Logistic-regression coefficients (standardised features)

| Feature | Coefficient |
|---|---:|
| agree_rules | +1.590 |
| kind_replacement | -0.345 |
| n_parse_failures | -0.220 |
| amount_log | +0.220 |
| self_conf | +0.206 |
| has_self_conf | +0.202 |
| fuzzy_score | +0.174 |
| kind_risk_profile | +0.152 |
| len_z | +0.117 |
| kind_fee_initial | +0.098 |
| kind_fee_ongoing | +0.094 |
| validator_error | -0.073 |
| kind_recommendation | +0.012 |
| has_rules | +0.000 |
| validator_warning | +0.000 |
| n_repairs | +0.000 |
| section_found | +0.000 |

## Notes

- Labels from the real llm_validated extractions on 40 SoAs; model answers served from the run-10 cache.
