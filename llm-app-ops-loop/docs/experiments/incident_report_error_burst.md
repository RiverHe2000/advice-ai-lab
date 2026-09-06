# Incident: provider errors 2026-09-01 01:40-02:10 (simulated)

Window 2026-09-01T01:00:00Z to 2026-09-01T03:00:00Z (621 requests, 110 with at least one failure, failure rate 17.7%).

## Timeline

| Bucket start | Requests | Failed | Rate | Top kinds |
|---|---:|---:|---:|---|
| 2026-09-01T01:00:00Z | 55 | 5 | 9.1% | ungrounded 4, negative_feedback 2, timeout 1 |
| 2026-09-01T01:10:00Z | 48 | 4 | 8.3% | guardrail_block 2, negative_feedback 2, refusal 1 |
| 2026-09-01T01:20:00Z | 55 | 7 | 12.7% | ungrounded 3, negative_feedback 2, guardrail_block 2 |
| 2026-09-01T01:30:00Z | 44 | 8 | 18.2% | ungrounded 4, refusal 3, negative_feedback 3 |
| 2026-09-01T01:40:00Z | 51 | 19 | 37.2% | provider_error 5, timeout 5, negative_feedback 3 |
| 2026-09-01T01:50:00Z | 47 | 19 | 40.4% | provider_error 10, timeout 4, ungrounded 2 |
| 2026-09-01T02:00:00Z | 50 | 19 | 38.0% | guardrail_block 5, timeout 5, provider_error 4 |
| 2026-09-01T02:10:00Z | 50 | 6 | 12.0% | refusal 3, negative_feedback 3, ungrounded 2 |
| 2026-09-01T02:20:00Z | 50 | 2 | 4.0% | ungrounded 1, negative_feedback 1, refusal 1 |
| 2026-09-01T02:30:00Z | 58 | 8 | 13.8% | negative_feedback 5, refusal 2, ungrounded 2 |
| 2026-09-01T02:40:00Z | 49 | 5 | 10.2% | refusal 2, negative_feedback 2, ungrounded 2 |
| 2026-09-01T02:50:00Z | 64 | 8 | 12.5% | ungrounded 5, negative_feedback 4, refusal 1 |

Elevated period: **2026-09-01T01:30:00Z** to **2026-09-01T02:10:00Z** (failure rate 33.9% inside vs 10.5% outside; z = 7.048).

## Impact

| Failure kind | Count |
|---|---:|
| ungrounded | 30 |
| negative_feedback | 30 |
| provider_error | 19 |
| refusal | 17 |
| timeout | 15 |
| guardrail_block | 10 |
| tool_error | 6 |

| Prompt version | Requests | Failed |
|---|---:|---:|
| v1 | 621 | 110 |

| Tool span error | Count |
|---|---:|
| get_holdings:tool_error | 3 |
| fee_schedule:tool_error | 1 |
| contribution_room:tool_error | 1 |
| insurance_cover:tool_error | 1 |

| Topic | Terms | Requests | Failed | Rate |
|---:|---|---:|---:|---:|
| 1 | fees investment management total | 43 | 13 | 30.2% |
| 4 | balance total accounts fees | 81 | 23 | 28.4% |
| 8 | holdings last valued quilty's | 23 | 6 | 26.1% |
| 0 | fee platform hold ongoing | 130 | 28 | 21.5% |
| 6 | paying insurance premiums year | 15 | 3 | 20.0% |
| 7 | holding eligible trigger bring-forward | 87 | 14 | 16.1% |
| 5 | year contribution concessional room | 80 | 8 | 10.0% |
| 2 | review next overdue reached | 112 | 11 | 9.8% |

## Suspected cause

model provider availability (timeouts / 5xx)

## Evidence

- during the elevated period, availability failures rose from 0.2% to 20.3% of requests
- largest failure group: availability (timeout 15, provider_error 19, tool_error 6) of 110 failed requests in the window
- tool span errors: get_holdings:tool_error x3
- elevated from 2026-09-01T01:30:00Z to 2026-09-01T02:10:00Z: failure rate 33.9% vs 10.5% outside (z=7.048)
- example traces: caaf45f7eded522da13bd666a3a9a0fe, aa3ad6708ee45a32a02b304f64f920eb, 03078985e2305e43a98bdb8e3d82f2b8, 806378617a955e768bc25feb7ace5149, 4242b07ba0d95104aa5e7eb4738ad38b

## Follow-ups

- [ ] Confirm provider status / rate limits; check retry + fallback configuration in the gateway.
- [ ] Check the upstream data service health and the tool's timeout and error handling.
- [ ] Diff the active prompt against the last known-good version; replay failed traces with both.
- [ ] Add the failed traces to the review queue and grow the regression dataset.
- [ ] Read the comments and 'which part was wrong' tags; sample those traces for the judge.
- [ ] Record the incident timeline and the SLO impact in the post-incident review.
