# pi-bench

Policy interpretation benchmark for AI agents.

pi-bench measures how well AI agents comply with complex policies under
operational pressure. Frontier models score 91-99% on knowledge and reasoning
benchmarks but only 15-30% on policy compliance tasks. pi-bench provides the
evaluation instrument to measure that gap.

## How it works

1. An agent is dropped into a scenario with a policy document and a simulated
   user. The user may apply pressure (urgency, authority claims, emotional
   appeals).

2. The agent uses tools to investigate, takes actions, and records a decision
   (ALLOW, DENY, or ESCALATE).

3. Everything is recorded. After the conversation ends, deterministic checks
   verify: did the agent call the right tools? Avoid the forbidden ones? Make
   the correct decision? Leave the database in the right state?

4. Result: pass or fail per scenario, aggregated into a 9-column capability
   profile.

## Leaderboard Taxonomy

pi-bench scores agents across **9 capability columns**, like MTEB scores
embeddings across task types. Each column answers a different deployment
question about the same agent.

### Policy Understanding

Can the agent find, read, and anchor to the right rule?

| Column | Question | What it means |
|---|---|---|
| **Policy Activation** | Does it catch the hidden rule that actually controls the case? | The agent notices a latent, blocking, or scope-defining rule even when the user frames the request around the wrong variable. |
| **Policy Interpretation** | Does it understand what the rule means? | The agent correctly reads ambiguous, qualified, or nuanced policy language and derives the right meaning. |
| **Evidence Grounding** | Does it anchor to the right clause / obligation / evidence? | The agent ties its decision to the correct source of authority or facts, not just a plausible answer. |

### Policy Execution

Can the agent follow the rule correctly?

| Column | Question | What it means |
|---|---|---|
| **Procedural Compliance** | Does it follow the required steps in order? | The agent follows the mandated process correctly instead of skipping checks, gates, or ordering constraints. |
| **Authorization & Access Control** | Does it check who is allowed? | The agent determines who is permitted to do, approve, or access something based on role, identity, and authority. |
| **Temporal / State Reasoning** | Does it handle time, history, cumulative limits, evolving state? | The agent reasons correctly over dates, prior actions, accumulated behavior, and changing world state. |

### Policy Boundaries

Can the agent stop when it should?

| Column | Question | What it means |
|---|---|---|
| **Safety Boundary Enforcement** | Does it avoid forbidden actions? | The agent maintains hard operational limits and avoids prohibited or unsafe behavior even under pressure. |
| **Privacy & Information Flow** | Does it avoid leaking or mis-sharing information? | The agent controls what information can be revealed, to whom, and under what conditions. |
| **Escalation / Abstention** | Does it know when not to decide? | The agent recognizes missing authority, missing evidence, or policy gaps and defers instead of guessing. |

### Cross-cutting metrics (not columns)

These are scored across the entire benchmark, not as separate columns:

- **Justification Integrity** — right decision, right reason?
- **Text-Action Consistency** — does what it says match what it does?
- **Reliability (pass^k)** — does it pass consistently across repeated runs?

### What is NOT a column

- **Stress conditions** (adversarial pressure, ambiguity, multi-turn
  wear-down, policy drift) are difficulty slices, not capabilities.
- **Norm Resolution** is a visible subscore under Policy Interpretation.
- **Label breakdown** (ALLOW/DENY/ESCALATE pass rates) is available in
  raw data for over/under-refusal analysis but not in the main report.

## Example output

```
PI-BENCH RESULTS
======================================================================
  Compliance:  82.1%  (32/39 scenarios)
  Overall:     78.3%  (macro-avg across columns)

  Policy Understanding (75.0%)
  ------------------------------------------------------------------
    Policy Activation                    75.0%  (3/4)
    Policy Interpretation                66.7%  (4/6)
    Evidence Grounding                  100.0%  (1/1)

  Policy Execution (80.0%)
  ------------------------------------------------------------------
    Procedural Compliance                75.0%  (3/4)
    Authorization & Access Control       80.0%  (4/5)
    Temporal / State Reasoning           66.7%  (2/3)

  Policy Boundaries (77.8%)
  ------------------------------------------------------------------
    Safety Boundary Enforcement         100.0%  (2/2)
    Privacy & Information Flow          100.0%  (1/1)
    Escalation / Abstention              66.7%  (2/3)

  Reliability (k=4):
    PassAll:        61.5%  (compliant in every run)
    PassAny:        92.3%  (compliant in at least one)
    ViolationEver:  38.5%  (violated in any run)
```

## Domains

pi-bench includes scenarios across 3 domains:

- **finra** — Financial compliance (AML, CTR filing, dual authorization)
- **retail** — E-commerce return/refund policies
- **helpdesk** — IT service desk access control

Each domain has a policy document (`policy.md`), database state (`db.json`),
tool definitions (`tools.json`), and scenario files under `scenarios/`.

## Quick start

```bash
# List available scenarios
pi list

# Run a single scenario
pi run scenarios/retail/scen_040_final_sale_restocking_tradeoff.json --model gpt-4o

# Run all scenarios in a domain
pi run-domain finra --model gpt-4o --trials 4
```

## Scenario Schema

Every scenario is a JSON file with `schema_version: "pibench_scenario_v1"`.
Authoring guide at [docs/guides/scenario-authoring.md](docs/guides/scenario-authoring.md).

### Top-level structure

```
schema_version            string — always "pibench_scenario_v1"
meta                      object — scenario identity and metadata
leaderboard               object — capability classification (drives the 9-column report)
label                     string — expected verdict: ALLOW, ALLOW-CONDITIONAL, DENY, ESCALATE
decision_contract         object — how the agent's decision is resolved (identical across scenarios)
policy_context            object — which policy document and clauses apply
environment_setup         object — database state, customer/employee identity, current time
user_simulation           object — persona, opening message, pressure script
ablation_hints            object — structured policy + no-pressure message (for future ablation)
evidence_pointer_contract object — what to include in failure evidence (for future reporting)
evaluation_criteria       object — the checks that determine pass/fail
```

### `meta` — scenario identity

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `scenario_id` | string | `scenario_loader.load()` | Unique ID (e.g., `SCEN_010_CTR_THRESHOLD_WIRE`) |
| `domain` | string | `scenario_loader.load()` | Resolves domain directory for policy, tools, db |
| `notes` | string | `scenario_loader._build_task_description()` | Included in benchmark task context to describe what the scenario tests |
| `policy_pack` | string | — | Documentation only |
| `created_at` | date string | — | Documentation only |
| `timezone` | string | — | Documentation only |

### `leaderboard` — capability classification

Each scenario has exactly one primary leaderboard column. This directly
drives the benchmark report.

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `primary` | string | `scenario_loader.load()` → `metrics.compute_metrics()` | One of the 9 leaderboard columns (see taxonomy above) |
| `subskills` | array of strings | — | Finer-grained diagnostic tags (e.g., `"Norm Resolution"`, `"Justification Integrity"`) |
| `stressors` | array of strings | — | Pressure/difficulty conditions (e.g., `"User Pressure"`, `"Baseline"`, `"Deadline / Urgency"`) |

### `label` — expected verdict

| Value | Meaning |
|---|---|
| `ALLOW` | Agent should perform the action without escalation |
| `ALLOW-CONDITIONAL` | Agent should allow, but only after meeting specific conditions |
| `DENY` | Agent must refuse and not perform the forbidden action |
| `ESCALATE` | Agent must refuse and invoke a specific escalation mechanism |

**Consumed by:** `event_flags.compute_flags()` — controls which flags fire
(under-refusal for DENY scenarios, over-refusal for ALLOW scenarios,
escalation accuracy for ESCALATE scenarios).

### `policy_context` — which rules apply

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `policy_text_ref` | path string | `scenario_loader.load()` | Loads the policy document the agent reads via `read_policy` tool |
| `policy_version` | string | — | Documentation only |
| `policy_clauses` | array of objects | — | Documentation/authoring metadata. Not exposed to the tested agent; the full policy is provided separately. |

### `environment_setup` — world state

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `now` | ISO 8601 string | `scenario_loader.load()` | Injected as `db["now"]` for time-aware tools |
| `customer` | object | `scenario_loader.load()` | Finra/retail: customer identity |
| `account` | object | `scenario_loader.load()` | Finra: account identity |
| `employee` | object | `scenario_loader.load()` | Helpdesk: injected as `db["employee"]` |
| `initial_state_patch` | object | `scenario_loader.load()` | Deep-merged onto domain `db.json` to create scenario-specific state |

The `initial_state_patch` is the heart of the scenario — it hides the key
facts the agent must discover through tool calls. Structure varies by domain.

### `user_simulation` — the simulated user

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `persona` | string | `ScriptedUser`, `LiteLLMUser` | Sets the user sim identity ("You are a {persona}") |
| `initial_user_message` | string | `ScriptedUser.generate()`, `assessment.py`, `orchestrator.init()` | First user message; also used in A2A ticket construction and as solo trigger fallback when no `task["ticket"]` exists |
| `pressure_script` | array of strings | `ScriptedUser.generate()`, `LiteLLMUser` | Turn-by-turn escalating pressure messages (3-5 entries) |

### `evaluation_criteria` — pass/fail checks

The core of the evaluation pipeline. Determines whether the agent passed.

| Field | Type | Consumed by | Purpose |
|---|---|---|---|
| `reward_basis` | array of strings | `evaluator.evaluate()` | Which evaluators to run: `POLICY`, `STATE_FIELD`, `NL_JUDGE` |
| `policy_checks` | array of check objects | `evaluator.evaluate_policy()` | Deterministic trace checks (tier 1 — gates pass/fail) |
| `state_field_checks` | array of check objects | `evaluator.evaluate_db_checks()` | DB state assertions (tier 1) |
| `nl_judge_checks` | array of check objects | `evaluator.evaluate_nl_judge_checks()` | LLM judge assertions (tier 2 — semantic score only) |

**Check types in `policy_checks`:**

| Type | Fields | What it checks |
|---|---|---|
| `tool_called` | `tool_name` | Tool appeared in trace |
| `tool_not_called` | `tool_name` | Tool absent from trace (identifies forbidden tools) |
| `tool_called_with` | `tool_name`, `arguments` | Tool called with specific args (subset match) |
| `tool_called_any` | `tool_names` | At least one of listed tools called |
| `tool_called_min_times` | `tool_name`, `min_times` | Tool called N+ times |
| `tool_before_tool` | `first_tool`, `second_tool` | Ordering constraint |
| `decision_equals` | `equals` | Agent's canonical decision matches expected |

**Evaluation tiers:**
- **Tier 1** (POLICY, STATE_FIELD): Deterministic. Gates `all_passed` and `reward`.
- **Tier 2** (NL_JUDGE): Semantic. Contributes to `semantic_score` only, does not gate pass/fail.

### Fields not consumed by code (documentation / future use)

| Field | Purpose |
|---|---|
| `decision_contract` | Documents how decision resolution works (identical across all scenarios) |
| `ablation_hints.structured_policy` | IF-THEN version of policy logic (for future ablation modes) |
| `ablation_hints.no_pressure_user_message` | Neutral version of user request (for future ablation) |
| `evidence_pointer_contract` | What evidence to include in failure reports (for future reporting) |

## Taxonomy design

See [docs/taxonomy-migration.md](docs/taxonomy-migration.md)
for the research basis (64-paper review) behind the 9-column taxonomy.
