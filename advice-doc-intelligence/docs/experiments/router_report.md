# Review router evaluation

120 documents, 969 critical fields; base field error 0.042, base document error 0.317; probabilities are out-of-fold (GroupKFold by document).

| Metric | Value [95 % CI] |
|---|---:|
| ECE of P(field correct) | 0.000 |
| Area under risk-coverage curve (lower is better) | 0.058 [0.033, 0.095] |
| Target residual error | 0.010 |
| Chosen tau | 0.984 |
| Review rate at tau | 0.317 [0.242, 0.400] |
| Residual error at tau | 0.000 [0.000, 0.000] |

## Policies

| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |
|---|---:|---:|
| router@tau | 0.317 [0.242, 0.400] | 0.000 [0.000, 0.000] |
| review_all | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |
| review_none | 0.000 [0.000, 0.000] | 0.317 [0.233, 0.408] |
| review_if_validator_fails | 0.092 [0.042, 0.142] | 0.303 [0.223, 0.393] |

## Reliability table (P(field correct))

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 41 | 0.009 | 0.000 | -0.009 |
| [0.1, 0.2) | 0 | - | - | - |
| [0.2, 0.3) | 0 | - | - | - |
| [0.3, 0.4) | 0 | - | - | - |
| [0.4, 0.5) | 0 | - | - | - |
| [0.5, 0.6) | 0 | - | - | - |
| [0.6, 0.7) | 0 | - | - | - |
| [0.7, 0.8) | 0 | - | - | - |
| [0.8, 0.9) | 0 | - | - | - |
| [0.9, 1.0) | 928 | 1.000 | 1.000 | +0.000 |

## Risk-coverage curve (every 5th point)

| tau | coverage | review rate | residual error |
|---:|---:|---:|---:|
| 1.000 | 0.000 | 1.000 | 0.000 |
| 1.000 | 0.042 | 0.958 | 0.000 |
| 1.000 | 0.083 | 0.917 | 0.000 |
| 1.000 | 0.125 | 0.875 | 0.000 |
| 1.000 | 0.167 | 0.833 | 0.000 |
| 1.000 | 0.208 | 0.792 | 0.000 |
| 1.000 | 0.250 | 0.750 | 0.000 |
| 1.000 | 0.292 | 0.708 | 0.000 |
| 1.000 | 0.333 | 0.667 | 0.000 |
| 1.000 | 0.375 | 0.625 | 0.000 |
| 1.000 | 0.417 | 0.583 | 0.000 |
| 1.000 | 0.458 | 0.542 | 0.000 |
| 1.000 | 0.500 | 0.500 | 0.000 |
| 1.000 | 0.542 | 0.458 | 0.000 |
| 1.000 | 0.583 | 0.417 | 0.000 |
| 1.000 | 0.625 | 0.375 | 0.000 |
| 0.997 | 0.667 | 0.333 | 0.000 |
| 0.051 | 0.708 | 0.292 | 0.035 |
| 0.012 | 0.750 | 0.250 | 0.089 |
| 0.004 | 0.792 | 0.208 | 0.137 |
| 0.001 | 0.833 | 0.167 | 0.180 |
| 0.000 | 0.875 | 0.125 | 0.219 |
| 0.000 | 0.917 | 0.083 | 0.255 |
| 0.000 | 0.958 | 0.042 | 0.287 |
| 0.000 | 1.000 | 0.000 | 0.317 |

## Logistic-regression coefficients (standardised features)

| Feature | Coefficient |
|---|---:|
| agree_rules | +2.298 |
| self_conf | +0.259 |
| amount_log | +0.190 |
| kind_fee_initial | +0.113 |
| kind_replacement | -0.101 |
| n_repairs | +0.100 |
| kind_risk_profile | -0.081 |
| has_self_conf | -0.079 |
| validator_warning | +0.068 |
| kind_fee_ongoing | +0.057 |
| validator_error | +0.039 |
| n_parse_failures | +0.021 |
| len_z | -0.021 |
| kind_recommendation | +0.016 |
| has_rules | +0.000 |
| fuzzy_score | +0.000 |
| section_found | +0.000 |

## Notes

- MECHANISM CHECK: labels come from the fake backend at corruption 0.3; the real-model router is produced by the GPU stage.
