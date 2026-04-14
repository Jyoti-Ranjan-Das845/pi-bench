#!/usr/bin/env bash
set -u -o pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "OPENAI_API_KEY is not set. Put it in $ROOT/.env before running."
  exit 2
fi

export PYTHONPATH="$ROOT/src:$ROOT:${PYTHONPATH:-}"

SCENARIO="${1:-scenarios/retail/scen_044_fraud_flag_cash_refund.json}"
if [[ ! -f "$SCENARIO" ]]; then
  echo "Scenario file not found: $SCENARIO"
  exit 2
fi

AGENT_MODEL="${PI_BENCH_AGENT_MODEL:-gpt-4o-mini}"
USER_MODEL="${PI_BENCH_USER_MODEL:-gpt-4.1-mini}"
SEED="${PI_BENCH_SEED:-42}"
MAX_STEPS="${PI_BENCH_MAX_STEPS:-40}"
RUNS="${PI_BENCH_REPEAT_RUNS:-3}"

if ! [[ "$RUNS" =~ ^[1-9][0-9]*$ ]]; then
  echo "PI_BENCH_REPEAT_RUNS must be a positive integer; got: $RUNS"
  exit 2
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
SCENARIO_NAME="$(basename "$SCENARIO" .json)"
OUT_DIR="$ROOT/reports/single_scenario_repeat/$RUN_ID"
mkdir -p "$OUT_DIR/results" "$OUT_DIR/logs"

cat > "$OUT_DIR/config.txt" <<EOF
run_id=$RUN_ID
scenario=$SCENARIO
agent_model=$AGENT_MODEL
user_model=$USER_MODEL
seed=$SEED
max_steps=$MAX_STEPS
runs=$RUNS
EOF

echo "Output directory: $OUT_DIR"
echo "Scenario: $SCENARIO"
echo "Agent model: $AGENT_MODEL"
echo "User model:  $USER_MODEL"
echo "Seed:        $SEED"
echo "Max steps:   $MAX_STEPS"
echo "Runs:        $RUNS"
echo

FAILED=0
for ((i = 1; i <= RUNS; i++)); do
  result_path="$OUT_DIR/results/${SCENARIO_NAME}_run_${i}.json"
  log_path="$OUT_DIR/logs/${SCENARIO_NAME}_run_${i}.log"

  echo "[run $i/$RUNS] $SCENARIO_NAME"
  if python -m pi_bench.cli run "$SCENARIO" \
    --agent-llm "$AGENT_MODEL" \
    --no-solo \
    --user-llm "$USER_MODEL" \
    --agent-max-steps "$MAX_STEPS" \
    --seed "$SEED" \
    --save-to "$result_path" \
    > "$log_path" 2>&1; then
    echo "  saved: $result_path"
  else
    echo "  failed or did not pass; see: $log_path"
    FAILED=$((FAILED + 1))
  fi
done

cat > "$OUT_DIR/summary.txt" <<EOF
run_id=$RUN_ID
scenario=$SCENARIO
agent_model=$AGENT_MODEL
user_model=$USER_MODEL
seed=$SEED
max_steps=$MAX_STEPS
runs=$RUNS
failed_runs=$FAILED
results=$OUT_DIR/results
logs=$OUT_DIR/logs
EOF

echo
echo "Saved summary: $OUT_DIR/summary.txt"
if [[ "$FAILED" -gt 0 ]]; then
  exit 1
fi
exit 0
