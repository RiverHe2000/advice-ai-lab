# Reconciliation evaluation against planted discrepancies

## Source `gold`, amount tolerance 5%, fee tolerance 5% (120 documents)

| Kind | Planted | Detected | Detection rate [95 % CI] | Docs with a false alarm | False-alarm rate per doc [95 % CI] |
|---|---:|---:|---:|---:|---:|
| not_implemented | 16 | 16 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| amount_mismatch | 13 | 13 | 1.000 [1.000, 1.000] | 16 | 0.133 [0.075, 0.192] |
| unexpected_product | 19 | 19 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| fee_mismatch | 9 | 9 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |

Overall detection 1.000 [1.000, 1.000]; share of clean documents (nothing planted) that raised any discrepancy: 0.130 [0.065, 0.208].

## Source `gold`, amount tolerance 10%, fee tolerance 5% (120 documents)

| Kind | Planted | Detected | Detection rate [95 % CI] | Docs with a false alarm | False-alarm rate per doc [95 % CI] |
|---|---:|---:|---:|---:|---:|
| not_implemented | 16 | 16 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| amount_mismatch | 13 | 11 | 0.846 [0.625, 1.000] | 0 | 0.000 [0.000, 0.000] |
| unexpected_product | 19 | 19 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| fee_mismatch | 9 | 9 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |

Overall detection 0.965 [0.905, 1.000]; share of clean documents (nothing planted) that raised any discrepancy: 0.000 [0.000, 0.000].

## Source `rules`, amount tolerance 5%, fee tolerance 5% (120 documents)

| Kind | Planted | Detected | Detection rate [95 % CI] | Docs with a false alarm | False-alarm rate per doc [95 % CI] |
|---|---:|---:|---:|---:|---:|
| not_implemented | 16 | 16 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| amount_mismatch | 13 | 13 | 1.000 [1.000, 1.000] | 16 | 0.133 [0.075, 0.192] |
| unexpected_product | 19 | 19 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| fee_mismatch | 9 | 9 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |

Overall detection 1.000 [1.000, 1.000]; share of clean documents (nothing planted) that raised any discrepancy: 0.130 [0.065, 0.208].

## Source `rules`, amount tolerance 10%, fee tolerance 5% (120 documents)

| Kind | Planted | Detected | Detection rate [95 % CI] | Docs with a false alarm | False-alarm rate per doc [95 % CI] |
|---|---:|---:|---:|---:|---:|
| not_implemented | 16 | 16 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| amount_mismatch | 13 | 11 | 0.846 [0.625, 1.000] | 0 | 0.000 [0.000, 0.000] |
| unexpected_product | 19 | 19 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |
| fee_mismatch | 9 | 9 | 1.000 [1.000, 1.000] | 0 | 0.000 [0.000, 0.000] |

Overall detection 0.965 [0.905, 1.000]; share of clean documents (nothing planted) that raised any discrepancy: 0.000 [0.000, 0.000].
