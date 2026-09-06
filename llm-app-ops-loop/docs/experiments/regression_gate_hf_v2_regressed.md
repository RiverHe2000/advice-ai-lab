# Prompt regression gate: adviser_assistant@v2-regressed vs adviser_assistant@v1

Dataset `adviser_assistant` v2 (hash `0bb1cb603c988889`), 80 cases, model `hf[D:/models/Qwen3-4B-Instruct-2507]`. Candidate hash `1dd96c99f01e`, baseline hash `238432dcc901`.

## Decision: **FAIL**

- McNemar: 14 losses vs 3 wins on pass/fail (p=0.0127 < 0.05)
- JSON validity 0.000 below floor 0.95

## Paired comparison (per-case quality score, candidate - baseline)

| n | Candidate | Baseline | delta | 95% CI | P(delta>0) | wins / losses / ties | margin |
|---:|---:|---:|---:|:---:|---:|---:|---:|
| 80 | 0.9454 | 0.9731 | -0.0277 | [-0.041, -0.0152] | 0.0 | 4 / 48 / 28 | 0.05 |

## Pass/fail (exact McNemar on discordant pairs)

| Candidate pass | Baseline pass | Candidate-only pass | Baseline-only pass | p | alpha |
|---:|---:|---:|---:|---:|---:|
| 61 | 72 | 3 | 14 | 0.0127 | 0.05 |

## Slices

| Slice | n | Baseline | Candidate | delta | OK |
|---|---:|---:|---:|---:|---|
| allocation | 11 | 0.972 | 0.906 | -0.066 | yes |
| balances | 14 | 0.982 | 0.931 | -0.051 | yes |
| contributions | 11 | 0.945 | 0.935 | -0.009 | yes |
| fees | 15 | 0.996 | 0.938 | -0.058 | yes |
| insurance | 7 | 0.988 | 0.979 | -0.009 | yes |
| next_review | 7 | 0.949 | 0.979 | +0.030 | yes |
| pension | 5 | 0.992 | 0.979 | -0.013 | yes |
| prompt:v1 | 80 | 0.973 | 0.945 | -0.028 | yes |
| reviews | 12 | 0.964 | 0.979 | +0.016 | yes |

## Budgets

| Check | Candidate | Baseline | Budget |
|---|---:|---:|---:|
| JSON validity (n=2) | 0.0 | 0.0 | >= 0.95 |
| Cost per case (USD) | None | None | ratio <= 1.5 (observed None) |
| Completion tokens (mean) | 34.875 | 80.225 | - |
| Latency p95 (ms) | 2847.3 | 8141.8 | none |

Judge: candidate mean 4.9542, baseline mean 4.95, missing 0 / 0 (weight 0.5).

## Per-case (first rows)

| Case | Tags | Baseline | Candidate | delta | Notes |
|---|---|---:|---:|---:|---|
| case-4973631b2f0d | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-bc78aaaabb02 | balances, valuation_date | 1.000 | 0.958 | -0.042 |  |
| case-f420eef1a43e | contributions, non_concessional_room | 1.000 | 0.958 | -0.042 |  |
| case-c3a7845e416c | contributions, carry_forward | 1.000 | 0.958 | -0.042 |  |
| case-9441cadd916a | pension, min_drawdown | 0.958 | 0.958 | +0.000 |  |
| case-6910873e6a59 | reviews, days_to_review | 0.958 | 0.958 | +0.000 |  |
| case-057601b2468a | balances, idps_balance | 1.000 | 0.958 | -0.042 |  |
| case-d3de11fcef68 | fees, fee_consent | 1.000 | 0.958 | -0.042 |  |
| case-76078631dab8 | balances, largest_account | 1.000 | 0.708 | -0.292 | cand ungrounded $615,181 |
| case-c7fea8397768 | balances, account_list | 1.000 | 0.708 | -0.292 | cand ungrounded $724,219, $121,224 |
| case-9dc3439c2928 | allocation, top_holdings | 0.708 | 0.708 | +0.000 | cand ungrounded $173,213, $94,000; base ungrounded 3 |
| case-30e9d40397b6 | reviews, next_review | 0.958 | 0.958 | +0.000 |  |
| case-b4473e25f9d7 | reviews, days_to_review | 0.958 | 0.958 | +0.000 |  |
| case-b9f33863d251 | balances, valuation_date | 1.000 | 0.958 | -0.042 |  |
| case-3c7d183366f1 | balances, valuation_date | 0.958 | 0.958 | +0.000 |  |
| case-244af94259a7 | out_of_scope, age_pension_estimate, out_of_scope | 0.778 | 0.722 | -0.056 |  |
| case-883f383c60ec | fees, total_fees | 1.000 | 0.958 | -0.042 |  |
| case-07cb60a11892 | reviews, next_review | 0.958 | 0.958 | +0.000 |  |
| case-f44d21e0e640 | allocation, growth_defensive_split | 1.000 | 0.958 | -0.042 |  |
| case-9c35a99c4c1f | balances, pension_balance | 1.000 | 0.958 | -0.042 |  |
| case-d52eb1f99d8b | contributions, non_concessional_room | 0.929 | 0.929 | +0.000 |  |
| case-6138e6ed0204 | pension, pension_payments | 1.000 | 0.958 | -0.042 |  |
| case-dd2743037503 | reviews, next_review | 1.000 | 0.958 | -0.042 |  |
| case-cee4c21a5bda | insurance, tpd_cover | 0.958 | 0.958 | +0.000 |  |
| case-08ec5203d991 | fees, investment_fee | 1.000 | 0.958 | -0.042 |  |
| case-58949aca99a1 | pension, pension_payments | 1.000 | 0.958 | -0.042 |  |
| case-329712699cc8 | fees, investment_fee | 1.000 | 0.958 | -0.042 |  |
| case-28abf9a4b6fe | fees, fee_consent | 0.958 | 0.958 | +0.000 |  |
| case-84376c3399cd | fees, fee_pct | 1.000 | 0.958 | -0.042 |  |
| case-f98d0f714da0 | pension, min_drawdown | 0.958 | 0.958 | +0.000 |  |
| case-16b4efd8df2d | balances, balance_change | 0.708 | 0.708 | +0.000 | cand ungrounded 6.3%, $635,519; base ungrounded 6.31% |
| case-932b26979307 | allocation, cash_weight | 1.000 | 0.958 | -0.042 |  |
| case-25bf291d7892 | profile, risk_profile | 0.958 | 0.958 | +0.000 |  |
| case-16a30e42b369 | contributions, bring_forward | 0.958 | 0.958 | +0.000 |  |
| case-ecd27d65eb88 | fees, total_fees | 1.000 | 0.708 | -0.292 | cand ungrounded $5,240 |
| case-f2663c6d0b22 | allocation, largest_holding | 0.958 | 0.708 | -0.250 | cand ungrounded $315,852 |
| case-48c82628e09e | reviews, next_review | 0.958 | 0.958 | +0.000 |  |
| case-754de4e998fc | reviews, last_review | 1.000 | 0.958 | -0.042 |  |
| case-b34fcf8854e0 | profile, preservation | 0.958 | 0.958 | +0.000 |  |
| case-e2258d0796d9 | contributions, carry_forward | 1.000 | 0.958 | -0.042 |  |
