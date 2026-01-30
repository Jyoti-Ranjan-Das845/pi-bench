#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Starting containers ==="
docker compose up -d --build

echo "=== Waiting for health checks ==="
for svc in policybeats-green policybeats-purple; do
  for i in $(seq 1 30); do
    port=8000; [[ "$svc" == *purple* ]] && port=8001
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then
      echo "$svc healthy"
      break
    fi
    [ "$i" -eq 30 ] && { echo "FAIL: $svc not healthy"; docker compose logs "$svc"; docker compose down; exit 1; }
    sleep 2
  done
done

echo "=== Running assessment via A2A message/send ==="
RESULT=$(curl -sf -X POST http://localhost:8000/a2a/message/send \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": "e2e-test-1",
    "method": "message/send",
    "params": {
      "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "{\"purple_agent_url\": \"http://policybeats-purple:8001\", \"purple_agent_id\": \"mock-purple-001\", \"config\": {\"num_tasks\": 3}}"}],
        "messageId": "e2e-msg-1"
      }
    }
  }')

echo "=== Response ==="
echo "$RESULT" | python3 -m json.tool

echo "=== Validating AgentBeats format ==="
echo "$RESULT" | python3 -c "
import json, sys
data = json.load(sys.stdin)
result = data.get('result', {})
msg = result.get('message', {})
parts = msg.get('parts', [])
assert len(parts) > 0, 'No parts in response'
inner = json.loads(parts[0]['text'])
assert 'participants' in inner, 'Missing participants'
assert 'results' in inner, 'Missing results'
assert inner['participants']['agent'] == 'mock-purple-001', f'Wrong agent ID: {inner[\"participants\"][\"agent\"]}'
print('PASS: AgentBeats format validated')
print(f'  Agent: {inner[\"participants\"][\"agent\"]}')
r = inner['results'][0]
print(f'  Score: {r[\"score\"]}/{r[\"max_score\"]}')
print(f'  Pass rate: {r[\"pass_rate\"]:.1f}%')
"

echo "=== Tearing down ==="
docker compose down

echo "=== E2E TEST PASSED ==="
