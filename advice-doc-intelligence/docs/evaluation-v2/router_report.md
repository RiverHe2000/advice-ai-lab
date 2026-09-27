# Review router evaluation

24 documents, 191 scored fields; base field error 0.021, base document error 0.792; probabilities and threshold are frozen before scoring these documents.
Policy intervals are exact 95% binomial intervals over documents; they assume independent documents. Templated data may violate this assumption. No accepted documents means residual error is unavailable, not zero.

| Metric | Value [95 % CI] |
|---|---:|
| ECE of P(field correct) | 0.000 |
| Area under risk-coverage curve (lower is better) | 0.755 [0.559, 0.943] |
| Target residual error | 0.010 |
| Chosen tau | 1.0001 |
| Review rate at tau | 1.000 [0.858, 1.000] |
| Residual error at tau | n/a |
| Auto-accepted test documents | 0 |
| Target supported by test upper bound | False |

## Policies

| Policy | Review rate [95 % CI] | Residual doc error among auto-accepted [95 % CI] |
|---|---:|---:|
| router@tau | 1.000 [0.858, 1.000] | n/a |
| review_all | 1.000 [0.858, 1.000] | n/a |
| review_none | 0.000 [0.000, 0.142] | 0.792 [0.578, 0.929] |
| review_if_validator_fails | 0.000 [0.000, 0.142] | 0.792 [0.578, 0.929] |

## Reliability table (P(field correct))

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 4 | 0.013 | 0.000 | -0.013 |
| [0.1, 0.2) | 0 | - | - | - |
| [0.2, 0.3) | 0 | - | - | - |
| [0.3, 0.4) | 0 | - | - | - |
| [0.4, 0.5) | 0 | - | - | - |
| [0.5, 0.6) | 0 | - | - | - |
| [0.6, 0.7) | 0 | - | - | - |
| [0.7, 0.8) | 0 | - | - | - |
| [0.8, 0.9) | 0 | - | - | - |
| [0.9, 1.0) | 187 | 1.000 | 1.000 | +0.000 |

## Risk-coverage curve (every 5th point)

| tau | coverage | review rate | residual error |
|---:|---:|---:|---:|
| 1.000 | 0.000 | 1.000 | 0.000 |
| 0.000 | 1.000 | 0.000 | 0.792 |

## Logistic-regression coefficients (standardised features)

| Feature | Coefficient |
|---|---:|
| agree_rules | +2.005 |
| n_repairs | +0.202 |
| kind_risk_profile | -0.171 |
| self_conf | +0.161 |
| kind_fee_initial | +0.108 |
| has_self_conf | -0.088 |
| kind_recommendation | +0.086 |
| amount_log | +0.084 |
| kind_replacement | -0.076 |
| validator_warning | +0.056 |
| len_z | +0.053 |
| validator_error | +0.031 |
| n_parse_failures | +0.017 |
| kind_fee_ongoing | +0.016 |
| has_rules | +0.000 |
| fuzzy_score | +0.000 |
| section_found | +0.000 |

## Notes

- Document split: 72 train / 24 threshold calibration / 24 test; seed 7. All fields of a document stay together.
- The calibration target is empirical, not a population guarantee. Test labels never choose tau or fit the router; report the test upper bound before claiming the target.
- This split does not establish generalisation to unseen template families or real documents.
- Field ECE concerns scored fields only. Document residual error uses every gold-compared schema field, including omitted list items. Gold labels never create inference features.
- Offline synthetic mechanism check; not a real-model or external-template generalisation result.
