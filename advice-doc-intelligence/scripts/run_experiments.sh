#!/usr/bin/env bash
# Regenerates docs/experiments/*.
#
# Stage 1 (CPU, deterministic; what docs/RESULTS.md is written from today):
#   corpus -> classifier (sigmoid + isotonic) -> rules extractor (+ OCR-like noise) ->
#   fake-LLM extraction mechanism checks at corruption 0 / 0.1 / 0.3 -> router risk-coverage
#   (rules + fake-LLM features) -> reconciliation simulator -> workflow demo.
# Stage 2 (GPU, real models; needs the [hf] extra):
#   zero-shot classification, llm / llm_validated extraction on the 120 SoAs and the router
#   trained on real extractions, for MODEL (default D:/models/Qwen3-4B-Instruct-2507) and the
#   small baseline Qwen/Qwen2.5-1.5B-Instruct. A model name can be a local directory.
#
#   bash scripts/run_experiments.sh                    # both stages
#   SKIP_GPU=1 bash scripts/run_experiments.sh         # CPU stage only
#   MODEL=/path/to/model BASELINE=Qwen/Qwen2.5-1.5B-Instruct bash scripts/run_experiments.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python}
export PYTHONUTF8=1
MODEL=${MODEL:-D:/models/Qwen3-4B-Instruct-2507}
BASELINE=${BASELINE:-Qwen/Qwen2.5-1.5B-Instruct}
CORPUS=${CORPUS:-data/corpus}
OUT=docs/experiments
SEED=${SEED:-7}
mkdir -p "$OUT" runs

t0=$(date +%s)
step() { echo; echo "== $1  ($(( $(date +%s) - t0 ))s elapsed)"; }

# SKIP_CPU=1 re-runs only the real-model stage against an existing corpus / classifier.
if [ "${SKIP_CPU:-0}" != "1" ]; then

step "1. corpus: 60 documents x 9 types + 120 Statements of Advice, real PDFs, seed $SEED"
$PY -m advicedoc corpus generate --out "$CORPUS" --n-per-type 60 --n-soa 120 --seed $SEED \
  | tee "$OUT/corpus_generate.json"

step "2. classifier: stratified split, sigmoid and isotonic calibration"
$PY -m advicedoc train-classifier --corpus "$CORPUS" --out runs/classifier.joblib \
  --calibration sigmoid --seed 0 | tee "$OUT/classifier_train.json"
$PY -m advicedoc train-classifier --corpus "$CORPUS" --out runs/classifier_isotonic.joblib \
  --calibration isotonic --seed 0 > runs/classifier_isotonic_train.json

step "3. classifier evaluation: held-out test set, OCR-like noise, zero-shot fake baseline, gate"
$PY -m advicedoc eval-classifier --corpus "$CORPUS" --classifier runs/classifier.joblib \
  --out runs/classifier_eval --noise 0.05 0.10 --zero-shot --model fake --corruption 0.2 \
  --gate --min-macro-f1 0.95 | tee "$OUT/classifier_eval.json"
cp runs/classifier_eval/classifier_report.md "$OUT/classifier_report.md"
cp runs/classifier_eval/classifier_report.json "$OUT/classifier_report.json"
$PY -m advicedoc eval-classifier --corpus "$CORPUS" --classifier runs/classifier_isotonic.joblib \
  --out runs/classifier_eval_isotonic --noise 0.05 0.10 > runs/classifier_eval_isotonic.json
cp runs/classifier_eval_isotonic/classifier_report.md "$OUT/classifier_report_isotonic.md"
cp runs/classifier_eval_isotonic/classifier_report.json "$OUT/classifier_report_isotonic.json"

step "4. rules extractor on the 120 gold SoAs (PDF round trip) and under OCR-like noise"
$PY -m advicedoc eval-extraction --corpus "$CORPUS" --strategies rules --noise 0.0 0.02 0.05 0.10 \
  --out "$OUT" --stem extraction_rules --title "Rules extractor on 120 SoAs (clean and noisy text)" \
  --note "Text comes from the rendered PDFs through pdfplumber; noise is applied to that text." \
  --gate --min-doc-accuracy 0.95 | tee "$OUT/extraction_rules_summary.json"

step "5. fake-LLM mechanism checks: corruption 0 / 0.1 / 0.3 (validators, retries, re-asks)"
for c in 0.0 0.1 0.3; do
  tag=${c/./}
  $PY -m advicedoc eval-extraction --corpus "$CORPUS" --strategies rules llm llm_validated \
    --model fake --corruption "$c" --out "$OUT" --stem "extraction_fake_c${tag}" \
    --title "Mechanism check: scripted model, corruption $c" \
    --note "MECHANISM CHECK, not a model result: the fake backend answers from the gold with corruption probability $c per section." \
    > "runs/extraction_fake_c${tag}.json"
done

step "6. review router: risk-coverage curve on rules + fake-LLM features (mechanism check)"
$PY -m advicedoc eval-router --corpus "$CORPUS" --strategy llm_validated --model fake --corruption 0.3 \
  --out runs/router_eval --target-residual 0.01 \
  --note "MECHANISM CHECK: labels come from the fake backend at corruption 0.3; the real-model router is produced by the GPU stage." \
  | tee "$OUT/router_eval.json"
cp runs/router_eval/router_report.md "$OUT/router_report.md"
cp runs/router_eval/router_report.json "$OUT/router_report.json"
# On clean text the rules extractor is perfect, so rules-agreement is an oracle feature; the
# same run on OCR-noisy text (rules ~56 % field accuracy) is the harder mechanism check.
$PY -m advicedoc eval-router --corpus "$CORPUS" --strategy llm_validated --model fake --corruption 0.3 \
  --noise 0.05 --out runs/router_eval_noise --target-residual 0.01 \
  --note "MECHANISM CHECK on OCR-noisy text (5 % character noise): the rules extractor is no longer an oracle." \
  > runs/router_eval_noise.json
cp runs/router_eval_noise/router_report.md "$OUT/router_report_noise005.md"
cp runs/router_eval_noise/router_report.json "$OUT/router_report_noise005.json"
$PY -m advicedoc train-router --corpus "$CORPUS" --strategy llm_validated --model fake --corruption 0.3 \
  --out runs/router.joblib > runs/router_train.json

step "7. reconciliation against the simulator's planted discrepancies"
$PY -m advicedoc eval-reconcile --corpus "$CORPUS" --sources gold rules --tolerance 0.05 0.10 \
  --out runs/reconcile | tee "$OUT/reconcile_eval.json"
cp runs/reconcile/reconcile_report.md "$OUT/reconcile_report.md"
cp runs/reconcile/reconcile_report.json "$OUT/reconcile_report.json"
$PY -m advicedoc reconcile --corpus "$CORPUS" --doc-id soa_0007 --out "$OUT/reconcile_example_soa_0007.md"

step "8. workflow demo: an inbox of PDFs through classify -> extract -> validate -> route -> reconcile"
rm -rf runs/inbox && mkdir -p runs/inbox
for f in soa/soa_0001 soa/soa_0002 soa/soa_0003 fds/fds_0001 bank_statement/bank_statement_0001 correspondence/correspondence_0001; do
  cp "$CORPUS/$f.pdf" runs/inbox/
  [ -f "$CORPUS/$f.holdings.json" ] && cp "$CORPUS/$f.holdings.json" runs/inbox/
done
rm -f runs/jobs.sqlite
$PY -m advicedoc run --inbox runs/inbox --classifier runs/classifier.joblib --router runs/router.joblib \
  --strategy llm_validated --model fake --corpus "$CORPUS" --corruption 0.3 --db runs/jobs.sqlite \
  2> runs/workflow_demo.log | tee "$OUT/workflow_demo.json"

echo; echo "CPU stage done in $(( $(date +%s) - t0 ))s"
if [ "${SKIP_GPU:-0}" = "1" ]; then
  echo "SKIP_GPU=1: stopping before the real-model stage"; exit 0
fi
fi  # SKIP_CPU

# ----- Stage 2: real models -----------------------------------------------------------------
# GPU_LIMIT SoAs per model (the full 120 take ~4 h per model on one RTX 4070 at ~14 tok/s);
# every greedy answer is cached in runs/cache_<model>.sqlite, so llm_validated and the router
# evaluation re-use the llm pass instead of repeating it, and a re-run is free.
GPU_LIMIT=${GPU_LIMIT:-40}
for m in "$MODEL" "$BASELINE"; do
  tag=$(basename "$m" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '_')
  cache="runs/cache_${tag}.sqlite"
  step "9. [$tag] zero-shot classification on the held-out test set"
  $PY -m advicedoc eval-classifier --corpus "$CORPUS" --classifier runs/classifier.joblib \
    --out "runs/hf_${tag}_classifier" --noise --zero-shot --model hf --model-name "$m" --cache "$cache" \
    2> "runs/hf_${tag}_classifier.log" | tee "$OUT/hf_${tag}_classifier_eval.json" || true
  cp "runs/hf_${tag}_classifier/classifier_report.md" "$OUT/hf_${tag}_classifier_report.md" || true
  cp "runs/hf_${tag}_classifier/classifier_report.json" "$OUT/hf_${tag}_classifier_report.json" || true

  step "10. [$tag] llm and llm_validated extraction on $GPU_LIMIT SoAs (rules as the paired baseline)"
  $PY -m advicedoc eval-extraction --corpus "$CORPUS" --strategies rules llm llm_validated \
    --limit "$GPU_LIMIT" --model hf --model-name "$m" --cache "$cache" \
    --out "$OUT" --stem "hf_${tag}_extraction" \
    --title "Real model $m: rules vs llm vs llm_validated on $GPU_LIMIT SoAs" \
    --note "The first $GPU_LIMIT of the 120 gold SoAs (manifest order); greedy decoding; answers cached per request." \
    2> "runs/hf_${tag}_extraction.log" | tee "$OUT/hf_${tag}_extraction_summary.json" || true

  step "11. [$tag] review router trained and cross-validated on the real extractions"
  $PY -m advicedoc eval-router --corpus "$CORPUS" --strategy llm_validated --limit "$GPU_LIMIT" \
    --model hf --model-name "$m" --cache "$cache" \
    --out "runs/hf_${tag}_router" --target-residual 0.01 \
    --note "Labels from the real llm_validated extractions on $GPU_LIMIT SoAs; model answers served from the run-10 cache." \
    2> "runs/hf_${tag}_router.log" | tee "$OUT/hf_${tag}_router_eval.json" || true
  cp "runs/hf_${tag}_router/router_report.md" "$OUT/hf_${tag}_router_report.md" || true
  cp "runs/hf_${tag}_router/router_report.json" "$OUT/hf_${tag}_router_report.json" || true
  echo "[$tag] done at $(( $(date +%s) - t0 ))s"
done
echo; echo "all done in $(( $(date +%s) - t0 ))s - artefacts in $OUT"
