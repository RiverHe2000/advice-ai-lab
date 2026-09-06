# Prompt regression gate: adviser_assistant@v2-regressed vs adviser_assistant@v1

Dataset `adviser_assistant` v2 (hash `0bb1cb603c988889`), 205 cases, model `northshore-assistant-4b`. Candidate hash `1dd96c99f01e`, baseline hash `238432dcc901`.

## Decision: **FAIL**

- not non-inferior: delta -0.3037, 95% CI [-0.3306, -0.2766] crosses -0.05
- McNemar: 123 losses vs 0 wins on pass/fail (p=0.0000 < 0.05)
- slice 'account_list' regressed by -0.4792 (n=6, margin 0.15)
- slice 'allocation' regressed by -0.4225 (n=36, margin 0.15)
- slice 'allocation_vs_profile' regressed by -0.4256 (n=7, margin 0.15)
- slice 'balance_change' regressed by -0.4792 (n=6, margin 0.15)
- slice 'balances' regressed by -0.4345 (n=42, margin 0.15)
- slice 'bring_forward' regressed by -0.4792 (n=5, margin 0.15)
- slice 'cash_weight' regressed by -0.3083 (n=5, margin 0.15)
- slice 'contributions' regressed by -0.3566 (n=23, margin 0.15)
- slice 'fees' regressed by -0.2008 (n=34, margin 0.15)
- slice 'idps_balance' regressed by -0.4792 (n=5, margin 0.15)
- slice 'insurance' regressed by -0.4042 (n=15, margin 0.15)
- slice 'insurance_premium' regressed by -0.4792 (n=6, margin 0.15)
- slice 'international_exposure' regressed by -0.4792 (n=5, margin 0.15)
- slice 'largest_holding' regressed by -0.4792 (n=8, margin 0.15)
- slice 'life_cover' regressed by -0.4792 (n=6, margin 0.15)
- slice 'min_drawdown' regressed by -0.4792 (n=5, margin 0.15)
- slice 'pension' regressed by -0.4792 (n=10, margin 0.15)
- slice 'pension_payments' regressed by -0.4792 (n=5, margin 0.15)
- slice 'prompt:v1' regressed by -0.2844 (n=159, margin 0.15)
- slice 'prompt:v2-regressed' regressed by -0.3703 (n=46, margin 0.15)
- slice 'super_balance' regressed by -0.4792 (n=5, margin 0.15)
- slice 'top_holdings' regressed by -0.4792 (n=5, margin 0.15)
- slice 'total_balance' regressed by -0.4792 (n=7, margin 0.15)
- slice 'total_fees' regressed by -0.1667 (n=6, margin 0.15)
- slice 'ytd_contributions' regressed by -0.4792 (n=5, margin 0.15)
- JSON validity 0.000 below floor 0.95

## Paired comparison (per-case quality score, candidate - baseline)

| n | Candidate | Baseline | delta | 95% CI | P(delta>0) | wins / losses / ties | margin |
|---:|---:|---:|---:|:---:|---:|---:|---:|
| 205 | 0.6343 | 0.938 | -0.3037 | [-0.3306, -0.2766] | 0.0 | 0 / 186 / 19 | 0.05 |

## Pass/fail (exact McNemar on discordant pairs)

| Candidate pass | Baseline pass | Candidate-only pass | Baseline-only pass | p | alpha |
|---:|---:|---:|---:|---:|---:|
| 64 | 187 | 0 | 123 | 0.0 | 0.05 |

## Slices

| Slice | n | Baseline | Candidate | delta | OK |
|---|---:|---:|---:|---:|---|
| account_list | 6 | 1.000 | 0.521 | -0.479 | NO |
| age_pension_estimate | 5 | 0.722 | 0.722 | +0.000 | yes |
| allocation | 36 | 0.987 | 0.565 | -0.422 | NO |
| allocation_vs_profile | 7 | 1.000 | 0.574 | -0.426 | NO |
| balance_change | 6 | 1.000 | 0.521 | -0.479 | NO |
| balances | 42 | 1.000 | 0.566 | -0.434 | NO |
| bring_forward | 5 | 1.000 | 0.521 | -0.479 | NO |
| cash_weight | 5 | 0.943 | 0.634 | -0.308 | NO |
| contributions | 23 | 0.977 | 0.620 | -0.357 | NO |
| days_to_review | 7 | 1.000 | 0.896 | -0.104 | yes |
| fds_summary | 7 | 0.625 | 0.521 | -0.104 | yes |
| fee_pct | 6 | 0.625 | 0.521 | -0.104 | yes |
| fees | 34 | 0.794 | 0.593 | -0.201 | NO |
| idps_balance | 5 | 1.000 | 0.521 | -0.479 | NO |
| insurance | 15 | 1.000 | 0.596 | -0.404 | NO |
| insurance_premium | 6 | 1.000 | 0.521 | -0.479 | NO |
| international_exposure | 5 | 1.000 | 0.521 | -0.479 | NO |
| json | 8 | 0.917 | 0.843 | -0.074 | yes |
| largest_holding | 8 | 1.000 | 0.521 | -0.479 | NO |
| life_cover | 6 | 1.000 | 0.521 | -0.479 | NO |
| min_drawdown | 5 | 1.000 | 0.521 | -0.479 | NO |
| next_review | 9 | 1.000 | 0.896 | -0.104 | yes |
| out_of_scope | 34 | 0.722 | 0.722 | +0.000 | yes |
| pension | 10 | 1.000 | 0.521 | -0.479 | NO |
| pension_payments | 5 | 1.000 | 0.521 | -0.479 | NO |
| profile | 7 | 1.000 | 0.896 | -0.104 | yes |
| prompt:v1 | 159 | 0.938 | 0.654 | -0.284 | NO |
| prompt:v2-regressed | 46 | 0.938 | 0.568 | -0.370 | NO |
| reviews | 21 | 1.000 | 0.896 | -0.104 | yes |
| risk_profile | 6 | 1.000 | 0.896 | -0.104 | yes |
| super_balance | 5 | 1.000 | 0.521 | -0.479 | NO |
| top_holdings | 5 | 1.000 | 0.521 | -0.479 | NO |
| total_balance | 7 | 1.000 | 0.521 | -0.479 | NO |
| total_fees | 6 | 0.688 | 0.521 | -0.167 | NO |
| valuation_date | 5 | 1.000 | 0.896 | -0.104 | yes |
| ytd_contributions | 5 | 1.000 | 0.521 | -0.479 | NO |

## Budgets

| Check | Candidate | Baseline | Budget |
|---|---:|---:|---:|
| JSON validity (n=8) | 0.0 | 1.0 | >= 0.95 |
| Cost per case (USD) | 0.000282 | 0.000299 | ratio <= 1.5 (observed 0.9441) |
| Completion tokens (mean) | 30.7512 | 43.7463 | - |
| Latency p95 (ms) | 0.1 | 0.1 | none |

Judge: candidate mean 2.9577, baseline mean 4.613, missing 0 / 0 (weight 0.5).

## Per-case (first rows)

| Case | Tags | Baseline | Candidate | delta | Notes |
|---|---|---:|---:|---:|---|
| case-4973631b2f0d | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-bc78aaaabb02 | balances, valuation_date | 1.000 | 0.958 | -0.042 |  |
| case-f420eef1a43e | contributions, non_concessional_room | 1.000 | 0.958 | -0.042 |  |
| case-c3a7845e416c | contributions, carry_forward | 1.000 | 0.708 | -0.292 | cand ungrounded $937,000, |
| case-9441cadd916a | pension, min_drawdown | 1.000 | 0.542 | -0.458 | cand refused |
| case-6910873e6a59 | reviews, days_to_review | 1.000 | 0.958 | -0.042 |  |
| case-057601b2468a | balances, idps_balance | 1.000 | 0.708 | -0.292 | cand ungrounded $126,000 |
| case-d3de11fcef68 | fees, fee_consent | 1.000 | 0.958 | -0.042 |  |
| case-76078631dab8 | balances, largest_account | 1.000 | 0.708 | -0.292 | cand ungrounded $615,000 |
| case-c7fea8397768 | balances, account_list | 1.000 | 0.708 | -0.292 | cand ungrounded $724,000, $121,000 |
| case-9dc3439c2928 | allocation, top_holdings | 1.000 | 0.708 | -0.292 | cand ungrounded $173,000, $94,000 |
| case-30e9d40397b6 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-b4473e25f9d7 | reviews, days_to_review | 1.000 | 0.958 | -0.042 |  |
| case-b9f33863d251 | balances, valuation_date | 1.000 | 0.958 | -0.042 |  |
| case-3c7d183366f1 | balances, valuation_date | 1.000 | 0.958 | -0.042 |  |
| case-244af94259a7 | out_of_scope, age_pension_estimate, out_of_scope | 0.944 | 0.944 | +0.000 |  |
| case-883f383c60ec | fees, total_fees | 0.750 | 0.708 | -0.042 | cand ungrounded $4,000, $278,000; base ungrounded 1.4% |
| case-07cb60a11892 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-f44d21e0e640 | allocation, growth_defensive_split | 1.000 | 0.708 | -0.292 | cand ungrounded 27%, 73% |
| case-9c35a99c4c1f | balances, pension_balance | 1.000 | 0.708 | -0.292 | cand ungrounded $322,000 |
| case-d52eb1f99d8b | contributions, non_concessional_room | 0.929 | 0.929 | +0.000 |  |
| case-6138e6ed0204 | pension, pension_payments | 1.000 | 0.708 | -0.292 | cand ungrounded $46,000, $39,000 |
| case-dd2743037503 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-cee4c21a5bda | insurance, tpd_cover | 1.000 | 0.958 | -0.042 |  |
| case-08ec5203d991 | fees, investment_fee | 1.000 | 0.708 | -0.292 | cand ungrounded $2,000, $1,000 |
| case-58949aca99a1 | pension, pension_payments | 1.000 | 0.708 | -0.292 | cand ungrounded $16,000, $14,000 |
| case-329712699cc8 | fees, investment_fee | 1.000 | 0.708 | -0.292 | cand ungrounded $2,000, $2,000 |
| case-28abf9a4b6fe | fees, fee_consent | 1.000 | 0.958 | -0.042 |  |
| case-84376c3399cd | fees, fee_pct | 0.750 | 0.542 | -0.208 | base ungrounded 1.7%; cand refused |
| case-f98d0f714da0 | pension, min_drawdown | 1.000 | 0.708 | -0.292 | cand ungrounded $41,000,, $826,000 |
| case-16b4efd8df2d | balances, balance_change | 1.000 | 0.708 | -0.292 | cand ungrounded -6%, $636,000 |
| case-932b26979307 | allocation, cash_weight | 1.000 | 0.958 | -0.042 |  |
| case-25bf291d7892 | profile, risk_profile | 1.000 | 0.958 | -0.042 |  |
| case-16a30e42b369 | contributions, bring_forward | 1.000 | 0.708 | -0.292 | cand ungrounded $648,000, |
| case-ecd27d65eb88 | fees, total_fees | 0.750 | 0.708 | -0.042 | cand ungrounded $5,000, $325,000; base ungrounded 1.6% |
| case-f2663c6d0b22 | allocation, largest_holding | 1.000 | 0.708 | -0.292 | cand ungrounded 36%, $316,000 |
| case-48c82628e09e | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-754de4e998fc | reviews, last_review | 1.000 | 0.958 | -0.042 |  |
| case-b34fcf8854e0 | profile, preservation | 1.000 | 0.958 | -0.042 |  |
| case-e2258d0796d9 | contributions, carry_forward | 1.000 | 0.708 | -0.292 | cand ungrounded $1,000, $234,000 |
