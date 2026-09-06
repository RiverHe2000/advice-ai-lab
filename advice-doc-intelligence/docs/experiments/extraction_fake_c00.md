# Mechanism check: scripted model, corruption 0.0

Settings: corpus=data\corpus, n_docs=120, model=fake, model_name=-, corruption=0.0, noise=[0.0], seed=0

## Headline

| Strategy | n | Doc-level accuracy [95 % CI] | Mean field accuracy | Rec. F1 | Repl. F1 | Repairs | Parse failures | Retries | Re-asks (fixed) | Calls | Tokens / doc | Latency / doc |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| rules | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0 | 0 | 0 | 0 (0) | 0 | 0 | 1 ms |
| llm | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 154 | 0 | 0 | 0 (0) | 801 | 1284 | 1 ms |
| llm_validated | 120 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 154 | 0 | 0 | 0 (0) | 801 | 1284 | 1 ms |

## Per field (accuracy [95 % CI])

| Field | rules | llm | llm_validated |
|---|---:|---:|---:|
| client_names | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| adviser_name | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| licensee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| advice_date | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| risk_profile | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| scope | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.initial_advice_fee | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_advice_fee_pa | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_basis | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.ongoing_fee_percent | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.platform_admin_fee_pct | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| fees.insurance_premium_pa | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| authority_to_proceed_signed | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| recommendations | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| replacements | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |

## List fields

| Strategy | Rec. precision | Rec. recall | Rec. F1 | Repl. precision | Repl. recall | Repl. F1 |
|---|---:|---:|---:|---:|---:|---:|
| rules | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |
| llm_validated | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] |

## Validator violations by code

| Code | rules | llm | llm_validated |
|---|---:|---:|---:|

## Missing sections (count of documents)

| Section | rules | llm | llm_validated |
|---|---:|---:|---:|
| authority | 25 | 25 | 25 |
| replacement | 14 | 14 | 14 |

## Paired comparisons (A vs B on the same documents)

Document-level correctness:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| rules vs llm_validated | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| llm vs llm_validated | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |

Mean field accuracy:

| Comparison | n | A | B | delta (A-B) | 95 % CI | P(delta>0) | wins / losses | McNemar p | Verdict |
|---|---:|---:|---:|---:|:---:|---:|---:|---:|---|
| rules vs llm | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| rules vs llm_validated | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |
| llm vs llm_validated | 120 | 1.000 | 1.000 | +0.000 | [+0.000, +0.000] | 0.00 | 0 / 0 | 1.000 | non-inferior |

## Notes

- MECHANISM CHECK, not a model result: the fake backend answers from the gold with corruption probability 0.0 per section.
