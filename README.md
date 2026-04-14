# pi-bench

**pi-bench** is a benchmark for evaluating whether AI agents can follow
operational policy in stateful, tool-using environments.

pi-bench is not a static policy QA benchmark. It does not only ask whether a
model can answer questions about a policy. It places an agent inside realistic
enterprise scenarios, gives it policy documents, database-backed tools, and a
simulated user, then evaluates whether the agent acts compliantly across the
full interaction.

pi-bench is designed around one core question:

> Can an agent read a governing policy, inspect the current state, use tools
> correctly, handle user pressure, and make a compliant operational decision?

The current release ships a fixed scenario set, but the benchmark is designed
to scale. New domains, policies, tools, databases, and scenarios can be added
without changing the core agent integration contract.

## What pi-bench Provides

pi-bench includes:

- **71 policy-compliance scenarios**
- **3 enterprise domains**
  - FINRA / financial compliance
  - retail refunds and returns
  - IT helpdesk access control
- **Full policy documents**
- **Stateful domain databases**
- **Structured tool schemas**
- **Multi-turn user simulation**
- **Deterministic policy and state checks**
- **Local and A2A-compatible execution paths**
- **Leaderboard-ready metrics**

Each scenario defines the policy context, initial state, user behavior,
available tools, expected decision, and evaluation checks.

## Why pi-bench Exists

Operational policy-following is not the same as generic reasoning or
instruction following.

Real deployed agents must handle:

- messy policy documents,
- hidden state triggers,
- incomplete or ambiguous user requests,
- pressure from users,
- tool calls that mutate state,
- privacy and safety boundaries,
- escalation requirements,
- and auditability across a full trace.

A model can understand a policy in isolation and still fail when it must act
under that policy in a live environment. pi-bench measures that gap.

## Benchmark Taxonomy

pi-bench reports performance across **9 capability columns**, grouped into **3
policy-compliance families**.

### Policy Understanding

| Column | What It Tests |
|---|---|
| **Policy Activation** | Whether the agent notices that a hidden or blocking policy rule applies. |
| **Policy Interpretation** | Whether the agent correctly understands policy meaning, exceptions, and conditions. |
| **Evidence Grounding** | Whether the agent grounds its decision in the right policy clause or factual evidence. |

### Policy Execution

| Column | What It Tests |
|---|---|
| **Procedural Compliance** | Whether the agent follows required steps and ordering constraints. |
| **Authorization & Access Control** | Whether the agent verifies who is allowed to request, approve, or access something. |
| **Temporal / State Reasoning** | Whether the agent handles time, history, prior actions, and changing state correctly. |

### Policy Boundaries

| Column | What It Tests |
|---|---|
| **Safety Boundary Enforcement** | Whether the agent avoids forbidden or unsafe actions. |
| **Privacy & Information Flow** | Whether the agent avoids leaking internal, private, or restricted information. |
| **Escalation / Abstention** | Whether the agent knows when to escalate, defer, deny, or abstain. |

## Failure Axes And Scenario Coverage

pi-bench scenarios are written to expose failures along the same operational
axes used in the taxonomy.

### Policy Understanding Failures

These include cases where the agent misses the controlling policy trigger,
misreads ambiguous policy language, uses the wrong clause, or reaches the right
outcome for the wrong reason.

The current scenario set covers examples such as hidden AML triggers, policy
gaps, conflicting provisions, wrong-justification traps, and evidence-grounding
failures.

### Policy Execution Failures

These include cases where the agent understands the request but fails to execute
the correct operational process.

The current scenario set covers examples such as skipped verification, missing
required tool calls, incorrect ordering, failure to update state, failure to
record a decision, and tool-action mismatch.

### Policy Boundary Failures

These include cases where the agent should stop, deny, escalate, or protect
information but fails to hold the boundary.

The current scenario set covers examples such as forbidden action attempts,
privacy leakage, disclosure of internal risk signals, under-refusal,
over-refusal, premature closure, and missed escalation.

This list is not closed. pi-bench is intended to grow with new domains, new
policy surfaces, and new failure modes as agent deployments become more
complex.

## How To Use pi-bench With Your Agent

pi-bench evaluates an agent by driving a complete assessment loop: it sends the
agent policy/task context, gives it structured tools, runs the simulated user,
executes tool calls against the environment, and scores the resulting trace.

To connect an existing agent, implement a small wrapper around it. The wrapper
does not need to change the agent's internal architecture. It only needs to
tell pi-bench how to initialize the agent, send the next message, receive tool
calls or text, and cleanly stop after the run.

At the start of an assessment, pi-bench provides:

- `benchmark_context`: policy and task context as structured nodes,
- `tools`: structured tool schemas available for the scenario,
- `message_history`: optional prior messages for resumed runs.

Agent builders can store that context however they want: system prompt, memory,
RAG store, session state, or another internal representation.

For A2A agents, pi-bench also supports a bootstrap flow. If the agent declares
the bootstrap extension, pi-bench sends the policy/task context and tool schemas
once, receives a `context_id`, and then sends only conversation turns for the
rest of the run. This avoids repeatedly sending the full policy and tool list,
which reduces token waste. If bootstrap is not supported, pi-bench falls back
to a normal stateless flow where the needed benchmark context is included in
requests.

pi-bench supports two integration modes.

### 1. Local Mode

In local mode, the tested agent is a Python object that implements the pi-bench
local agent interface.

The protocol is defined in:

```text
src/pi_bench/local/protocol.py
```

It can be imported from:

```python
from pi_bench.local import AgentProtocol
```

The protocol has five core methods:

```python
class Agent:
    def init_state(
        self,
        benchmark_context: list[dict],
        tools: list[dict],
        message_history: list[dict] | None = None,
    ) -> dict:
        ...

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]:
        ...

    def is_stop(self, message: dict) -> bool:
        ...

    def set_seed(self, seed: int) -> None:
        ...

    def stop(self, message: dict | None, state: dict | None) -> None:
        ...
```

`init_state(...)` receives the benchmark context and tool schemas. The agent
can convert them into its own prompt, memory, or internal session format.

`generate(...)` receives the latest benchmark message and returns the next
assistant message plus updated agent state. That assistant message may contain
text, tool calls, or both.

`is_stop(...)`, `set_seed(...)`, and `stop(...)` let the runtime handle
termination, reproducibility, and cleanup consistently.

The reference local agent implementation is:

```text
src/pi_bench/agents/litellm_agent.py
```

A local example is available in:

```text
examples/local_demo/
```

### 2. A2A Mode

In A2A mode, pi-bench runs as a green benchmark server and evaluates a remote
purple agent over an A2A-compatible HTTP interface.

The green server is started with:

```bash
pi-bench-green --host 0.0.0.0 --port 9009
```

A purple agent should expose an A2A message endpoint that accepts conversation
turns and returns assistant text and/or structured tool calls.

A purple agent can optionally declare the bootstrap extension in its agent card:

```text
urn:pi-bench:policy-bootstrap:v1
```

When this extension is present, pi-bench uses the one-time context handoff
described above. Otherwise, it uses the normal stateless A2A path.

A2A examples are available in:

```text
examples/a2a_demo/
```

These examples show how to serve a LiteLLM-based purple agent and how to run
pi-bench against it.

## Quick Start

Install locally:

```bash
python -m pip install -e .
```

Set your model provider key:

```bash
export OPENAI_API_KEY="..."
```

List scenarios:

```bash
pi list
```

Run a single scenario:

```bash
pi run scenarios/retail/scen_020_standard_refund.json \
  --agent-llm gpt-4o-mini \
  --no-solo \
  --user-llm gpt-4.1-mini
```

Run one domain:

```bash
pi run-domain finra \
  --agent-llm gpt-4o-mini \
  --no-solo \
  --user-llm gpt-4.1-mini \
  --num-trials 1 \
  --concurrency 1
```

Start the A2A green benchmark server:

```bash
pi-bench-green --host 0.0.0.0 --port 9009
```

Run the local A2A demo:

```bash
python examples/a2a_demo/run_a2a.py \
  --model gpt-4o-mini \
  --user-model gpt-4.1-mini \
  --serve-user \
  --scenarios-dir scenarios \
  --concurrency 1
```

## Decision Signal

Each scenario expects the agent to make a final policy decision.

The preferred decision channel is the `record_decision` tool.

Allowed decisions are:

| Decision | Meaning |
|---|---|
| `ALLOW` | The request can proceed now because policy requirements are satisfied. |
| `ALLOW-CONDITIONAL` | The request can proceed only if required conditions are met. |
| `DENY` | The request must not be fulfilled because policy blocks it or requirements are not met. |
| `ESCALATE` | The case needs review or action by the appropriate higher authority. |

Multiple `record_decision` calls are allowed. The final valid call is treated
as the canonical decision.

If no valid decision tool call is present, pi-bench can fall back to a valid
fenced JSON decision block.

## Evaluation

pi-bench evaluates each scenario using deterministic checks over the trace and
final state.

A scenario can include checks such as:

- whether a required tool was called,
- whether a forbidden tool was avoided,
- whether a tool was called with required arguments,
- whether tools were called in the required order,
- whether the final database state is correct,
- whether the canonical decision matches the expected label,
- whether the agent avoided prohibited disclosures.

The main result fields are:

| Field | Meaning |
|---|---|
| `overall_score` | Macro-average score across the 9 taxonomy columns. |
| `compliance_rate` | Strict full-pass rate across scenarios. |
| `by_group` | Scores for Policy Understanding, Policy Execution, and Policy Boundaries. |
| `by_column` | Scores for each of the 9 capability columns. |
| `event_flag_rates` | Aggregate violation, refusal, escalation, and forbidden-attempt signals. |
| `scenario_details` | Per-scenario result details, including reward, decision, checks, flags, and trace metadata. |

## Event Flags

pi-bench reports event-level signals that explain how an agent failed.

| Flag | Meaning |
|---|---|
| `violation_rate` | Fraction of completed scenarios with at least one failed policy or state check. |
| `under_refusal_rate` | Rate of allowing or acting when the scenario required denial. |
| `over_refusal_rate` | Rate of refusing or escalating when the scenario should be allowed. |
| `escalation_accuracy_rate` | Rate of correct escalation behavior on escalation scenarios. |
| `attempt_rate` | Rate of attempting forbidden tools or actions. |

These flags help explain failure shape, not only final score.

## Repository Structure

```text
src/pi_bench/              Core benchmark runtime
domains/                   Domain policies, tools, and base databases
scenarios/                 Scenario JSON files
examples/local_demo/       Local execution example
examples/a2a_demo/         A2A green/purple/user examples
scripts/                   Utility scripts for validation and runs
```

## AgentBeats / Competition Entrypoint

The benchmark exposes an AgentBeats-compatible green server through:

```bash
pi-bench-green --host 0.0.0.0 --port 9009
```

The green server evaluates a submitted purple agent and returns
leaderboard-compatible result JSON.

The expected container entrypoint is:

```text
pi-bench-green --host 0.0.0.0 --port 9009
```

## Leaderboard

The leaderboard repository is:

```text
https://github.com/Jyoti-Ranjan-Das845/pi-bench-leaderboard
```

The leaderboard reports:

- Policy Understanding
- Policy Execution
- Policy Boundaries
- Overall score
- Full compliance
- Event flag diagnostics

## Citation

If you use pi-bench, cite the benchmark and leaderboard artifacts.

```bibtex
@misc{pibench2026,
  title        = {pi-bench: A Stateful Policy-Compliance Benchmark for Tool-Using Agents},
  author       = {Pi-Bench Contributors},
  year         = {2026},
  howpublished = {\url{https://github.com/Jyoti-Ranjan-Das845/pi-bench}},
  note         = {Leaderboard: https://github.com/Jyoti-Ranjan-Das845/pi-bench-leaderboard}
}
```
