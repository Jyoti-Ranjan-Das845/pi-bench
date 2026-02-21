# PI-Bench (PolicyBeats)

A **deterministic policy compliance benchmark** for evaluating AI agents on operational policies.

**Key principle**: No LLM judges. No interpretation. Policy compliance evaluated from observable execution traces using deterministic rule checkers.

---

## 🎯 Two Enterprise Use Cases

PI-Bench serves dual purposes:

### 1. 🏆 **Official Leaderboard** (Public Benchmark)

Compare your agent against others on **all 9 dimensions** using official scenarios.

```bash
# Run official benchmark
pi-bench leaderboard \
  --agent-url http://localhost:8080 \
  --agent-name "my-agent" \
  --output results.json

# Verify submission
pi-bench verify results.json
```

**Requirements:**
- ✅ All 9 dimensions evaluated
- ✅ Official scenarios only (no modifications)
- ✅ Hash verification (tamper detection)

See [docs/LEADERBOARD.md](docs/LEADERBOARD.md) for submission guide.

---

### 2. 🔧 **Custom Runner** (Internal Testing Platform)

Use PI-Bench for internal testing with **custom policies and scenarios**.

```bash
# Run custom evaluation
pi-bench run \
  --agent-url http://localhost:8080 \
  --scenarios compliance,my-custom-scenario \
  --output results.json
```

**Features:**
- ✅ Custom policy definitions
- ✅ Custom multi-turn scenarios
- ✅ Mix official + custom resources
- ✅ Programmatic Python API

See [docs/CUSTOM_RUNNER.md](docs/CUSTOM_RUNNER.md) for extensibility guide.

---

## Why PI-Bench?

Existing policy/safety benchmarks are **fragmented and unrealistic**:

| Problem | Existing Benchmarks | PI-Bench |
|---------|---------------------|-------------|
| Text-only evaluation | Pass agents that *say* no but *would* act | Full execution traces |
| LLM judges | Non-deterministic, model-dependent | Deterministic checkers |
| Binary decisions | Force verdicts when policy is unclear | AMBIGUOUS as first-class outcome |
| Safety-only | Miss access, privacy, process, governance | 9 comprehensive dimensions |

**The result**: Prior benchmarks would pass an agent that refuses politely in text but violates policy through tools. That's theater, not compliance.

PI-Bench tests **what agents actually do**, not what they say.

---

## 📊 9 Evaluation Dimensions

All agents evaluated across:

1. **Compliance** - Follow explicit policy rules
2. **Understanding** - Interpret nuanced policy text
3. **Robustness** - Resist adversarial pressure
4. **Process** - Follow ordering constraints
5. **Restraint** - Avoid over-refusing permitted actions
6. **Conflict Resolution** - Handle contradicting rules
7. **Detection** - Identify violations in traces
8. **Explainability** - Justify policy decisions
9. **Adaptation** - Adjust when conditions trigger rules

---

## 🚀 Quick Start

### Installation

```bash
pip install pi-bench
```

### Leaderboard Mode

```bash
# Run official benchmark (all 9 dimensions)
pi-bench leaderboard \
  --agent-url http://localhost:8080 \
  --output results.json

# Dry-run (see what will be tested)
pi-bench leaderboard --dry-run --agent-url http://localhost:8080
```

### Custom Runner Mode

```bash
# List available resources
pi-bench list policies
pi-bench list scenarios
pi-bench list dimensions

# Run custom evaluation
pi-bench run \
  --agent-url http://localhost:8080 \
  --scenarios compliance,robustness \
  --output custom-results.json
```

### Python API

```python
from pi_bench.registry import Registry
from pi_bench.policy import forbid_pii_pattern, require_prior_tool
from pi_bench.types import PolicyPack
from pi_bench.a2a.protocol import MultiTurnScenario, ScenarioTurn
from pi_bench.a2a.engine import AssessmentEngine
import asyncio

# Create custom policy
my_policy = PolicyPack(
    policy_pack_id="my-policy-v1",
    version="1.0.0",
    rules=(
        forbid_pii_pattern("no-ssn", pii_type="ssn"),
        require_prior_tool("verify-first",
                          required_tool="verify_identity",
                          before_tool="access_data"),
    ),
)

# Register and use
Registry.register_policy(my_policy, "my-policy")

# Run evaluation
async def main():
    engine = AssessmentEngine(requests_per_minute=30)
    report = await engine.assess(
        purple_url="http://localhost:8080",
        scenarios=[...],  # Your scenarios
    )
    print(f"Overall Score: {report.overall_score:.2%}")

asyncio.run(main())
```

See [examples/](examples/) directory for complete examples.

---

## 🏗️ Core Concepts

### Deterministic Evaluation

- **Same trace → Same score** (always)
- No LLM judges
- No interpretation
- Observable execution only

### 19 Fundamental Rule Types

PI-Bench provides **19 fundamental rule types** as building blocks:

**DON'T (8 types):**
- `forbid_substring`, `forbid_pattern`, `forbid_pii_pattern`
- `forbid_field_disclosure`, `forbid_cross_tenant`
- `forbid_state_change`, `forbid_input_leakage`, `forbid_over_restriction`

**DO (6 types):**
- `require_tool`, `require_role`, `require_consent_flag`
- `require_state_field`, `require_escalation_on`, `require_trace_event`

**ORDER (2 types):**
- `require_prior_tool`, `sequence`

**Detection (3 types):**
- `detect_refusal`, `detect_delayed_violation`, `cumulative_risk_threshold`

### 3-Gateway Inspection

All rule checkers inspect:
- ✅ **Text Gateway** - Agent messages
- ✅ **Tool Args Gateway** - Tool call arguments
- ✅ **Tool Results Gateway** - Tool execution results

Example: `forbid_substring("SECRET")` catches violations in:
- Agent text: `"The SECRET is 42"`
- Tool args: `send_email(body="SECRET info")`
- Tool results: `{"data": "SECRET leaked"}`

### A2A Protocol

PI-Bench uses **Agent-to-Agent (A2A)** protocol:
- **Purple Agent** (under test) - Your agent via HTTP
- **Green Agent** (evaluator) - PI-Bench evaluation engine
- **Black-box testing** - No access to agent internals required

---

## 📚 Documentation

- **[docs/QUICKSTART.md](docs/QUICKSTART.md)** - Installation and basic usage
- **[docs/LEADERBOARD.md](docs/LEADERBOARD.md)** - Official benchmark submission
- **[docs/CUSTOM_RUNNER.md](docs/CUSTOM_RUNNER.md)** - Custom policies and scenarios
- **[GOAL.md](GOAL.md)** - Policy-first benchmark philosophy
- **[AGENT_SPEC.md](AGENT_SPEC.md)** - Normative specification

---

## 🔧 CLI Commands

```bash
# Official leaderboard
pi-bench leaderboard --agent-url URL [options]

# Custom evaluation
pi-bench run --agent-url URL --scenarios SCENARIOS [options]

# Verify submission
pi-bench verify results.json

# List resources
pi-bench list {policies|scenarios|dimensions}

# Version
pi-bench version

# Original scoring (legacy)
pi-bench score episodes.json --policy policy.json
```

---

## 📖 Examples

See [examples/](examples/) directory:

- **[custom_policy.py](examples/custom_policy.py)** - Creating custom policies (HIPAA, PCI-DSS)
- **[custom_scenario.py](examples/custom_scenario.py)** - Creating multi-turn test scenarios
- **[custom_runner.py](examples/custom_runner.py)** - Programmatic API usage

---

## 🧪 Example: Healthcare HIPAA Policy

```python
from pi_bench.policy import (
    forbid_pii_pattern,
    require_consent_flag,
    require_prior_tool,
)
from pi_bench.types import PolicyPack

HIPAA_POLICY = PolicyPack(
    policy_pack_id="hipaa-v1",
    version="1.0.0",
    rules=(
        # Privacy: No PII disclosure
        forbid_pii_pattern("no-ssn", pii_type="ssn"),
        forbid_pii_pattern("no-all-pii", pii_type="all"),

        # Consent: Required before processing
        require_consent_flag("hipaa-consent",
                            flag_name="patient_consent_given"),

        # Process: Verify before EHR access
        require_prior_tool("verify-before-ehr",
                          required_tool="verify_patient_identity",
                          before_tool="access_ehr"),
    ),
)
```

---

## 🏛️ Architecture

```
src/pi_bench/
├── types.py              # Immutable data types
├── trace.py              # Trace validation, normalization, hashing
├── policy/               # Policy definition & compilation
│   ├── _constructors.py  # 19 rule type constructors
│   └── _compilers.py     # Rule checkers (deterministic)
├── a2a/                  # A2A execution engine
│   ├── protocol.py       # Message types, scenarios
│   ├── engine.py         # Assessment engine
│   └── mt_scenarios.py   # Official scenarios
├── packs/                # Policy pack system
│   ├── loader.py         # Load from data/ directory
│   └── schema.py         # Validation
├── leaderboard/          # Verification system
│   ├── verify.py         # Hash verification
│   └── format.py         # Results schema
├── registry.py           # Custom resource registry
└── cli.py                # CLI entry point
```

**Key invariant**: Policy scoring is pure (no I/O, no side effects).

---

## 🎯 Design Principles

1. **Policy-literal** - Mechanical encodings, not interpretive
2. **Observable only** - Evaluate traces, not intent
3. **Deterministic** - Same inputs → identical outputs
4. **Evidence-based** - Every violation points to specific trace events
5. **No LLM judges** - Policies are operational rules, not probabilistic
6. **Black-box** - A2A protocol enables testing without agent internals

---

## 🧪 Testing

```bash
pytest tests/ -v
```

Tests cover:
- Policy violations with evidence
- Determinism (same input → same output)
- Trace validation
- All 19 rule types
- Multi-turn scenarios
- Leaderboard verification

---

## 🤝 Contributing

1. All scoring logic must be pure (no I/O)
2. New rule types must map to real policy patterns
3. Tests required for new features
4. Maintain determinism guarantee

---

## 📄 License

[Add your license here]

---

## 🙏 Citation

If you use PI-Bench in your research, please cite:

```bibtex
@misc{pibench2025,
  title={PI-Bench: Deterministic Policy Compliance Benchmark for AI Agents},
  author={[Authors]},
  year={2025},
  url={https://github.com/Jyoti-Ranjan-Das845/pi-bench}
}
```
