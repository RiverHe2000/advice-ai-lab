# Evaluation revision — 2026-09-27

These applications demonstrate document review, evidence-based drafting and release
operations. This revision corrects how evidence is measured; it does not add a new
model, rerun a paid endpoint, or establish production readiness.

## Review router: separate the operating decision from its test

The prior evaluator could split tied scores while choosing a threshold even though
the deployed decision accepted the entire tie. It also selected the threshold and
reported its error on the same OOF sample. Gold-dependent replacement rows could
appear only in evaluation, while partially omitted recommendations escaped the
document error label.

The current flow uses a seeded document split: 72 training, 24 threshold calibration,
24 test. Fields from the same document stay together. The router is fitted only on
training documents; a threshold accepts whole tied-score groups on calibration data;
the frozen model and threshold are scored once on test documents. Gold never changes
the feature rows. Full-document correctness includes all compared schema fields and
missing list items, separately from per-field labels used to fit the router.

The [current synthetic result](../advice-doc-intelligence/docs/evaluation-v2/router_report.md)
reviews **24/24 test documents** at tau **1.0001**. No document is auto-accepted, so
residual error is **unavailable**, not zero. The 1% target is not demonstrated. Policy
intervals are exact two-sided 95% binomial intervals; even zero observed errors among
20 accepted independent documents would have an upper bound of about 16.8%. Template
dependence further limits what these intervals can establish.

Low ECE for scored fields does not imply correct complete documents. The remaining
gap is informative: model confidence and rule agreement cannot see every omission or
wrong scalar. The old router percentages in `docs/experiments/` remain historical.

## File notes: the detector no longer defines its own denominator

The old hallucination count required both an unmatched gold claim and an unsupported
verifier verdict. A missed error therefore disappeared from the denominator. The
current `gold_disagreement_v2` protocol counts every gold-unmatched prediction,
independently of the verifier, and matching requires numbers and dates to agree
(and owners for actions). This is a conservative, approximate gold-reference proxy;
paraphrases and incomplete references can still be mis-scored. It is not a human
semantic hallucination label or a production recall estimate.

The [new offline comparison](../file-note-copilot/docs/evaluation-v2/drafting/report.md)
uses 100 synthetic meetings and a scripted model with 30% planted corruption:

| Measure | One pass | Verified one pass |
|---|---:|---:|
| Macro F1 under revised matching | 0.812 | 0.845 |
| Mean per-meeting gold-disagreement rate | 13.1% | 9.7% |
| Remaining gold disagreements surfaced | 0 / 213 | 143 / 149 (96.0%) |

The updated default is `verified_single_shot`, consistent across settings, UI and
deployment examples. Historical Qwen runs retain their original matching rules and
cannot be compared statistically with v2; `--compare-with` rejects different metric
definitions before calling a model. The old real-model 100%-surfaced claim is retired.

The release gate keeps its original quality limits. Under the independent definition,
the 10% corrupting scripted control fails the 3% upper-bound limit (observed upper
bound 3.8%). CI checks that the clean control passes and this corrupted control is
rejected. This is a mechanism check, not evidence that a real model passes release.

## Reproduce offline

From the repository root after installing the three editable packages:

```bash
advicedoc corpus generate --out advice-doc-intelligence/runs/evaluation-v2/corpus --n-per-type 1 --n-soa 120 --seed 7 --no-pdf
advicedoc eval-router --corpus advice-doc-intelligence/runs/evaluation-v2/corpus --strategy llm_validated --model fake --corruption 0.3 --out advice-doc-intelligence/docs/evaluation-v2 --n-boot 1000 --seed 7
filenote --log-level WARNING eval --model fake --corruption 0.3 --n 100 --strategies single_shot verified_single_shot --out file-note-copilot/docs/evaluation-v2/drafting --n-boot 1000
```

The router JSON records split IDs. File-note JSON identifies the metric version and
records per-meeting evidence. Timing metadata varies across machines. Historical
experiment artifacts are preserved. No new real-model metrics, cloud deployment or
real-client data are part of this revision. The Cloud Run example has ephemeral
storage and is restricted to a disposable demonstration; it cannot preserve business
approval records across instance loss or route requests across replicas reliably.

## Local verification

Python 3.12 on Windows: ruff lint/format and strict mypy pass for all three packages.
The offline suites passed 125 document-intelligence tests (97.90% branch coverage),
202 file-note unit/API tests (98.12%), and 165 operations-loop tests (98.03%). The
three required Playwright browser tests also passed, and the default-strategy API
smoke returned `verified_single_shot`. Classifier/extraction release gates passed;
the revised drafting gate passed the clean control and rejected the corrupt control.
These are local results; remote CI and a cloud deployment are separate evidence.
