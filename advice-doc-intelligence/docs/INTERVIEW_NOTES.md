# Interview notes — advice document intelligence

## The problem and the shape of the solution

**Walk me through what happens to a document.** A PDF is ingested into a `Document` of pages,
lines and tables (pdfplumber; an OCR layer would produce the same object for scans). The
classifier looks at the first two pages — word and character TF-IDF plus a small dense block of
page count, table count, digit ratio and ~30 domain-term flags — and returns a label with a
*calibrated* probability; below the abstain threshold the label is `unknown` and a human
decides. Rules pull the metadata every type has (clients, adviser, date) from labelled
first-page fields. If it is a Statement of Advice, an extractor produces the typed
`SoAExtraction`: clients, adviser, licensee, date, risk profile, scope, recommendations,
fees, product replacements, whether the authority to proceed is signed. Deterministic
validators check what can be checked (fee arithmetic, funds, product master, dates, checksums,
privacy). The router scores every critical field with P(correct) and sends the document to
review if the least certain field is below τ. Finally the extraction is reconciled against the
platform's holdings snapshot and a per-client report lists what was not implemented, what
differs in amount, what was bought that was never advised, and whether the fee charged matches
the fee agreed. All of that runs as a durable job with persisted transitions.

**Why a synthetic corpus rather than real documents?** I do not have real SoAs and could not
publish them if I did. A generator that writes the gold first and renders it into a real PDF
gives me three things a scraped corpus cannot: a known truth for every field (so accuracy is a
measurement, not an annotation exercise), control over difficulty (layout variants, distractors,
noise), and reproducibility (same seed, byte-identical gold and PDFs). The obvious cost is that
clean-text accuracy is optimistic — the README says so — and the noise experiments and the
real-model stage are how I keep myself honest.

**Why three extraction strategies?** Because the interesting question is not "can an LLM read
an SoA" but "what does the LLM buy over what an engineer writes in an afternoon, and where".
The rules extractor is deliberately decent: section detection, table parsing with a prose
fallback, fuzzy product canonicalisation, three date and three currency formats. On clean text
it is exact on all 120 SoAs at a millisecond each; at 5 % OCR-like noise it keeps 60 % of
fields. The `llm` strategy chunks by section and asks for one JSON object per section;
`llm_validated` adds one targeted re-ask per section whose hard validation fails. Same
protocol, same evaluator, paired statistics on the same documents.

## Modelling choices

**Why logistic regression for the classifier and not a transformer?** Ten well-separated
types, first-page text, a few hundred training documents, and a requirement to run in a
millisecond with a probability I can calibrate and explain. TF-IDF + LR gets macro-F1 1.000 on
the held-out set and 0.96 at 10 % character noise. A fine-tuned encoder would be the next step
if the noise rows fell, and it would sit behind the same `predict_one` protocol.

**What does calibration mean here and why do you report ECE?** The classifier's confidence
drives an abstain decision and the router's probability drives a review decision; both are
thresholds a person sets. If the confidence is not a probability the threshold is meaningless.
Two calibrations with identical accuracy behaved differently: Platt scaling on perfectly
separable folds is under-confident (ECE 0.064, mean confidence 0.94 at accuracy 1.0), so a
0.95 abstain threshold rejects *everything*; isotonic is exact (ECE 0.001). The reliability
table is in the report so the reader can see where the mass sits.

**The router is the piece you called "most interview-worthy". Why?** It turns an extraction
system into a selective-prediction system: instead of "the model is 92 % accurate" it says "at
τ = 0.984 we review 32 % of documents and the ones we auto-accept have 0 % critical-field
error". Per critical field it has features that exist at inference time — agreement with the
rules extractor, validator flags, product fuzzy score, repairs and parse failures, section
found, length and magnitude z-scores, the model's self-reported confidence — a logistic
regression, and isotonic calibration on out-of-fold predictions grouped by document. The
evaluation is a risk-coverage curve with its area, the τ that meets a residual-error target,
the review rate that implies, and three naive policies (review all / none / iff a validator
fails) with bootstrap intervals.

**And what did the router evaluation show?** Two things, honestly. On clean text the rules
extractor is exact, so "agrees with rules" is an oracle feature (coefficient +2.3) and the
router is trivially perfect — that proves the machinery, not the problem. On 5 % noisy text,
where rules are 60 % accurate, the curve is a real trade-off: 25 % review leaves 14 % residual
error, 50 % leaves 3 %, and the 1 % target is only met by reviewing almost everything, because
the corruption modes that pass every validator — a wrong but valid risk profile, a dropped
recommendation — leave no trace in those features with a scripted model. The real-model run is
what settles it; the mechanism is ready for it.

**Why validators at all if you have an LLM?** Because they are free, deterministic, and catch
the expensive mistakes: a fee that does not equal percent × balance, a recommendation to invest
more than the client has, a product not on the master, a replacement without a reason, a date
years away, a TFN in the output. At 30 % scripted corruption the re-ask cleared 44 of 58
flagged sections and lifted document accuracy from 0.36 to 0.51 (McNemar p < 0.001). And the
per-field table shows exactly what they cannot see, which is the argument for the router.

**JSON handling — what do you do when the model returns garbage?** Repair, then validate,
then retry once with the error explained, then record a missing section with the reason.
Repair strips fences and prose, removes trailing commas, and for truncation closes the open
string and brackets (falling back to cutting the last partial element). A repaired-but-wrong
value is caught by pydantic or by the evaluator; nothing is defaulted. Repairs, parse failures
and retries are counted in every report because a model that needs 20 % repairs is a different
operational animal from one that needs 1 %.

## Statistics

**Why bootstrap intervals on everything?** 120 SoAs and 165 test documents are small samples;
a point estimate of 0.96 vs 0.98 means nothing without an interval. Seeded percentile bootstrap
with 1 000 resamples on every headline number, and for a metric like macro-F1 the resample
recomputes the metric rather than averaging per-document scores.

**How do you compare two strategies?** Never from two point estimates. On the *same* documents:
a paired bootstrap on per-document differences (with a stated non-inferiority margin for the
verdict) and an exact McNemar test on document-level correctness — the discordant pairs are
what matters, and 18 / 0 at p < 0.001 is a different claim from "0.51 > 0.36".

**How do you evaluate a detector?** Against a simulator with a known truth, reporting detection
*and* false-alarm rates per kind with intervals. The holdings simulator plants four kinds of
discrepancy and adds unclamped market noise so that a 5 % tolerance produces a measured 13 %
false-alarm rate (4.6 % of faithfully implemented balances land outside ±5 %) while a 10 %
tolerance produces none but misses the two ±8 % mismatches. That is the tolerance decision made
with numbers. The same evaluation found two simulator bugs — contradictory planted truth in
two-discrepancy documents — which is what a known-truth harness is for.

## Engineering

**What breaks first in production?** Layouts I have not seen: the rules extractor is
template-shaped, and heading detection is the brittle link (fuzzy matching helps with OCR noise
but not with a licensee that calls the section "Strategy"). Second, the classifier's confidence
on out-of-distribution documents — the abstain threshold is the control, and the `unknown`
route exists precisely for that. Third, the router's features assume the rules extractor is a
useful second opinion; where it is not, the probability degrades gracefully (calibrated
low) rather than silently.

**How is the workflow durable?** A SQLite job table with states
`received → classified → extracted → validated → routed → reconciled → done | failed`, every
transition logged with timestamps and duration, each step idempotent (it checks the payload
before working), a retry cap after which the job is `failed` with the error, and reviewer
decisions stored as corrections — labelled examples for retraining the router. The test kills
the pipeline after `extracted` and resumes from a new `Workflow` over the same database; the
extraction runs once. The queue is a three-method protocol; Pub/Sub plugs in there.

**Privacy.** TFNs never appear in the corpus (masked as "recorded on file"); a TFN-shaped
number in extracted text is a hard violation with a mod-11 checksum so account numbers do not
trip it — and the ABN's last nine digits pass that checksum one time in eleven, so ABN spans are
masked first (a test found it). Log lines are redacted for names the pipeline has seen, emails,
phones and TFNs; the review API stores who decided what, not the client's details.

**Why is the LLM behind a protocol with three backends?** Tests and CI run the scripted
backend, which answers from the gold with a configurable corruption rate so that the evaluator,
validators, retries, re-asks and router are all exercised for right *and* wrong outputs. The
OpenAI-compatible backend talks to vLLM / Ollama / Azure / the gateway from my other repo with
bounded retries and usage accounting; the HF backend runs a local directory in-process. Swapping
is one flag, and every report has the same columns.

**What would you do next?** Run stage 2 (the script is ready), then: a domain-classifier style
check for out-of-distribution documents feeding the abstain decision; a retraining loop for the
router from stored corrections; per-section confidence from the model's logprobs where the
backend exposes them (a much better `self_conf` feature); and a small set of *real* scanned
documents with an OCR layer to replace the independent-character noise model.

## The model-risk angle

Every model here has a gate with a number, a probability with a calibration table, a
comparison with a paired test, and a detector with a false-alarm rate from a known truth; every
model interaction is logged and replayable from the job table; a reviewer's decision is
recorded with their identity; and the corpus and seeds make every table regenerable. That is
the evidence a model-validation function needs, and it is the same discipline as the promotion
gate in `mlflow-model-lifecycle` and the monitor evaluation in `model-monitoring-drift`.

## What the real models showed

**A zero-shot 4 B model classified every document correctly. Why keep the TF-IDF model?**
Because on this corpus accuracy cannot separate them (McNemar 0 / 0 discordant pairs) and
everything else does: 1 ms on a CPU against a second on a GPU, a calibrated probability
with an abstain threshold against a model that always answers, and no prompt to version.
The honest limitation is that a templated corpus is too easy; the OCR-noise rows are where
the classifier is actually tested, and scanned client documents are where a multimodal
model would earn its place.

**Where did the 4 B extractor fail?** Not on reading — every scalar field was exact on 40
SoAs, fee arithmetic included — but on interpretation: the authority-to-proceed boolean
(0.45, it reads the signed/unsigned wording the wrong way round) and the replacement list
(0.775, the section is "missing" in 13 documents). Both pass every validator, because a
wrong-but-valid boolean and an empty list are structurally fine. That is the residual the
scripted run predicted and the reason the router exists: with real extractions it sends
27.5 % of documents to a human and leaves 0 % residual error, where "review if a validator
fails" reviews 2.5 % and leaves 25.6 % wrong.

**Did the validators and re-asks help with a real model?** Barely with the 4 B (7 re-asks,
6 fixed, document accuracy unchanged) and slightly with the 1.5 B (46 re-asks, 10 fixed,
0 → 2 correct documents). The mechanism buys most when the model makes *checkable* mistakes
— fee arithmetic, invalid enums, product names — and the 4 B model did not make those. I
would keep it: it is cheap with the response cache, it catches the checkable class when a
model drifts, and its counters (re-asks, fixed) are a free health signal per model version.

**Why 40 documents?** Seven section prompts per SoA at ≈ 14 tokens per second on one RTX 4070
is 23 s per document; 40 documents × two models with the router re-using the cached answers
took 34 min. The intervals are wide (document accuracy 0.725 [0.60, 0.85]); the per-field
findings are not, because the failures concentrate on two fields.
