# Review router evaluation

40 documents, 247 critical fields; base field error 0.348, base document error 0.925; probabilities are out-of-fold (GroupKFold by document).

| Metric | Value [95 % CI] |
|---|---:|
| ECE of P(field correct) | 0.005 |
| Area under risk-coverage curve (lower is better) | 0.742 [0.530, 1.000] |
| Target residual error | 0.010 |
| Chosen tau | 0.876 |
| Review rate at tau | 0.925 [0.825, 1.000] |
| Residual error at tau | 0.000 [0.000, 0.000] |

## Policies

| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |
|---|---:|---:|
| router@tau | 0.925 [0.825, 1.000] | 0.000 [0.000, 0.000] |
| review_all | 1.000 [1.000, 1.000] | 0.000 [0.000, 0.000] |
| review_none | 0.000 [0.000, 0.000] | 0.925 [0.825, 1.000] |
| review_if_validator_fails | 0.825 [0.700, 0.925] | 0.857 [0.500, 1.000] |

## Reliability table (P(field correct))

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 84 | 0.003 | 0.000 | -0.003 |
| [0.1, 0.2) | 1 | 0.133 | 0.000 | -0.133 |
| [0.2, 0.3) | 0 | - | - | - |
| [0.3, 0.4) | 0 | - | - | - |
| [0.4, 0.5) | 0 | - | - | - |
| [0.5, 0.6) | 0 | - | - | - |
| [0.6, 0.7) | 0 | - | - | - |
| [0.7, 0.8) | 0 | - | - | - |
| [0.8, 0.9) | 2 | 0.868 | 1.000 | +0.132 |
| [0.9, 1.0) | 160 | 0.997 | 0.994 | -0.004 |

## Risk-coverage curve (every 5th point)

| tau | coverage | review rate | residual error |
|---:|---:|---:|---:|
| 1.000 | 0.000 | 1.000 | 0.000 |
| 0.008 | 0.125 | 0.875 | 0.400 |
| 0.000 | 0.250 | 0.750 | 0.700 |
| 0.000 | 0.375 | 0.625 | 0.800 |
| 0.000 | 0.500 | 0.500 | 0.850 |
| 0.000 | 0.625 | 0.375 | 0.880 |
| 0.000 | 0.750 | 0.250 | 0.900 |
| 0.000 | 0.875 | 0.125 | 0.914 |
| 0.000 | 1.000 | 0.000 | 0.925 |

## Logistic-regression coefficients (standardised features)

| Feature | Coefficient |
|---|---:|
| agree_rules | +2.918 |
| kind_risk_profile | +0.789 |
| kind_replacement | -0.774 |
| n_parse_failures | -0.674 |
| kind_recommendation | -0.619 |
| amount_log | +0.597 |
| kind_fee_initial | +0.396 |
| kind_fee_ongoing | +0.380 |
| validator_warning | +0.348 |
| fuzzy_score | +0.267 |
| n_repairs | -0.241 |
| has_rules | +0.217 |
| has_self_conf | -0.206 |
| self_conf | -0.143 |
| len_z | +0.085 |
| validator_error | -0.058 |
| section_found | +0.000 |

## Notes

- Labels from the real llm_validated extractions on 40 SoAs; model answers served from the run-10 cache.
