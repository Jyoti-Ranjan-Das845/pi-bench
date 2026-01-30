# Green Agent Validation Checklist

## A2A Protocol Compliance (Tutorial Requirements)

- [ ] Agent card at `/.well-known/agent.json` returns valid discovery metadata
- [ ] `POST /a2a/message/send` accepts A2A messages from purple agents, returns proper responses
- [ ] `GET /health` health check endpoint works
- [ ] Docker image builds and runs — `docker compose up` starts green agent on port 8000
- [ ] Assessment flow — handles assessment requests, drives multi-turn scenarios, returns results JSON
- [ ] Results JSON format matches AgentBeats schema (`participants`, `results[]` with `pass_rate`, `score`, `max_score`, `time_used`, `task_rewards`)
- [ ] `scenario.toml` support — green agent ID + config section (`domain`, `num_tasks`) wired correctly

## Spec §5: Two-Agent Architecture

- [ ] User Simulator — Green drives the conversation (sends instructions first, not Purple)
- [ ] Environment state machine tracks `data_accessed`, `data_modified`, `data_deleted`, `consent_status`, `session_escalated`, `session_disclosed_ai`
- [ ] Dummy tool execution — Green executes Purple's tool calls against environment and returns realistic results
- [ ] Per-turn evaluation — Scorer runs after each turn (not just post-hoc)
- [ ] Purple is a black box — Green makes no assumptions about Purple internals

## Spec §5.3: Observation Model (Three Gateways)

- [ ] Text gateway — evaluates `agent_message.content`
- [ ] Tool args gateway — evaluates `tool_call.tool` + `tool_call.arguments`
- [ ] Tool result gateway — evaluates `tool_result.result`

## Spec §6: Scoring

- [ ] Deterministic-first — same trace + policy produces identical JSON bytes. LLM judge (e.g. NLI as in tau-bench) is acceptable as escape hatch but should be avoided where possible
- [ ] Verdicts — produces `COMPLIANT`, `VIOLATION`, `AMBIGUOUS_POLICY`, `AMBIGUOUS_STATE`, `AMBIGUOUS_CONFLICT`
- [ ] Evidence pointers — every violation references specific trace events by index
- [ ] `violation_rate` computed correctly
- [ ] `over_refusal_rate` computed (Restraint column)
- [ ] `procedural_violation_rate` computed (Process column)
- [ ] Ambiguity scored as test category — agents expressing uncertainty on ambiguous episodes score correctly (§6.4)
- [ ] Run-level confidence — fraction of episodes with definitive verdicts reported

## Spec §4.3: Policy Surfaces (A–G)

- [ ] A: Access & Authorization — role checks, tenant isolation tested
- [ ] B: Privacy & Data Handling — PII patterns, consent flags tested
- [ ] C: Disclosure & Communication — forbidden disclosures, required disclaimers tested
- [ ] D: Process & Procedural — step ordering, required escalations tested
- [ ] E: Safety & Risk — forbidden patterns tested
- [ ] F: Governance & Auditability — trace events, state evidence tested
- [ ] G: Ambiguity & Conflict — conflicting rules, unclear scope tested

## Spec §6.2: Task Types (Leaderboard Columns)

- [ ] Compliance — episodes that test explicit rule-following
- [ ] Understanding — episodes requiring policy interpretation through behavior
- [ ] Robustness — adversarial pressure scenarios
- [ ] Process — ordering/escalation constraint scenarios
- [ ] Restraint — over-refusal detection scenarios
- [ ] Conflict Resolution — contradicting rules scenarios
- [ ] Detection — violation identification (guardrail agents, n/a for general)
- [ ] Explainability — justification quality (LLM judge escape hatch)
- [ ] Adaptation — condition-triggered policy activation mid-conversation

## Anti-Gaming & Reproducibility (Spec §7.3)

- [ ] Trace-level auditing — full traces stored, not just scores
- [ ] Trace hashing — SHA256 of canonical JSON for reproducibility
- [ ] No single number — decomposed scores across task types

## AgentBeats Platform Integration

- [ ] Leaderboard query — DuckDB query produces correct columns (`id`, scores)
- [ ] Webhook — leaderboard repo webhook triggers leaderboard refresh on merge
- [ ] Local testing — `generate_compose.py` + `docker compose up --abort-on-container-exit` works end-to-end
