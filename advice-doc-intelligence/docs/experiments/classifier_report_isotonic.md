# Document classifier evaluation

Train 495 / test 165 documents; calibration `isotonic`; 0.9 ms per document.

| Metric | Value [95 % CI] |
|---|---:|
| Accuracy | 1.000 [1.000, 1.000] |
| Macro-F1 | 1.000 [1.000, 1.000] |
| ECE (10 bins) | 0.001 |

## Per class

| Class | Support | Precision | Recall | F1 |
|---|---:|---:|---:|---:|
| authority_to_proceed | 15 | 1.000 | 1.000 | 1.000 |
| bank_statement | 15 | 1.000 | 1.000 | 1.000 |
| correspondence | 15 | 1.000 | 1.000 | 1.000 |
| fact_find | 15 | 1.000 | 1.000 | 1.000 |
| fds | 15 | 1.000 | 1.000 | 1.000 |
| fee_consent | 15 | 1.000 | 1.000 | 1.000 |
| insurance_schedule | 15 | 1.000 | 1.000 | 1.000 |
| roa | 15 | 1.000 | 1.000 | 1.000 |
| soa | 30 | 1.000 | 1.000 | 1.000 |
| super_statement | 15 | 1.000 | 1.000 | 1.000 |

## Confusion matrix (rows = gold, columns = predicted incl. unknown)

| gold \ pred | authority_to_proceed | bank_statement | correspondence | fact_find | fds | fee_consent | insurance_schedule | roa | soa | super_statement | unknown |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| authority_to_proceed | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| bank_statement | 0 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| correspondence | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fact_find | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| fds | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 0 | 0 |
| fee_consent | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 0 |
| insurance_schedule | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 |
| roa | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 0 |
| soa | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 30 | 0 | 0 |
| super_statement | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 15 | 0 |

## Reliability table

| Confidence bin | n | Mean confidence | Accuracy | gap |
|---|---:|---:|---:|---:|
| [0.0, 0.1) | 0 | - | - | - |
| [0.1, 0.2) | 0 | - | - | - |
| [0.2, 0.3) | 0 | - | - | - |
| [0.3, 0.4) | 0 | - | - | - |
| [0.4, 0.5) | 0 | - | - | - |
| [0.5, 0.6) | 0 | - | - | - |
| [0.6, 0.7) | 0 | - | - | - |
| [0.7, 0.8) | 0 | - | - | - |
| [0.8, 0.9) | 1 | 0.875 | 1.000 | +0.125 |
| [0.9, 1.0) | 164 | 1.000 | 1.000 | +0.000 |

## Abstain curve

| Threshold | Abstain rate | Accuracy when answered |
|---:|---:|---:|
| 0.00 | 0.000 | 1.000 |
| 0.50 | 0.000 | 1.000 |
| 0.60 | 0.000 | 1.000 |
| 0.70 | 0.000 | 1.000 |
| 0.80 | 0.000 | 1.000 |
| 0.90 | 0.006 | 1.000 |
| 0.95 | 0.006 | 1.000 |
| 0.99 | 0.012 | 1.000 |

## OCR-like noise

| Noise rate | Accuracy | Macro-F1 | ECE | Abstain rate |
|---:|---:|---:|---:|---:|
| 0.05 | 0.994 [0.982, 1.000] | 0.995 [0.983, 1.000] | 0.019 | 0.012 |
| 0.10 | 0.964 [0.933, 0.988] | 0.966 [0.936, 0.988] | 0.037 | 0.024 |

## Metadata rules (first page)

| Field | Accuracy |
|---|---:|
| client_names | 1.000 |
| adviser_name | 1.000 |
| document_date | 1.000 |

| Type | client_names | adviser_name | document_date |
|---|---:|---:|---:|
| authority_to_proceed | 1.000 | 1.000 | 1.000 |
| bank_statement | 1.000 | 1.000 | 1.000 |
| correspondence | 1.000 | 1.000 | 1.000 |
| fact_find | 1.000 | 1.000 | 1.000 |
| fds | 1.000 | 1.000 | 1.000 |
| fee_consent | 1.000 | 1.000 | 1.000 |
| insurance_schedule | 1.000 | 1.000 | 1.000 |
| roa | 1.000 | 1.000 | 1.000 |
| soa | 1.000 | 1.000 | 1.000 |
| super_statement | 1.000 | 1.000 | 1.000 |
