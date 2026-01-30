# Competition Gap Plan

**Date**: 2026-01-29
**Goal**: Make PolicyBeats competition-ready end-to-end

## Gap Analysis

### What We Have (Working)
- Dockerfile + GitHub Actions → publishes green agent image
- A2A server with `/.well-known/agent.json`, `/a2a/message/send`, `/assess/multi-turn`
- Multi-turn engine (`engine.py`) with 9-column scoring, tool-call loops, per-turn eval
- Single-turn assessment (`assessment.py`) with AgentBeats results format
- Results JSON with `participants` + `results` array
- `docker-compose.yml` for local green agent

### Gap 1: `/a2a/message/send` uses old single-turn flow
**Severity**: CRITICAL — this is what the competition runner calls
**Problem**: `server.py:261` calls `run_assessment()` (single-turn, `assessment.py`) instead of `run_multi_turn_assessment()` (multi-turn, `engine.py`). The multi-turn engine has tool-call loops, per-turn eval, 9-column scoring — none of that runs when the competition sends a request.
**Fix**: Wire `message_send()` to call `run_multi_turn_assessment()` and convert its `AssessmentReport` to AgentBeats JSON format.

### Gap 2: No `scenario.toml`
**Severity**: HIGH — leaderboard repo needs this to configure assessment runs
**Problem**: The leaderboard expects a `scenario.toml` that defines benchmark metadata, scoring dimensions, and scenario configuration.
**Fix**: Create `scenario.toml` at project root with PolicyBeats benchmark config.

### Gap 3: Results JSON uses localhost URL instead of purple agent's AgentBeats ID
**Severity**: MEDIUM — leaderboard needs proper agent ID
**Problem**: `results.py` correctly accepts `purple_agent_id` param, but the A2A message/send handler passes whatever the caller sends. Need to ensure the competition runner's purple agent ID flows through.
**Fix**: Already handled if Gap 1 is fixed correctly — `run_multi_turn_assessment` gets the ID from the A2A request and passes it to the results formatter.

### Gap 4: No purple agent container for local E2E testing
**Severity**: MEDIUM — can't validate full flow locally
**Problem**: `docker-compose.yml` only has green agent. No way to test the complete green↔purple A2A loop.
**Fix**: Add a mock purple agent service to `docker-compose.yml` that responds to A2A messages.

### Gap 5: `AssessmentReport` → AgentBeats JSON conversion missing
**Severity**: CRITICAL (blocks Gap 1)
**Problem**: `engine.py:run_multi_turn_assessment()` returns `AssessmentReport` (protocol.py dataclass), but AgentBeats needs the `{"participants": {...}, "results": [...]}` format. No converter exists for `AssessmentReport` → AgentBeats JSON.
**Fix**: Add `report_to_agentbeats()` function in `results.py` that maps the 9-column `AssessmentReport` to AgentBeats format.

## Task Breakdown

### Phase 1: Wire Multi-Turn Engine into A2A (Gaps 1 + 5)

- [ ] **T1.1**: Add `report_to_agentbeats(report: AssessmentReport, purple_agent_id: str, time_used: float) -> dict` to `results.py`
  - Map `report.overall_score` → `score`
  - Map `report.scores_by_rule` → per-rule metrics
  - Map `report.scores_by_category` → category breakdown
  - Map `report.scores_by_task_type` → task type breakdown
  - Include `report.scenario_results` as episodes
  - Set `participants.agent` = `purple_agent_id`

- [ ] **T1.2**: Update `server.py:message_send()` to call `run_multi_turn_assessment()`
  - Extract `purple_agent_url` and `purple_agent_id` from the A2A message (existing parse logic works)
  - Call `run_multi_turn_assessment(purple_url=purple_agent_url)`
  - Convert report via `report_to_agentbeats()`
  - Return as A2A response

- [ ] **T1.3**: Remove or deprecate old `/assess` endpoint (uses single-turn flow)
  - Keep `/assess/multi-turn` as the direct test endpoint
  - Mark `/assess` as deprecated or remove

### Phase 2: Create `scenario.toml`

- [ ] **T2.1**: Create `scenario.toml` with:
  - `[benchmark]` section: name, version, description, category
  - `[scoring]` section: dimensions (safety, compliance, precision, robustness, overall)
  - `[scenarios]` section: count, surfaces, difficulty levels
  - `[agent]` section: green agent URL, Docker image ref, capabilities

### Phase 3: Local E2E Testing (Gap 4)

- [ ] **T3.1**: Create `src/policybeats/purple/mock_server.py` — minimal FastAPI purple agent that:
  - Serves `/.well-known/agent.json`
  - Handles `/a2a/message/send` with a simple LLM-backed or rule-based responder
  - Uses litellm for LLM calls (or env var to pick model)

- [ ] **T3.2**: Add mock purple to `docker-compose.yml`:
  ```yaml
  policybeats-purple:
    build:
      context: .
      dockerfile: Dockerfile.purple
    ports:
      - "8001:8001"
    environment:
      - OPENAI_API_KEY=${OPENAI_API_KEY}
  ```

- [ ] **T3.3**: Add E2E test script `scripts/e2e_test.sh`:
  - `docker compose up -d`
  - Wait for both health checks
  - `curl` green's `/a2a/message/send` with purple's URL
  - Validate response has AgentBeats format
  - `docker compose down`

### Phase 4: Validation

- [ ] **T4.1**: Unit test `report_to_agentbeats()` with a mock `AssessmentReport`
- [ ] **T4.2**: Integration test: run multi-turn assessment against mock purple, verify AgentBeats JSON schema
- [ ] **T4.3**: Verify `scenario.toml` parses correctly (toml.load)

## Priority Order
1. T1.1 → T1.2 → T1.3 (critical path — unblocks competition)
2. T2.1 (needed for leaderboard)
3. T3.1 → T3.2 → T3.3 (local validation)
4. T4.1 → T4.2 → T4.3 (confidence)
