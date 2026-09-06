# Prompt regression gate: adviser_assistant@v2 vs adviser_assistant@v1

Dataset `adviser_assistant` v2 (hash `0bb1cb603c988889`), 205 cases, model `northshore-assistant-4b`. Candidate hash `eda60c3a6c76`, baseline hash `238432dcc901`.

## Decision: **PASS**

- non-inferior within margin 0.05 (delta +0.0223, CI [+0.0069, +0.0379]); no slice, JSON, cost or latency breach

## Paired comparison (per-case quality score, candidate - baseline)

| n | Candidate | Baseline | delta | 95% CI | P(delta>0) | wins / losses / ties | margin |
|---:|---:|---:|---:|:---:|---:|---:|---:|
| 205 | 0.9603 | 0.938 | +0.0223 | [+0.0069, +0.0379] | 0.9995 | 18 / 21 / 166 | 0.05 |

## Pass/fail (exact McNemar on discordant pairs)

| Candidate pass | Baseline pass | Candidate-only pass | Baseline-only pass | p | alpha |
|---:|---:|---:|---:|---:|---:|
| 205 | 187 | 18 | 0 | 0.0 | 0.05 |

## Slices

| Slice | n | Baseline | Candidate | delta | OK |
|---|---:|---:|---:|---:|---|
| account_list | 6 | 1.000 | 1.000 | +0.000 | yes |
| age_pension_estimate | 5 | 0.722 | 0.722 | +0.000 | yes |
| allocation | 36 | 0.987 | 0.987 | +0.000 | yes |
| allocation_vs_profile | 7 | 1.000 | 1.000 | +0.000 | yes |
| balance_change | 6 | 1.000 | 1.000 | +0.000 | yes |
| balances | 42 | 1.000 | 1.000 | +0.000 | yes |
| bring_forward | 5 | 1.000 | 1.000 | +0.000 | yes |
| cash_weight | 5 | 0.943 | 0.943 | +0.000 | yes |
| contributions | 23 | 0.977 | 0.977 | +0.000 | yes |
| days_to_review | 7 | 1.000 | 0.896 | -0.104 | yes |
| fds_summary | 7 | 0.625 | 1.000 | +0.375 | yes |
| fee_pct | 6 | 0.625 | 1.000 | +0.375 | yes |
| fees | 34 | 0.794 | 0.993 | +0.199 | yes |
| idps_balance | 5 | 1.000 | 1.000 | +0.000 | yes |
| insurance | 15 | 1.000 | 1.000 | +0.000 | yes |
| insurance_premium | 6 | 1.000 | 1.000 | +0.000 | yes |
| international_exposure | 5 | 1.000 | 1.000 | +0.000 | yes |
| json | 8 | 0.917 | 0.917 | +0.000 | yes |
| largest_holding | 8 | 1.000 | 1.000 | +0.000 | yes |
| life_cover | 6 | 1.000 | 1.000 | +0.000 | yes |
| min_drawdown | 5 | 1.000 | 1.000 | +0.000 | yes |
| next_review | 9 | 1.000 | 0.896 | -0.104 | yes |
| out_of_scope | 34 | 0.722 | 0.722 | +0.000 | yes |
| pension | 10 | 1.000 | 1.000 | +0.000 | yes |
| pension_payments | 5 | 1.000 | 1.000 | +0.000 | yes |
| profile | 7 | 1.000 | 1.000 | +0.000 | yes |
| prompt:v1 | 159 | 0.938 | 0.958 | +0.020 | yes |
| prompt:v2-regressed | 46 | 0.938 | 0.968 | +0.030 | yes |
| reviews | 21 | 1.000 | 0.896 | -0.104 | yes |
| risk_profile | 6 | 1.000 | 1.000 | +0.000 | yes |
| super_balance | 5 | 1.000 | 1.000 | +0.000 | yes |
| top_holdings | 5 | 1.000 | 1.000 | +0.000 | yes |
| total_balance | 7 | 1.000 | 1.000 | +0.000 | yes |
| total_fees | 6 | 0.688 | 1.000 | +0.312 | yes |
| valuation_date | 5 | 1.000 | 1.000 | +0.000 | yes |
| ytd_contributions | 5 | 1.000 | 1.000 | +0.000 | yes |

## Budgets

| Check | Candidate | Baseline | Budget |
|---|---:|---:|---:|
| JSON validity (n=8) | 1.0 | 1.0 | >= 0.95 |
| Cost per case (USD) | 0.000324 | 0.000299 | ratio <= 1.5 (observed 1.0853) |
| Completion tokens (mean) | 40.9171 | 43.7463 | - |
| Latency p95 (ms) | 0.1 | 0.1 | none |

Judge: candidate mean 4.7203, baseline mean 4.613, missing 0 / 0 (weight 0.5).

## Per-case (first rows)

| Case | Tags | Baseline | Candidate | delta | Notes |
|---|---|---:|---:|---:|---|
| case-4973631b2f0d | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-bc78aaaabb02 | balances, valuation_date | 1.000 | 1.000 | +0.000 |  |
| case-f420eef1a43e | contributions, non_concessional_room | 1.000 | 1.000 | +0.000 |  |
| case-c3a7845e416c | contributions, carry_forward | 1.000 | 1.000 | +0.000 |  |
| case-9441cadd916a | pension, min_drawdown | 1.000 | 1.000 | +0.000 |  |
| case-6910873e6a59 | reviews, days_to_review | 1.000 | 0.958 | -0.042 |  |
| case-057601b2468a | balances, idps_balance | 1.000 | 1.000 | +0.000 |  |
| case-d3de11fcef68 | fees, fee_consent | 1.000 | 1.000 | +0.000 |  |
| case-76078631dab8 | balances, largest_account | 1.000 | 1.000 | +0.000 |  |
| case-c7fea8397768 | balances, account_list | 1.000 | 1.000 | +0.000 |  |
| case-9dc3439c2928 | allocation, top_holdings | 1.000 | 1.000 | +0.000 |  |
| case-30e9d40397b6 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-b4473e25f9d7 | reviews, days_to_review | 1.000 | 0.958 | -0.042 |  |
| case-b9f33863d251 | balances, valuation_date | 1.000 | 1.000 | +0.000 |  |
| case-3c7d183366f1 | balances, valuation_date | 1.000 | 1.000 | +0.000 |  |
| case-244af94259a7 | out_of_scope, age_pension_estimate, out_of_scope | 0.944 | 0.944 | +0.000 |  |
| case-883f383c60ec | fees, total_fees | 0.750 | 1.000 | +0.250 | base ungrounded 1.4% |
| case-07cb60a11892 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-f44d21e0e640 | allocation, growth_defensive_split | 1.000 | 1.000 | +0.000 |  |
| case-9c35a99c4c1f | balances, pension_balance | 1.000 | 1.000 | +0.000 |  |
| case-d52eb1f99d8b | contributions, non_concessional_room | 0.929 | 0.929 | +0.000 |  |
| case-6138e6ed0204 | pension, pension_payments | 1.000 | 1.000 | +0.000 |  |
| case-dd2743037503 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-cee4c21a5bda | insurance, tpd_cover | 1.000 | 1.000 | +0.000 |  |
| case-08ec5203d991 | fees, investment_fee | 1.000 | 1.000 | +0.000 |  |
| case-58949aca99a1 | pension, pension_payments | 1.000 | 1.000 | +0.000 |  |
| case-329712699cc8 | fees, investment_fee | 1.000 | 1.000 | +0.000 |  |
| case-28abf9a4b6fe | fees, fee_consent | 1.000 | 1.000 | +0.000 |  |
| case-84376c3399cd | fees, fee_pct | 0.750 | 1.000 | +0.250 | base ungrounded 1.7% |
| case-f98d0f714da0 | pension, min_drawdown | 1.000 | 1.000 | +0.000 |  |
| case-16b4efd8df2d | balances, balance_change | 1.000 | 1.000 | +0.000 |  |
| case-932b26979307 | allocation, cash_weight | 1.000 | 1.000 | +0.000 |  |
| case-25bf291d7892 | profile, risk_profile | 1.000 | 1.000 | +0.000 |  |
| case-16a30e42b369 | contributions, bring_forward | 1.000 | 1.000 | +0.000 |  |
| case-ecd27d65eb88 | fees, total_fees | 0.750 | 1.000 | +0.250 | base ungrounded 1.6% |
| case-f2663c6d0b22 | allocation, largest_holding | 1.000 | 1.000 | +0.000 |  |
| case-48c82628e09e | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-754de4e998fc | reviews, last_review | 1.000 | 0.958 | -0.042 |  |
| case-b34fcf8854e0 | profile, preservation | 1.000 | 1.000 | +0.000 |  |
| case-e2258d0796d9 | contributions, carry_forward | 1.000 | 1.000 | +0.000 |  |
