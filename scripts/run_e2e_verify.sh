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

AGENT_MODEL="${PI_BENCH_AGENT_MODEL:-gpt-4o-mini}"
# Cheap GPT-4-class default. Override PI_BENCH_USER_MODEL in .env if you
# want to test with a different user simulator model.
USER_MODEL="${PI_BENCH_USER_MODEL:-gpt-4.1-mini}"
CONCURRENCY="${PI_BENCH_CONCURRENCY:-3}"
SEED="${PI_BENCH_SEED:-42}"
MAX_STEPS="${PI_BENCH_MAX_STEPS:-40}"

if ! [[ "$CONCURRENCY" =~ ^[1-9][0-9]*$ ]]; then
  echo "PI_BENCH_CONCURRENCY must be a positive integer; got: $CONCURRENCY"
  exit 2
fi

RUN_ID="$(date +%Y%m%d_%H%M%S)"
OUT_DIR="$ROOT/reports/e2e_verify/$RUN_ID"
mkdir -p "$OUT_DIR"/{single,domain,full,logs}

SCENARIOS=(
  "scenarios/finra/scen_015_cross_account_pattern.json"
  "scenarios/helpdesk/scen_046_cross_employee_disclosure.json"
  "scenarios/retail/scen_044_fraud_flag_cash_refund.json"
)

DOMAINS=(
  "finra"
  "helpdesk"
  "retail"
)

run_single_scenario() {
  local scenario="$1"
  local name
  name="$(basename "$scenario" .json)"
  echo "[single] $name"
  python -m pi_bench.cli run "$scenario" \
    --agent-llm "$AGENT_MODEL" \
    --no-solo \
    --user-llm "$USER_MODEL" \
    --agent-max-steps "$MAX_STEPS" \
    --seed "$SEED" \
    --save-to "$OUT_DIR/single/$name.json" \
    > "$OUT_DIR/logs/single_$name.log" 2>&1
}

run_domain_set() {
  local domain="$1"
  echo "[domain] $domain"
  python -m pi_bench.cli run-domain "$domain" \
    --agent-llm "$AGENT_MODEL" \
    --no-solo \
    --user-llm "$USER_MODEL" \
    --agent-max-steps "$MAX_STEPS" \
    --num-trials 1 \
    --concurrency "$CONCURRENCY" \
    --seed "$SEED" \
    --save-to "$OUT_DIR/domain/$domain.json" \
    > "$OUT_DIR/logs/domain_$domain.log" 2>&1
}

run_full_set() {
  echo "[full] all active scenarios"
  python "$ROOT/scripts/run_full_set_local.py" \
    --agent-llm "$AGENT_MODEL" \
    --user-llm "$USER_MODEL" \
    --concurrency "$CONCURRENCY" \
    --seed "$SEED" \
    --max-steps "$MAX_STEPS" \
    --save-to "$OUT_DIR/full/full_set.json" \
    > "$OUT_DIR/logs/full_set.log" 2>&1
}

FAILED=0

echo "Output directory: $OUT_DIR"
echo "Agent model: $AGENT_MODEL"
echo "User model:  $USER_MODEL"
echo "Concurrency: $CONCURRENCY"
echo

cat > "$OUT_DIR/config.txt" <<EOF
run_id=$RUN_ID
agent_model=$AGENT_MODEL
user_model=$USER_MODEL
concurrency=$CONCURRENCY
seed=$SEED
max_steps=$MAX_STEPS
EOF

echo "Running 3 single-scenario commands. These run concurrently at script level."
pids=()
names=()
for scenario in "${SCENARIOS[@]}"; do
  run_single_scenario "$scenario" &
  pids+=("$!")
  names+=("$(basename "$scenario" .json)")
done
for i in "${!pids[@]}"; do
  if ! wait "${pids[$i]}"; then
    echo "[single] ${names[$i]} failed; see $OUT_DIR/logs/single_${names[$i]}.log"
    FAILED=$((FAILED + 1))
  fi
done

echo
echo "Running 3 domain commands with --concurrency $CONCURRENCY."
for domain in "${DOMAINS[@]}"; do
  if ! run_domain_set "$domain"; then
    echo "[domain] $domain failed; see $OUT_DIR/logs/domain_$domain.log"
    FAILED=$((FAILED + 1))
  fi
done

echo
echo "Running full-set command with --concurrency $CONCURRENCY."
if ! run_full_set; then
  echo "[full] full_set failed; see $OUT_DIR/logs/full_set.log"
  FAILED=$((FAILED + 1))
fi

cat > "$OUT_DIR/summary.txt" <<EOF
run_id=$RUN_ID
agent_model=$AGENT_MODEL
user_model=$USER_MODEL
concurrency=$CONCURRENCY
seed=$SEED
max_steps=$MAX_STEPS
result_dir=$OUT_DIR
failed_commands=$FAILED

single_results=$OUT_DIR/single
domain_results=$OUT_DIR/domain
full_results=$OUT_DIR/full
logs=$OUT_DIR/logs
EOF

echo
echo "Saved results under: $OUT_DIR"
echo "Summary: $OUT_DIR/summary.txt"
if [[ "$FAILED" -gt 0 ]]; then
  exit 1
fi
exit 0
