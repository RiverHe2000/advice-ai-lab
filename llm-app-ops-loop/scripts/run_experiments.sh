#!/usr/bin/env bash
# Regenerates docs/experiments/*.
#
#   CPU stage (default, ~2 min, no model): demo traffic for every scenario x 3 seeds, the monitor
#   self-evaluation, the regression gate (v1 vs v2, v1 vs v2-regressed) with the fake model,
#   the canary demo (advance vs automatic rollback), a replay and an incident report.
#
#   GPU stage (STAGE=gpu or STAGE=all; needs the [hf] extra and a CUDA GPU): runs the curated
#   dataset through the regression gate with a real model answering AND judging, and judges a
#   sample of demo traces with the same model.
#
#     MODEL=D:/models/Qwen3-4B-Instruct-2507 STAGE=gpu bash scripts/run_experiments.sh
#     MODEL=Qwen/Qwen2.5-1.5B-Instruct        STAGE=gpu bash scripts/run_experiments.sh   # small baseline
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python}
STAGE=${STAGE:-cpu}
MODEL=${MODEL:-D:/models/Qwen3-4B-Instruct-2507}
SEEDS=${SEEDS:-"1 2 3"}
MINUTES=${MINUTES:-240}
OUT=docs/experiments
RUNS=runs/experiments
export PYTHONUTF8=1
mkdir -p "$OUT" "$RUNS"
started=$(date +%s)
elapsed() { echo "   ($(( $(date +%s) - started )) s elapsed)"; }

run_cpu() {
  echo "== 1. demo traffic: 7 scenarios x seeds [$SEEDS] x $MINUTES simulated minutes"
  : > "$OUT/traffic_summary.jsonl"
  for sc in steady latency_spike error_burst regressed_prompt topic_shift cost_creep pii_leak; do
    for seed in $SEEDS; do
      $PY -m opsloop --store "$RUNS/$sc-$seed.sqlite" demo traffic --scenario "scenarios/$sc.yaml" \
        --minutes "$MINUTES" --seed "$seed" --reset --summary-out "$RUNS/$sc-$seed.summary.json" > /dev/null
      $PY -c "import json,sys; d=json.load(open('$RUNS/$sc-$seed.summary.json')); d.pop('tracer_stats',None); print(json.dumps(d))" >> "$OUT/traffic_summary.jsonl"
    done
  done
  elapsed

  echo "== 2. monitor self-evaluation (time-to-detect / detection / false alarms per incident kind)"
  set +e
  $PY -m opsloop monitor evaluate \
    --scenarios scenarios/steady.yaml scenarios/latency_spike.yaml scenarios/error_burst.yaml \
                scenarios/regressed_prompt.yaml scenarios/topic_shift.yaml scenarios/cost_creep.yaml scenarios/pii_leak.yaml \
    --seeds $SEEDS --minutes "$MINUTES" --out "$OUT" --gate > "$RUNS/monitor_evaluation.stdout.json"; code=$?
  set -e
  echo "   self-evaluation gate exit $code (0 = every kind detected and false alarms <= 5 %)"
  elapsed

  echo "== 3. curated dataset from production traces (steady run, seed 1)"
  STORE="$RUNS/steady-1.sqlite"
  $PY -m opsloop --store "$STORE" sample --strategy uniform --budget 140 --seed 1 --out "$RUNS/sample_uniform.json" > /dev/null
  $PY -m opsloop --store "$STORE" sample --budget 40 --seed 1 --out "$RUNS/sample_stratified.json" > /dev/null
  $PY -m opsloop --store "$STORE" judge --sample "$RUNS/sample_uniform.json" --model fake --out "$OUT/judge_uniform.json" > /dev/null
  $PY -m opsloop --store "$STORE" judge --sample "$RUNS/sample_stratified.json" --model fake --judge-invalid-rate 0.05 --out "$OUT/judge_stratified.json" > /dev/null
  $PY -m opsloop --store "$STORE" curate --sample "$RUNS/sample_uniform.json" --reviewer "c.he" --accept-all --out "$RUNS/review_v1.jsonl" > /dev/null
  $PY -m opsloop --store "$STORE" curate --sample "$RUNS/sample_stratified.json" --reviewer "c.he" --accept-all --out "$RUNS/review_v1b.jsonl" > /dev/null
  cat "$RUNS/review_v1.jsonl" "$RUNS/review_v1b.jsonl" > "$RUNS/review_v1_all.jsonl"
  rm -rf "$RUNS/datasets"
  $PY -m opsloop --datasets-dir "$RUNS/datasets" dataset build --from-review "$RUNS/review_v1_all.jsonl" \
    --name adviser_assistant --changelog "uniform + stratified sample of the steady run" > "$OUT/dataset_v1_manifest.json"
  # v2 of the dataset: cases from the regressed-prompt incident's review queue (the loop closes)
  STORE2="$RUNS/regressed_prompt-1.sqlite"
  $PY -m opsloop --store "$STORE2" sample --since 2026-09-01T01:30:00Z --until 2026-09-01T02:30:00Z --budget 60 --seed 2 --out "$RUNS/sample_incident.json" > /dev/null
  $PY -m opsloop --store "$STORE2" curate --sample "$RUNS/sample_incident.json" --reviewer "c.he" --accept-all --out "$RUNS/review_v2.jsonl" > /dev/null
  $PY -m opsloop --datasets-dir "$RUNS/datasets" dataset build --from-review "$RUNS/review_v2.jsonl" \
    --name adviser_assistant --changelog "cases from the regressed-prompt incident review queue" > "$OUT/dataset_v2_manifest.json"
  $PY -m opsloop --datasets-dir "$RUNS/datasets" dataset diff --name adviser_assistant --from 1 --to 2 > "$OUT/dataset_diff_v1_v2.json"
  cp "$RUNS/datasets/adviser_assistant/v2.jsonl" "$OUT/dataset_adviser_assistant_v2.jsonl"
  elapsed

  echo "== 4. regression gate with the fake model: v1 vs v2 (good) and v1 vs v2-regressed (bad)"
  $PY -m opsloop --datasets-dir "$RUNS/datasets" regress --dataset adviser_assistant@v2 --candidate @v2 --baseline @v1 \
    --model fake --use-judge --out "$RUNS/regress_good" --gate > "$RUNS/regress_good.stdout.json" && echo "   good candidate: PASS (exit 0)"
  cp "$RUNS/regress_good/report.md" "$OUT/regression_gate_v2_good.md"; cp "$RUNS/regress_good/report.json" "$OUT/regression_gate_v2_good.json"
  set +e
  $PY -m opsloop --datasets-dir "$RUNS/datasets" regress --dataset adviser_assistant@v2 --candidate @v2-regressed --baseline @v1 \
    --model fake --use-judge --out "$RUNS/regress_bad" --gate > "$RUNS/regress_bad.stdout.json"; code=$?
  set -e
  echo "   regressed candidate: exit $code (1 = FAIL, as intended)"
  cp "$RUNS/regress_bad/report.md" "$OUT/regression_gate_v2_regressed_bad.md"; cp "$RUNS/regress_bad/report.json" "$OUT/regression_gate_v2_regressed_bad.json"
  elapsed

  echo "== 5. canary: v2 advances 10 -> 50 -> 100 -> promoted, v2-regressed rolls back (200 sessions, 8 h rounds)"
  for sc in canary_good canary_bad; do
    cp prompts/releases.yaml "$RUNS/releases_$sc.yaml"
    ver=$([ "$sc" = canary_good ] && echo v2 || echo v2-regressed)
    $PY -m opsloop --releases "$RUNS/releases_$sc.yaml" release start --version "$ver" --stage 10 > /dev/null
    rm -f "$RUNS/$sc.sqlite"; : > "$OUT/canary_$sc.log"
    for round in 0 1 2; do
      start=$($PY -c "from datetime import datetime, timedelta, UTC; print((datetime(2026,9,1,tzinfo=UTC)+timedelta(hours=8*$round)).strftime('%Y-%m-%dT%H:%M:%SZ'))")
      $PY -m opsloop --store "$RUNS/$sc.sqlite" --releases "$RUNS/releases_$sc.yaml" demo traffic \
        --scenario "scenarios/$sc.yaml" --minutes 480 --seed $((3 + round)) --start "$start" --use-release > "$RUNS/$sc.traffic.$round.json"
      set +e
      $PY -m opsloop --store "$RUNS/$sc.sqlite" --releases "$RUNS/releases_$sc.yaml" release auto --window 8h --apply \
        --out "$OUT/canary_${sc}_round$round.json" > /dev/null; code=$?
      set -e
      action=$($PY -c "import json; print(json.load(open('$OUT/canary_${sc}_round$round.json'))['action'])")
      echo "   $sc round $round (from $start): $action (exit $code)" | tee -a "$OUT/canary_$sc.log"
      case "$action" in promote|rollback|hold) break ;; esac
    done
    cp "$RUNS/releases_$sc.yaml" "$OUT/releases_after_$sc.yaml"
  done
  elapsed

  echo "== 6. replay + incident report from the error-burst run (seed 1)"
  STORE3="$RUNS/error_burst-1.sqlite"
  TID=$($PY -c "from opsloop.store import TraceStore; s=TraceStore('$STORE3'); r=[x for x in s.rows() if x.status=='ok' and x.attributes.get('app.intent')=='fee_pct'][0]; print(r.trace_id)")
  $PY -m opsloop --store "$STORE3" replay "$TID" --model fake --seed 1 --out "$OUT/replay_same_prompt.md" > "$RUNS/replay_same.json"
  $PY -m opsloop --store "$STORE3" replay "$TID" --model fake --seed 1 --prompt-version v2 --out "$OUT/replay_with_v2.md" > "$RUNS/replay_v2.json"
  $PY -m opsloop --store "$STORE3" incident report --since 2026-09-01T01:00:00Z --until 2026-09-01T03:00:00Z \
    --title "Incident: provider errors 2026-09-01 01:40-02:10 (simulated)" --out "$OUT/incident_report_error_burst.md" > /dev/null
  $PY -m opsloop --store "$STORE3" monitor run --out "$RUNS/monitor_error_burst" > /dev/null || true
  cp "$RUNS/monitor_error_burst/alerts.md" "$OUT/alerts_error_burst.md"
  $PY -m opsloop --store "$RUNS/regressed_prompt-1.sqlite" monitor run --out "$RUNS/monitor_regressed" > /dev/null || true
  cp "$RUNS/monitor_regressed/alerts.md" "$OUT/alerts_regressed_prompt.md"
  elapsed
  echo "CPU stage done -> $OUT"
}

run_gpu() {
  echo "== GPU stage with $MODEL (answers AND judges); dataset from the CPU stage"
  [ -d "$RUNS/datasets/adviser_assistant" ] || { echo "run the CPU stage first (dataset missing)"; exit 1; }
  # GPU_LIMIT cases of dataset v2 (the full 205 take ~5 h per gate on one RTX 4070 at ~14 tok/s);
  # every greedy answer and judge verdict is cached per request in runs/cache_<model>.sqlite, so
  # the v1 baseline half of the second gate is served from the first and a re-run is free.
  GPU_LIMIT=${GPU_LIMIT:-80}
  tag=$(basename "$MODEL" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '_')
  CACHE="$RUNS/cache_${tag}.sqlite"
  t0=$(date +%s)
  set +e
  $PY -m opsloop --datasets-dir "$RUNS/datasets" regress --dataset adviser_assistant@v2 --candidate @v2 --baseline @v1 \
    --limit "$GPU_LIMIT" --model hf --model-name "$MODEL" --cache "$CACHE" --use-judge \
    --out "$RUNS/regress_hf_good" --gate > "$RUNS/regress_hf_good.stdout.json"; code=$?
  set -e
  echo "   v1 vs v2 with the real model on $GPU_LIMIT cases: exit $code ($(( $(date +%s) - t0 )) s)"
  cp "$RUNS/regress_hf_good/report.md" "$OUT/regression_gate_hf_v2.md"; cp "$RUNS/regress_hf_good/report.json" "$OUT/regression_gate_hf_v2.json"
  t1=$(date +%s)
  set +e
  $PY -m opsloop --datasets-dir "$RUNS/datasets" regress --dataset adviser_assistant@v2 --candidate @v2-regressed --baseline @v1 \
    --limit "$GPU_LIMIT" --model hf --model-name "$MODEL" --cache "$CACHE" --use-judge \
    --out "$RUNS/regress_hf_bad" --gate > "$RUNS/regress_hf_bad.stdout.json"; code=$?
  set -e
  echo "   v1 vs v2-regressed with the real model on $GPU_LIMIT cases: exit $code ($(( $(date +%s) - t1 )) s)"
  cp "$RUNS/regress_hf_bad/report.md" "$OUT/regression_gate_hf_v2_regressed.md"; cp "$RUNS/regress_hf_bad/report.json" "$OUT/regression_gate_hf_v2_regressed.json"
  t2=$(date +%s)
  STORE="$RUNS/steady-1.sqlite"
  $PY -m opsloop --store "$STORE" sample --strategy uniform --budget 60 --seed 7 --out "$RUNS/sample_hf.json" > /dev/null
  $PY -m opsloop --store "$STORE" judge --sample "$RUNS/sample_hf.json" --model hf --model-name "$MODEL" --cache "$CACHE" --out "$OUT/judge_hf_sample.json" > /dev/null
  echo "   judged 60 demo traces with the real model ($(( $(date +%s) - t2 )) s)"
  TID=$($PY -c "from opsloop.store import TraceStore; s=TraceStore('$STORE'); r=[x for x in s.rows() if x.status=='ok' and x.attributes.get('app.intent')=='total_fees'][0]; print(r.trace_id)")
  $PY -m opsloop --store "$STORE" replay "$TID" --model hf --model-name "$MODEL" --cache "$CACHE" --out "$OUT/replay_hf.md" > /dev/null
  elapsed
  echo "GPU stage done -> $OUT"
}

case "$STAGE" in
  cpu) run_cpu ;;
  gpu) run_gpu ;;
  all) run_cpu; run_gpu ;;
  *) echo "STAGE must be cpu, gpu or all"; exit 2 ;;
esac
