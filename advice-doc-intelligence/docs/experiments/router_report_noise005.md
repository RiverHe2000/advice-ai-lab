# Review router evaluation

120 documents, 972 critical fields; base field error 0.044, base document error 0.308; probabilities are out-of-fold (GroupKFold by document).

| Metric | Value [95 % CI] |
|---|---:|
| ECE of P(field correct) | 0.015 |
| Area under risk-coverage curve (lower is better) | 0.118 [0.058, 0.204] |
| Target residual error | 0.010 |
| Chosen tau | 1.000 |
| Review rate at tau | 0.992 [0.975, 1.000] |
| Residual error at tau | 0.000 [0.000, 0.000] |

## Policies

| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |
|---|---:|---:|
| router@tau | 0.992 [0.975, 1.000] | 0.000 [0.000, 0.000] |
| review_all | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |
| review_none | 0.000 [0.000, 0.000] | 0.308 [0.233, 0.392] |
| review_if_validator_fails | 0.158 [0.092, 0.225] | 0.307 [0.220, 0.400] |

## Reliability table (P(field correct))

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 1 | 0.053 | 0.000 | -0.053 |
| [0.1, 0.2) | 6 | 0.135 | 0.000 | -0.135 |
| [0.2, 0.3) | 6 | 0.254 | 0.000 | -0.254 |
| [0.3, 0.4) | 7 | 0.340 | 0.857 | +0.517 |
| [0.4, 0.5) | 5 | 0.438 | 0.600 | +0.162 |
| [0.5, 0.6) | 11 | 0.552 | 0.364 | -0.189 |
| [0.6, 0.7) | 9 | 0.649 | 0.889 | +0.239 |
| [0.7, 0.8) | 24 | 0.759 | 0.667 | -0.092 |
| [0.8, 0.9) | 35 | 0.847 | 0.857 | +0.010 |
| [0.9, 1.0) | 868 | 0.992 | 0.993 | +0.001 |

## Risk-coverage curve (every 5th point)

| tau | coverage | review rate | residual error |
|---:|---:|---:|---:|
| 1.000 | 0.000 | 1.000 | 0.000 |
| 0.994 | 0.042 | 0.958 | 0.200 |
| 0.991 | 0.083 | 0.917 | 0.100 |
| 0.981 | 0.125 | 0.875 | 0.067 |
| 0.981 | 0.167 | 0.833 | 0.050 |
| 0.980 | 0.208 | 0.792 | 0.040 |
| 0.978 | 0.250 | 0.750 | 0.033 |
| 0.970 | 0.292 | 0.708 | 0.029 |
| 0.966 | 0.333 | 0.667 | 0.050 |
| 0.958 | 0.375 | 0.625 | 0.044 |
| 0.933 | 0.417 | 0.583 | 0.040 |
| 0.917 | 0.458 | 0.542 | 0.036 |
| 0.829 | 0.500 | 0.500 | 0.033 |
| 0.807 | 0.542 | 0.458 | 0.046 |
| 0.781 | 0.583 | 0.417 | 0.086 |
| 0.765 | 0.625 | 0.375 | 0.120 |
| 0.720 | 0.667 | 0.333 | 0.150 |
| 0.657 | 0.708 | 0.292 | 0.153 |
| 0.596 | 0.750 | 0.250 | 0.144 |
| 0.546 | 0.792 | 0.208 | 0.168 |
| 0.460 | 0.833 | 0.167 | 0.190 |
| 0.330 | 0.875 | 0.125 | 0.210 |
| 0.255 | 0.917 | 0.083 | 0.245 |
| 0.158 | 0.958 | 0.042 | 0.278 |
| 0.053 | 1.000 | 0.000 | 0.308 |

## Logistic-regression coefficients (standardised features)

| Feature | Coefficient |
|---|---:|
| agree_rules | +1.871 |
| amount_log | +1.697 |
| self_conf | +1.193 |
| kind_fee_initial | +0.733 |
| validator_warning | +0.638 |
| n_repairs | +0.548 |
| has_self_conf | -0.493 |
| kind_recommendation | -0.438 |
| validator_error | +0.293 |
| section_found | +0.289 |
| kind_replacement | -0.251 |
| n_parse_failures | +0.199 |
| kind_risk_profile | +0.123 |
| len_z | +0.099 |
| kind_fee_ongoing | +0.089 |
| has_rules | +0.000 |
| fuzzy_score | +0.000 |

## Notes

- MECHANISM CHECK on OCR-noisy text (5 % character noise): the rules extractor is no longer an oracle.
