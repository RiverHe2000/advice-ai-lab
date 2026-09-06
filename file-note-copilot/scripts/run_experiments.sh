#!/usr/bin/env bash
# Regenerates docs/experiments/*.
#   CPU stage (minutes, no model): corpus, verifier self-evaluation, scripted-model strategy
#   comparison at corruption 0.1 / 0.3, pseudonymisation no-harm check, the CI gate, the
#   browser e2e log (if chromium is installed) and `terraform validate` (if Docker is up).
#   GPU stage (needs the [hf] extra and a CUDA device): all three strategies on the same 100
#   transcripts with and without pseudonymisation, for the main model and a small baseline.
#
#   bash scripts/run_experiments.sh                 # everything
#   STAGE=cpu bash scripts/run_experiments.sh       # CPU only
#   STAGE=gpu MODEL=D:/models/Qwen3-4B-Instruct-2507 bash scripts/run_experiments.sh
set -euo pipefail
cd "$(dirname "$0")/.."

PY=${PY:-python}
STAGE=${STAGE:-all}
MODEL=${MODEL:-D:/models/Qwen3-4B-Instruct-2507}
BASELINE=${BASELINE:-Qwen/Qwen2.5-1.5B-Instruct}
N=${N:-100}
SEED=${SEED:-11}
N_BOOT=${N_BOOT:-1000}
OUT=docs/experiments
CORPUS=runs/corpus/meetings.jsonl
export PYTHONUTF8=1
mkdir -p "$OUT" runs

elapsed() { echo "   ($(( $(date +%s) - $1 )) s)"; }

if [ "$STAGE" != "gpu" ]; then
  t=$(date +%s)
  echo "== 1. corpus: $N meetings, seed $SEED"
  $PY -m filenote --log-level WARNING corpus generate --n "$N" --seed "$SEED" \
    --out "$CORPUS" --stats "$OUT/corpus_stats.md" > runs/corpus.log
  elapsed "$t"

  t=$(date +%s)
  echo "== 2. verifier self-evaluation on planted hallucinations (the headline result)"
  $PY -m filenote --log-level WARNING eval-verifier --corpus "$CORPUS" --out runs/selfeval \
    --n-boot "$N_BOOT" --gate --min-detection 0.9 --max-false-alarm 0.02 > runs/selfeval.log
  cp runs/selfeval/verifier_selfeval.md "$OUT/verifier_selfeval.md"
  cp runs/selfeval/verifier_selfeval.json "$OUT/verifier_selfeval.json"
  elapsed "$t"

  for p in 0.1 0.3; do
    t=$(date +%s)
    echo "== 3. scripted model, corruption $p: single_shot vs extract_then_compose vs verified"
    $PY -m filenote --log-level WARNING eval --model fake --corruption "$p" --corpus "$CORPUS" \
      --strategies single_shot extract_then_compose verified --out "runs/fake_p$p" \
      --n-boot "$N_BOOT" > "runs/fake_p$p.log"
    cp "runs/fake_p$p/report.md" "$OUT/fake_strategies_p$p.md"
    cp "runs/fake_p$p/report.json" "$OUT/fake_strategies_p$p.json"
    elapsed "$t"
  done

  t=$(date +%s)
  echo "== 4. pseudonymisation no-harm check (verified strategy, corruption 0.3, paired)"
  $PY -m filenote --log-level WARNING eval --model fake --corruption 0.3 --corpus "$CORPUS" \
    --strategies verified --pseudonymise both --margin 0.02 --out runs/pseud \
    --n-boot "$N_BOOT" > runs/pseud.log
  cp runs/pseud/report.md "$OUT/pseudonymisation_check.md"
  cp runs/pseud/report.json "$OUT/pseudonymisation_check.json"
  elapsed "$t"

  t=$(date +%s)
  echo "== 5. CI drafting gate (what ci/file-note-copilot-ci.yml runs)"
  $PY -m filenote --log-level WARNING eval --model fake --corruption 0.1 --corpus "$CORPUS" \
    --strategies verified --out runs/ci_gate --n-boot "$N_BOOT" --gate \
    --min-f1 0.9 --min-decisions-f1 0.9 --max-hallucination 0.03 --max-omission 0.10 \
    --min-surfaced 0.95 > runs/ci_gate.log
  cp runs/ci_gate/report.md "$OUT/ci_gate.md"
  elapsed "$t"

  echo "== 6. browser end-to-end tests (skipped cleanly if chromium is not installed)"
  ( REQUIRE_E2E=${REQUIRE_E2E:-0} $PY -m pytest -m e2e --no-cov -p no:cacheprovider -v -rs \
      2>&1 | tee "$OUT/e2e_playwright.log" ) || true

  echo "== 7. terraform fmt/validate through Docker (skipped if Docker is not available)"
  if docker info > /dev/null 2>&1; then
    TF_DIR="$(pwd)/deploy/terraform"
    # Git Bash on Windows: hand Docker a native path and stop MSYS rewriting `/w` arguments.
    if command -v cygpath > /dev/null 2>&1; then TF_DIR="$(cygpath -w "$TF_DIR")"; fi
    export MSYS_NO_PATHCONV=1
    {
      echo "\$ terraform version"
      docker run --rm -v "$TF_DIR:/w" -w /w hashicorp/terraform:1.9 version
      echo "\$ terraform fmt -check -recursive"
      docker run --rm -v "$TF_DIR:/w" -w /w hashicorp/terraform:1.9 fmt -check -recursive && echo "(formatted)"
      echo "\$ terraform init -backend=false"
      docker run --rm -v "$TF_DIR:/w" -w /w hashicorp/terraform:1.9 init -backend=false -no-color
      echo "\$ terraform validate"
      docker run --rm -v "$TF_DIR:/w" -w /w hashicorp/terraform:1.9 validate -no-color
    } > "$OUT/terraform_validate.txt" 2>&1 || echo "terraform validate FAILED (see $OUT/terraform_validate.txt)"
    rm -rf deploy/terraform/.terraform deploy/terraform/.terraform.lock.hcl
  else
    echo "docker not available; skipped"
  fi
fi

if [ "$STAGE" != "cpu" ]; then
  # A 4 B model decodes at ~14 tok/s on one RTX 4070 and a meeting costs ~260 s across the
  # strategies even with the response cache, so the real-model stage uses the first N_GPU
  # meetings of the same seeded corpus. Every greedy answer is cached per request in
  # runs/cache_<model>.sqlite: the verified strategies re-use their base draft's calls, the
  # no-harm check re-uses the pseudonymised run, and a re-run is free.
  N_GPU=${N_GPU:-20}
  CORPUS_GPU=runs/corpus/meetings_gpu.jsonl
  $PY -m filenote --log-level WARNING corpus generate --n "$N_GPU" --seed "$SEED" --out "$CORPUS_GPU" > /dev/null
  first_report=""
  for m in "$MODEL" "$BASELINE"; do
    tag=$(basename "$m" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9\n' '_')
    cache="runs/cache_$tag.sqlite"
    t=$(date +%s)
    echo "== GPU: $m — four strategies, pseudonymised, on $N_GPU transcripts"
    extra=()
    [ -n "$first_report" ] && extra=(--compare-with "$first_report")
    $PY -m filenote --log-level INFO eval --model hf --model-name "$m" --corpus "$CORPUS_GPU" \
      --strategies single_shot extract_then_compose verified verified_single_shot --pseudonymise on \
      --cache "$cache" --out "runs/hf_$tag" --n-boot "$N_BOOT" "${extra[@]}" 2> "runs/hf_$tag.log" || true
    if [ -f "runs/hf_$tag/report.md" ]; then
      cp "runs/hf_$tag/report.md" "$OUT/hf_${tag}_report.md"
      cp "runs/hf_$tag/report.json" "$OUT/hf_${tag}_report.json"
      [ -z "$first_report" ] && first_report="runs/hf_$tag/report.json"
    fi
    elapsed "$t"

    if [ "$m" = "$MODEL" ]; then
      t=$(date +%s)
      echo "== GPU: $m — pseudonymisation no-harm check (verified, raw vs pseudonymised, paired)"
      $PY -m filenote --log-level INFO eval --model hf --model-name "$m" --corpus "$CORPUS_GPU" \
        --strategies verified --pseudonymise both --margin 0.02 --cache "$cache" \
        --out "runs/hf_${tag}_noharm" --n-boot "$N_BOOT" 2> "runs/hf_${tag}_noharm.log" || true
      if [ -f "runs/hf_${tag}_noharm/report.md" ]; then
        cp "runs/hf_${tag}_noharm/report.md" "$OUT/hf_${tag}_noharm_report.md"
        cp "runs/hf_${tag}_noharm/report.json" "$OUT/hf_${tag}_noharm_report.json"
      fi
      elapsed "$t"
    fi
  done
fi
echo "done — artefacts in $OUT"
