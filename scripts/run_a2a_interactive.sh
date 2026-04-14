#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

AGENT_MODEL="${PI_BENCH_AGENT_MODEL:-gpt-4o-mini}"
USER_MODEL="${PI_BENCH_USER_MODEL:-gpt-5.4}"
SCENARIOS_DIR="${PI_BENCH_SCENARIOS_DIR:-scenarios}"
AGENT_PORT="${PI_BENCH_AGENT_PORT:-8767}"
USER_PORT="${PI_BENCH_USER_PORT:-8768}"
CONCURRENCY="${PI_BENCH_CONCURRENCY:-1}"
MAX_STEPS="${PI_BENCH_MAX_STEPS:-40}"
USER_MAX_TURNS="${PI_BENCH_USER_MAX_TURNS:-8}"
SEED="${PI_BENCH_SEED:-42}"
SAVE_TO="${PI_BENCH_SAVE_TO:-reports/a2a_interactive_gpt4o-mini_gpt54_user_$(date +%Y%m%d_%H%M%S).json}"

export PYTHONPATH="$ROOT_DIR/src:$ROOT_DIR:${PYTHONPATH:-}"

python3 examples/a2a_demo/run_a2a.py \
  --model "$AGENT_MODEL" \
  --user-model "$USER_MODEL" \
  --user-kind litellm \
  --port "$AGENT_PORT" \
  --user-port "$USER_PORT" \
  --scenarios-dir "$SCENARIOS_DIR" \
  --seed "$SEED" \
  --max-steps "$MAX_STEPS" \
  --user-max-turns "$USER_MAX_TURNS" \
  --concurrency "$CONCURRENCY" \
  --retry-failed 1 \
  --save-to "$SAVE_TO" \
  --serve-user
