# PolicyBeats — Specification

> **Version**: 0.1 (Draft)
> **Date**: 2026-01-28
> **Status**: Open for discussion — metrics/aspects design pending research phase

---

## 1. Mission

PolicyBeats is a **diagnostic benchmark for policy-understanding agents**. It measures how well an AI agent reasons about, complies with, and resolves conflicts across diverse policy domains — not whether the agent completes a task, but whether it **follows the rules while doing so**.

Think of it as the MTEB leaderboard, but for policy compliance: an agent may excel at GDPR data-handling policies yet fail at hierarchical corporate ethics — and the benchmark makes that visible.

---

## 2. Problem Statement

Enterprises deploy AI agents that must operate under policies: return policies, codes of conduct, regulatory frameworks, access controls, escalation procedures. These agents claim "policy understanding" but there is **no standardized way to measure**:

- Does the agent **understand** a policy as written?
- Does it **reason** correctly when policies interact or conflict?
- Does it **comply** under pressure (adversarial inputs, ambiguous situations)?
- Does it handle **hierarchical policies** (regulation > company policy > team norm)?
- Where exactly does it break — which policy surface, which obligation type?

Current benchmarks either (a) test task success without policy awareness, or (b) use LLM judges that introduce non-determinism and interpretive drift.

---

## 3. Design Principles

Informed by recent benchmarking critique (see §12 Research Foundation):

| Principle | Source | Implication |
|-----------|--------|-------------|
| **Diagnostic, not competitive** | "Beyond the Benchmark" (2025) | Show failure slices, not just rankings |
| **Decomposed dimensions** | HELM 2.0 (Stanford CRFM) | No single score — explicit trade-offs across aspects |
| **Trajectory-grounded** | Multi-turn agent benchmarks | Multi-turn traces, not single-shot prompts |
| **Adversarial by design** | METR guidance (2024-2025) | Assume models optimize against the eval |
| **Evolving, not static** | "Evaluations Are Not Enough" (Anthropic, 2025) | Benchmark must adapt; static scorecards fail |
| **Reproducible & self-hosted** | CORE-Bench (2024), TheAgentCompany (2025) | Same environment, same inputs → same results. No external dependencies that drift over time |
| **Robust to paraphrasing** | "On Robustness and Reliability of Benchmark-Based Evaluation" (2025) | Scores must not collapse under rephrased policies or scenarios |
| **Architecture-aware diagnostics** | "Architecture-Aware Evaluation Metrics" (2025) | Attribute failures to specific components (policy parsing, tool use, reasoning) not just overall score |
| **Policy-literal** | PolicyBeats core | If the policy doesn't decide, neither do we |
| **Deterministic-first scoring** | PolicyBeats core, τ²-bench | Deterministic by default; LLM judge only as escape hatch for reasoning quality (see §6.2) |

---

## 4. What We Benchmark

### 4.1 The Agent Under Test

Any system that claims to understand, reason about, or enforce policies. This includes:

- **Policy-following agents** — Customer service bots, HR assistants, healthcare agents, financial advisors operating under policy constraints
- **Policy guardrail systems** — Guardrails like DynaGuard, ShieldAgent, PolicyGuard that enforce compliance on behalf of other agents
- **Purpose-built policy agents** — Agents specifically designed for policy reasoning, compliance checking, or policy Q&A
- **General-purpose agents** — LLMs given user-defined policy documents at runtime

The agent receives a **policy pack** (set of rules) and a **task** (multi-turn interaction requiring tool use and decisions). We observe its trace.

### 4.2 Policy Domains

Policies span many real-world contexts. Non-exhaustive domain list:

| Domain | Example Policies |
|--------|-----------------|
| **E-commerce / Retail** | Return windows, refund eligibility, escalation triggers |
| **Healthcare** | HIPAA data handling, consent requirements, disclosure restrictions |
| **Finance / Banking** | KYC procedures, transaction limits, fraud escalation |
| **HR / Employment** | Code of conduct, harassment policy, termination procedures |
| **Legal / Compliance** | GDPR data rights, SOC2 audit trails, PCI-DSS cardholder data |
| **Government / Public** | FOIA response rules, classification handling |
| **Enterprise Internal** | Access control, approval workflows, data retention |
| **User-Defined** | Custom policy documents provided at runtime |

### 4.3 Policy Surfaces (Horizontal Categories)

Orthogonal to domain — any domain can exercise any surface:

| Surface | What It Tests |
|---------|--------------|
| **A: Access & Authorization** | Role checks, tenant isolation, permission gates |
| **B: Privacy & Data Handling** | PII patterns, consent flags, data minimization |
| **C: Disclosure & Communication** | Forbidden disclosures, required disclaimers |
| **D: Process & Procedural** | Step ordering, required escalations, mandatory tools |
| **E: Safety & Risk** | Forbidden patterns, harm prevention |
| **F: Governance & Auditability** | Trace events, state evidence, audit trail |
| **G: Ambiguity & Conflict** | Conflicting rules, missing precedence, unclear scope |

### 4.4 Obligation Types

> **Status**: Provisional — final taxonomy to be derived from empirical analysis of real policies across domains during the research phase (§8).

Each policy rule expresses an obligation. The exact taxonomy of obligation types will emerge from studying real policy documents, but initial candidates include mandatory actions, prohibitions, ordering constraints, and state-achievement requirements. Each type will have a corresponding failure taxonomy derived directly from the policy text — we do not invent rules beyond what the policy states.

---

## 5. Evaluation Environment

### 5.1 Architecture — Two-Agent Model (A2A)

PolicyBeats uses a **two-agent architecture** with no separate orchestrator. The Purple Agent (under test) and Green Agent (evaluator + environment) communicate directly via the A2A protocol.

```
┌──────────────────┐          A2A           ┌──────────────────────────────┐
│   Purple Agent   │◄──────────────────────►│         Green Agent          │
│  (Agent Under    │   scenario instructions │                              │
│   Test)          │   ◄────────────────────│  ┌────────────────────────┐  │
│                  │                         │  │   User Simulator       │  │
│  • LLM-powered   │   text + tool calls    │  │   (scenario driver)    │  │
│  • Receives policy│  ────────────────────► │  └────────────────────────┘  │
│    pack + task   │                         │                              │
│  • Makes decisions│   tool results +      │  ┌────────────────────────┐  │
│  • Calls tools   │   next turn            │  │   Environment          │  │
│                  │   ◄────────────────────│  │   • State machine      │  │
│                  │                         │  │   • Database           │  │
│                  │                         │  │   • Dummy tools        │  │
│                  │                         │  │   • Memory / state     │  │
│                  │                         │  │     tracking           │  │
│                  │                         │  └────────────────────────┘  │
│                  │                         │                              │
│                  │                         │  ┌────────────────────────┐  │
│                  │                         │  │   Scorer               │  │
│                  │                         │  │   • Deterministic      │  │
│                  │                         │  │   • Per-turn eval      │  │
│                  │                         │  │   • Pure functions     │  │
│                  │                         │  │   • No LLM             │  │
│                  │                         │  └────────────────────────┘  │
└──────────────────┘                         └──────────────────────────────┘
```

### 5.2 Component Details

#### Purple Agent (Agent Under Test)

- **What it is**: Any external agent claiming policy compliance. Could be Claude, GPT, Gemini, a custom agent, or a fine-tuned model.
- **What it receives**: Policy pack (the rules) + task description + available tools.
- **What it does**: Engages in multi-turn conversation, makes tool calls, produces text responses.
- **What it produces**: A trace of messages and tool calls — this is what gets evaluated.
- **Key property**: Purple is a black box. Green does not know its internals.

#### Green Agent (Evaluator + Environment)

Green is the PolicyBeats agent. It owns everything except Purple:

**User Simulator** (inside Green):
- Drives the multi-turn scenario. Sends instructions that require policy decisions.
- Presents realistic user requests: "I want to delete my account", "Show me my transaction history", "Override the refund limit for this customer".
- Can escalate, change context mid-conversation, or introduce adversarial pressure.

**Environment** (inside Green):
- **State machine**: Tracks mutable session state — user context, consent status, data accessed/modified/deleted, escalation flags, audit events.
- **Database**: Domain-specific data (accounts, orders, patient records, etc.) that tools read from and write to.
- **Dummy tools**: When Purple makes a tool call, Green executes it against the environment and returns realistic results. Tools are simulated — they return plausible data and track side effects.
- **Memory / state tracking**: Every tool call, every argument, every return value, every state mutation is recorded. Side effects are explicit: `data_accessed`, `data_modified`, `data_deleted`, `consent_status`, etc.

**Scorer** (inside Green):
- Deterministic policy evaluation. Pure functions. No LLM.
- Evaluates **per-turn** during execution (not just post-hoc).
- Checks each policy clause against the trace + environment state.
- Produces verdicts with evidence pointers to specific trace events.
- Same input → same JSON bytes.

#### Interaction Flow

```
1. Green initializes environment state for scenario
2. Green (user sim) sends first instruction to Purple via A2A
3. Purple responds with text and/or tool calls
4. Green receives response:
   a. Executes any tool calls against environment (returns results to Purple)
   b. Environment state mutates (data_accessed, consent changes, etc.)
   c. Scorer evaluates Purple's response against policy rules for this turn
   d. Records: RuleCheck(rule_id, passed/failed, evidence, turn_number)
5. Green (user sim) sends next instruction based on scenario + Purple's response
6. Repeat until scenario complete or termination condition
7. Green produces final assessment: per-rule verdicts + aggregate scores
```

#### Why No Separate Orchestrator

In task-success benchmarks (like tau-bench), a separate orchestrator routes messages between agent, user, and environment as three independent parties. PolicyBeats does not need this because:

- **Green owns the environment**: The environment is part of the evaluation, not a neutral party. Green must inspect tool calls, execute them, track side effects, and evaluate compliance — all in one flow.
- **Green owns the user simulator**: The scenario is driven by the evaluator, not by an independent user. Green controls what situations Purple faces.
- **Simpler protocol**: Two-party A2A communication (Purple ↔ Green) is simpler than three-party routing. Green internally dispatches between user sim, environment, and scorer.
- **Per-turn evaluation**: Green evaluates compliance during execution, not post-hoc. This requires tight integration between environment state and scoring.

### 5.3 Observation Model

We observe through **three gateways** (all are evaluated):

```
Agent Trace
├── TEXT GATEWAY
│   └── agent_message.content    (what the agent says)
├── TOOL ARGS GATEWAY
│   ├── tool_call.tool           (which tool)
│   └── tool_call.arguments      (parameters sent)
└── TOOL RESULT GATEWAY
    └── tool_result.result       (what came back — may contain PII, etc.)
```

Plus **environment state** (state mutations, audit logs, exposed fields).

### 5.4 Additional Modalities

Beyond multi-turn tool-use (primary), we also support:

| Modality | What It Tests | Implementation |
|----------|--------------|----------------|
| **Singleton (single-turn)** | Policy understanding in isolation | Single prompt → single response, scored |
| **Multi-turn dialogue** | Compliance under conversational pressure | Orchestrator-driven (primary) |
| **Tool-use traces** | Compliance in tool arguments and results | Tool gateway inspection |
| **State mutation** | Compliance in database/environment changes | Environment state diffing |
| **Adversarial** | Robustness under attack | Adversarial scenario packs |
| **Conflict resolution** | Handling hierarchical/conflicting policies | Policy packs with intentional conflicts |

---

## 6. Scoring

### 6.1 Verdicts (Per Episode × Policy)

| Verdict | Meaning |
|---------|---------|
| `COMPLIANT` | All clauses satisfied |
| `VIOLATION` | One or more clauses violated (with evidence pointers) |
| `AMBIGUOUS_POLICY` | Policy itself is unclear |
| `AMBIGUOUS_STATE` | Trace lacks evidence to decide |
| `AMBIGUOUS_CONFLICT` | Rules conflict without precedence |

Every verdict is **deterministic** and **evidence-grounded** — pointers to exact trace events.

### 6.2 Leaderboard Task Types (Columns)

Following the MTEB pattern, leaderboard columns are **task types** (policy capabilities), not metrics. Each column aggregates a score from episodes designed to test that specific capability. The internal scoring mechanism (§6.3) produces the per-episode scores that roll up into each column.

| # | Task Type | What it tests | Derived from research |
|---|-----------|---------------|----------------------|
| 1 | **Compliance** | Follow explicit policy rules correctly | RuLES, DynaGuard, PolicyGuard |
| 2 | **Understanding** | Correctly act on policies requiring interpretation, inference, or selective disclosure | POLIS-Bench, CoPriva |
| 3 | **Robustness** | Maintain compliance under adversarial pressure, multi-turn manipulation, progressive escalation | SAGE, SALAD-Bench, RuLES (adversarial tiers) |
| 4 | **Process** | Follow ordering constraints, escalation procedures, mandatory steps | PolicyGuard (ordering/conditional), τ²-bench |
| 5 | **Restraint** | Avoid over-refusing permitted actions; maintain helpfulness within policy bounds | DynaGuard, PAM |
| 6 | **Conflict Resolution** | Handle contradicting rules, hierarchical precedence, missing scope | **Novel — no existing benchmark covers this** |
| 7 | **Detection** | Identify policy violations in observed agent traces (guardrail task) | ShieldAgent, PolyGuard, PolicyGuard |
| 8 | **Explainability** | Justify policy decisions in natural language with evidence | DynaGuard (CoT), ShieldAgent (logical verification) |
| 9 | **Adaptation** | Recognize condition-triggered policy activations and adjust behavior mid-conversation | DynaGuard (dynamic policies) — **real-world critical, under-tested** |

> **Note on Understanding (#2)**: POLIS-Bench and CoPriva measure understanding via LLM judges (cosine similarity + QwQ-32B accuracy). We improve on this by testing understanding **through behavior, not explanation**. Episodes are designed so the agent must interpret nuanced policy text to act correctly — e.g., "refunds within 30 days of purchase" when the user's purchase was 31 days ago, or "escalate if the customer is a minor" when age is implied but not stated. The agent demonstrates understanding by doing the right thing. Scored deterministically via `violation_rate` on interpretation-heavy episodes. No LLM judge needed.

> **Note on Detection (#7)**: This column applies to guardrail systems (§4.1) — systems that judge *other agents'* policy compliance. General-purpose agents score n/a on this column unless they have guardrail capabilities.

> **Note on Explainability (#8)**: This is the only column that may require an LLM judge as escape hatch (τ²-bench style, see §3 Deterministic-first scoring). All other columns are scored deterministically.

> **Note on Adaptation (#9)**: Policies are versioned, and agents work against a specified version. Adaptation tests **condition-triggered policy activation** — rules within a policy pack that activate or deactivate based on conversation state. The policy pack defines these conditions upfront; Green tracks when conditions are met; the scorer checks behavior before vs. after activation — fully deterministic. Real-world scenarios:
> - User reveals they are a minor → age-restriction rules activate mid-conversation
> - User mentions legal action → legal-hold protocol activates, data deletion paused
> - User withdraws consent → data access rules change immediately
> - Refund amount crosses threshold → escalation-required rules activate
> - Context flag set by tool result (e.g., account flagged as fraud) → restricted-action rules activate
>
> This is NOT about pushing regulatory updates mid-conversation (that's a versioning/deployment concern, not an agent capability). It IS about the agent recognizing when conversation state triggers a policy condition and adjusting behavior accordingly.

#### Future Task Types (Provisional)

The following capabilities were identified in the research survey but are deferred to future benchmark versions:

| Task Type | What it tests | Source paper | Why deferred |
|-----------|---------------|-------------|--------------|
| **Multilingual** | Policy in one language, interaction in another | POLIS-Bench (bilingual) | Significant dataset engineering; single paper coverage |
| **Cross-domain Generalization** | Transfer policy reasoning to unseen domains | PolicyGuard, PolyGuard | Tested implicitly by spanning domains, but no explicit column yet |

### 6.3 Internal Scoring (Per-Episode)

Each episode produces a deterministic score that feeds into the task type columns above. The internal scoring mechanism is:

| Signal | Type | Definition |
|--------|------|-----------|
| `violation_rate` | deterministic | Fraction of policy clauses violated in the episode |
| `over_refusal_rate` | deterministic | Fraction of permitted actions the agent wrongly refused |
| `procedural_violation_rate` | deterministic | Fraction of ordering/escalation constraints violated |
| `detection_accuracy` | deterministic | Fraction of violations correctly identified (Detection column only) |
| `explanation_quality` | LLM judge (escape hatch) | Quality of policy justification (Explainability column only) |

Different task type columns use different internal signals. For example, the Compliance column primarily uses `violation_rate`; the Restraint column primarily uses `over_refusal_rate`; the Process column uses `procedural_violation_rate`.

### 6.4 Ambiguity as a Test Category

Ambiguity is **not an error or quality signal** — it is a scored test category. The golden data includes episodes where the correct verdict is `AMBIGUOUS_*` (because the policy is genuinely unclear, rules conflict without precedence, or the trace lacks evidence to decide).

**Scoring ambiguous episodes:**

| Golden verdict | Agent behavior | Score |
|---|---|---|
| `COMPLIANT` | Complies | ✅ Correct |
| `COMPLIANT` | Refuses or hedges | ❌ Over-refusal |
| `VIOLATION` | Violates | ✅ Correct detection |
| `AMBIGUOUS_*` | Expresses uncertainty, asks for clarification, or flags the ambiguity | ✅ Correct |
| `AMBIGUOUS_*` | Confidently acts (complies or refuses without acknowledging ambiguity) | ❌ Hallucinated certainty |

Ambiguous episodes feed into **Understanding** (recognizing unclear policy text), **Conflict Resolution** (recognizing contradictions), and **Restraint** (not over-refusing when uncertain). They are full scored episodes, not discarded noise.

### 6.5 Run-Level Confidence

| Signal | Definition |
|--------|-----------|
| `confidence` | Fraction of episodes where the scorer produced a definitive verdict |

Confidence measures **eval completeness**, not policy ambiguity. An episode reduces confidence only if the scorer could not determine a verdict due to incomplete trace data (e.g., agent disconnected mid-episode, tool call returned no result, observation gap). Ambiguous golden verdicts do NOT reduce confidence — they are intentional test cases with expected correct behavior.

Reported as metadata on each eval run. A run with 95% confidence means 5% of episodes had incomplete observations, not that the policies were unclear.

---

## 7. Leaderboard

HuggingFace / MTEB style — raw metric scores as columns, no weighted aggregate. Users decide which metrics matter for their use case.

### 7.1 Primary View

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                π-bench Leaderboard                                      Confidence: 78%        │
├──────────────┬──────┬───────┬───────┬───────┬──────┬────────┬──────┬───────┬──────────────────────────────────┤
│ Model        │Cmplnc│Undrstd│Robust │Procss │Rstrnt│Conflct │Detect│Explnbl│Adapt                             │
│              │  ↑   │  ↑    │  ↑    │  ↑    │  ↑   │Resln ↑ │  ↑   │  ↑    │  ↑                               │
├──────────────┼──────┼───────┼───────┼───────┼──────┼────────┼──────┼───────┼──────────────────────────────────┤
│ Claude 4     │ 0.92 │ 0.87  │ 0.84  │ 0.90  │ 0.95 │ 0.78   │ n/a  │ 0.85  │ 0.81                             │
│ GPT-5        │ 0.89 │ 0.91  │ 0.80  │ 0.86  │ 0.97 │ 0.72   │ n/a  │ 0.82  │ 0.76                             │
│ Gemini Ultra │ 0.86 │ 0.83  │ 0.77  │ 0.82  │ 0.93 │ 0.69   │ n/a  │ 0.79  │ 0.73                             │
│ DynaGuard    │ 0.94 │ n/a   │ 0.91  │ 0.88  │ 0.72 │ n/a    │ 0.96 │ 0.90  │ 0.89                             │
│ ShieldAgent  │ 0.91 │ n/a   │ 0.88  │ 0.85  │ 0.70 │ n/a    │ 0.93 │ 0.87  │ n/a                              │
└──────────────┴──────┴───────┴───────┴───────┴──────┴────────┴──────┴───────┴──────────────────────────────────┘
```

Example leaderboard layout — scores to be populated by running Purple agents against the Green agent evaluation harness (see §5 for architecture). Each cell is the result of real multi-turn evaluation episodes scored deterministically.

Each column is one of the nine task types from §6.2. No column is "the score." Like MTEB, each column tests a distinct policy capability. A model with high Compliance but low Conflict Resolution follows simple rules but breaks when rules contradict. A guardrail system (DynaGuard, ShieldAgent) excels at Detection but may score n/a on Understanding or Conflict Resolution. A model scoring low on Adaptation handles static policies but fails when rules change mid-conversation.

**Confidence** (top-right) measures eval completeness — the fraction of episodes where the scorer produced a definitive verdict (see §6.5). It reflects observation quality, not policy ambiguity. Ambiguous episodes are scored test cases, not noise.

### 7.2 Drill-Down Filters

The primary view shows overall scores per task type. Users can filter by:

- **Policy Surface** (A-G) — see task type scores for just Access/Auth, or just Ambiguity
- **Domain** — healthcare, finance, retail, user-defined, etc.
- **Difficulty** — once tiers are empirically defined (§13)
- **Adversarial vs. normal** — performance under pressure

Each filter shows the same nine task type scores, scoped to the selected slice.

### 7.3 Anti-Gaming Measures

Per METR and "Evaluations Are Not Enough" guidance:

- **Held-out test sets**: Not all policy packs are public
- **Rotating scenarios**: Periodic refresh of adversarial cases
- **Trace-level auditing**: We store full traces, not just scores
- **Overfitting detection**: Flag models that score high on public but low on held-out
- **No single number**: Decomposed scores resist "optimize for the leaderboard" behavior
- **Submission API**: Agents submit traces; we score deterministically
- **Reproducibility**: Every score backed by full trace + verdict + evidence

---

## 8. Research Phase (MUST COMPLETE FIRST)

Before building the full benchmark, we need empirical grounding for the aspect taxonomy and metrics. This section is the immediate next step.

### 8.1 Research Questions

1. **What aspects matter most to policy agent builders?**
   - Interview / survey agent developers building policy-aware systems
   - What do they want to know about their agent's compliance?

2. **What failure modes are most common and dangerous?**
   - Analyze existing traces (internal experiments)
   - Which obligation types break most? Which surfaces?

3. **How should aspects be weighted?**
   - Is "hard benign error" (task succeeds but violates policy) 10x worse than over-restriction?
   - Domain-specific weights? (HIPAA violations > return policy violations?)

4. **What existing policy compliance benchmarks exist?**
   - DynaGuard, PolyGuard, RuLES — what did they measure? What did they miss?
   - Academic policy reasoning datasets (legal, regulatory)

5. **How do we define "policy understanding" vs "policy compliance"?**
   - Understanding: Can the agent explain the policy?
   - Compliance: Does the agent follow the policy?
   - Reasoning: Can the agent resolve conflicts/ambiguities?
   - Are these distinct measurable dimensions?

6. **What is the right granularity for aspects?**
   - Too few: hides important distinctions
   - Too many: noisy, hard to interpret
   - MTEB uses ~10 categories — is that right for policies?

### 8.2 Research Inputs Needed

The following will be provided to inform this research:

- [ ] Summary of related work (DynaGuard, PolyGuard, RuLES, etc.)
- [ ] Links to key papers on policy reasoning evaluation
- [ ] Analysis of existing PolicyBeats experiment traces
- [ ] Interviews / notes from policy agent builders
- [ ] Taxonomy of real-world policy failure cases

### 8.3 Research Deliverables

- **Aspect taxonomy document**: Final list of leaderboard dimensions with definitions
- **Metric specification**: Exact formulas, aggregation rules, weighting scheme
- **Scenario design guide**: How to construct episodes that isolate each aspect
- **Baseline results**: Initial scores on existing models to validate the taxonomy

---

## 9. Implementation Roadmap

### Phase 0: Research & Design (Current)
- Complete research phase (§8)
- Define final aspect taxonomy and metrics
- Design scenario templates for each aspect

### Phase 1: Environment Setup
- Build policy-specific domain environments
- Implement policy pack loading into environment
- Add policy-aware state tracking (database mutations → policy verdicts)
- Build domain environments: healthcare, finance, HR, retail

### Phase 2: Scenario & Policy Pack Authoring
- Author policy packs per domain (PP-01 through PP-07+)
- Create episode scenarios per aspect × domain × difficulty
- Build adversarial scenario packs
- Create conflict/hierarchy scenario packs

### Phase 3: Scoring Integration
- Wire green scorer into orchestration pipeline
- Implement per-aspect score aggregation
- Validate determinism end-to-end
- Run baseline models, verify scores match manual analysis

### Phase 4: Leaderboard
- Build leaderboard UI (inspired by HuggingFace / MTEB)
- Implement submission API (agent submits → we run → we score)
- Add drill-down views (per-aspect, per-domain, failure slices)
- Add radar charts and comparison tools

### Phase 5: Public Release
- Documentation and submission guide
- Initial model evaluations
- Paper / blog post describing methodology
- Open-source scoring code (deterministic, reproducible)

---

## 10. Key Differentiators

| Feature | PolicyBeats | DynaGuard | PolyGuard | Task-success benchmarks |
|---------|------------|-----------|-----------|------------------------|
| **Focus** | Policy understanding, reasoning, compliance & hierarchy resolution | Guard safety | Policy coverage | Task success |
| **Scoring** | Deterministic | LLM judge | Rule-based | LLM judge |
| **Multi-turn** | Yes | No | No | Yes |
| **Tool-aware** | Both gateways | No | No | Yes |
| **Ambiguity** | First-class verdict | N/A | N/A | N/A |
| **Aspects** | Decomposed dimensions | Single score | Coverage % | Single pass rate |
| **Adversarial** | Built-in | Yes | No | No |
| **Deterministic** | Yes (byte-level) | No | Partial | No |

---

## 11. How PolicyBeats Differs from Task-Success Benchmarks

Task-success benchmarks (e.g., tau-bench) measure whether an agent completes a customer service task correctly. They are **domain-specific** (airline, retail, telecom) and evaluate **task completion** via environment state comparison and action matching.

PolicyBeats is a **horizontal policy benchmark** that is **domain-agnostic**. The same policy surfaces (access control, privacy, disclosure, process, safety, governance, ambiguity) apply across every domain. Our dataset intentionally spans all domains — healthcare, finance, retail, HR, government, enterprise, user-defined — because we are benchmarking **policy reasoning capability**, not task completion in a specific domain.

| Dimension | Task-Success Benchmarks | PolicyBeats |
|-----------|------------------------|-------------|
| **Focus** | Did the agent complete the task? | Did the agent follow the policy? |
| **Scope** | Per-domain (airline, retail) | Horizontal across all domains |
| **Architecture** | 3-party: Agent ↔ Orchestrator ↔ Environment | 2-party: Purple ↔ Green (env inside Green) |
| **Evaluation timing** | Post-execution (compare final state) | Per-turn during execution |
| **Environment role** | Neutral tool provider | Part of the evaluator (tracks compliance) |
| **User simulator role** | Independent LLM party | Controlled by Green (drives policy scenarios) |
| **What tools test** | Task correctness | Policy compliance (side effects, access patterns) |
| **Primary metric** | Pass@k task completion | Violation rate, over-restriction, ambiguity handling |
| **Dataset design** | Domain tasks | Every domain, every policy surface |

---

## 12. Research Foundation

### Core References

**Benchmarking Methodology**:
- "Evaluations Are Not Enough" (2025) — benchmarks must evolve, be adversarial, not static scorecards
- METR evaluation papers (2024-2025) — test capabilities not surface behaviors; assume models optimize against eval
- HELM 2.0 (Stanford CRFM) — decompose into dimensions; no single metric suffices
- "Beyond the Benchmark" position papers (2025) — diagnostic not competitive; failure taxonomy emphasis
- CORE-Bench (2024) — computational reproducibility as benchmark; self-hosted, isolated evaluation environments
- "On Robustness and Reliability of Benchmark-Based Evaluation" (2025) — benchmarks must survive paraphrasing; absolute scores fragile even when rankings stable
- "Toward Architecture-Aware Evaluation Metrics" (2025) — attribute failures to specific agent components, not just overall score
- TheAgentCompany (2025) — self-hosted reproducible environments; checkpoint + execution-based evaluation

**Policy-Specific** (to be expanded in research phase):
- DynaGuard (2025) — dynamic guardrails with user-defined policies
- PolyGuard / GuardSet-X (2025) — 400+ risk categories, 1000+ safety rules, 150+ policy documents across 8 domains
- PAM (2025) — policy-aligned moderation filters at scale
- ShieldAgent (2025) — verifiable safety policy reasoning via logical verification
- Keep Security! / CoPriva (EMNLP 2025) — benchmarking security policy preservation under indirect attacks
- POLIS-Bench (2025) — multi-dimensional evaluation for bilingual policy tasks in government
- PolicyGuard (2025) — efficient guardrails for policy violation detection
- SAGE (EMNLP 2025) — generic framework for LLM safety evaluation via multi-turn adversarial conversations
- SALAD-Bench (ACL 2024) — hierarchical safety taxonomy (6 domains, 16 tasks, 66 categories)
- RuLES — rule-following evaluation

### Research → Task Type Mapping

How each policy paper maps to our leaderboard task types (§6.2):

| Paper | Cmplnc | Undrstd | Robust | Procss | Rstrnt | Conflict | Detect | Explain | Adapt |
|-------|--------|---------|--------|--------|--------|----------|--------|---------|-------|
| **DynaGuard** (2025) | ✅ multi-rule | | ✅ jailbreak resist | | ✅ dynamic policies | | ✅ violation detect | ✅ CoT justify | ✅ dynamic policy |
| **RuLES** (2023) | ✅ rule following | | ✅ adversarial tiers | | | | | | |
| **SAGE** (EMNLP 2025) | | | ✅ multi-turn pressure | | | | | | |
| **PolyGuard** (2025) | | | ✅ attack-enhanced | | | | ✅ 400+ categories | | |
| **ShieldAgent** (2025) | | | | | | | ✅ 7 risk types × 6 envs | ✅ logical verification | |
| **POLIS-Bench** (2025) | | ✅ clause retrieval | | | | | | | |
| **CoPriva** (EMNLP 2025) | | ✅ selective disclosure | ✅ indirect attacks | | | | | | |
| **SALAD-Bench** (ACL 2024) | | | ✅ 6→16→66 taxonomy | | | | | | |
| **PolicyGuard** (2025) | ✅ obligations | | | ✅ ordering, conditional | | | ✅ trajectory detect | | |
| **PAM** (2025) | | | | | ✅ moderation filters | | | | |
| **τ²-bench** (2025) | | | | ✅ procedural | | | | | |

**Coverage summary**:
- Well-covered (3+ papers): Compliance, Robustness, Detection
- Moderate (2 papers): Understanding, Process, Restraint, Explainability
- Under-tested (1 paper): **Adaptation** — only DynaGuard; real-world critical
- Novel (0 papers): **Conflict Resolution** — our unique contribution

### Key Insight

> No existing benchmark measures **policy understanding, reasoning, hierarchy resolution, and compliance as a first-class, decomposed, deterministic, multi-turn, tool-aware evaluation**. π-bench fills this gap.

---

## 13. Open Questions & Decisions

### Resolved

1. **Aspect taxonomy** — Final leaderboard dimensions to be determined from research phase analysis (§8). Not invented upfront.

2. **Weighting scheme** — No aggregation weighting. Like the MTEB embeddings leaderboard on HuggingFace, we show raw per-aspect scores side by side. Users decide which aspects matter for their use case. No single weighted average.

3. **User-defined / OOD policies** — The benchmark includes out-of-distribution (OOD) policy packs that no model has seen during training. This tests genuine policy reasoning vs. memorization.

4. **Temporal evolution** — Not a priority now. Address after initial release.

5. **Cost model** — Episodes × models × domains — acceptable for now. Revisit if benchmark grows.

### Open

6. **Human baseline (MUST HAVE)** — Human expert scores are required for calibration. Without them, we cannot know if a model score of 0.85 is "good" or "terrible" — only a human baseline gives meaning to the numbers.
   - **Initial approach**: Build a golden dataset with human-annotated verdicts. Multiple annotators per episode.
   - **Inter-annotator agreement**: Use **Cohen's kappa** (for 2 annotators) or **Fleiss' kappa** (for 3+) to measure agreement. Report kappa scores alongside benchmark results. If kappa is low on a policy clause, that clause may be ambiguous — which is itself a finding.
   - **Long-term**: Maintain a standing panel of policy domain experts (legal, compliance, HR, healthcare) who periodically re-annotate as scenarios evolve.

7. **What are difficulty tiers?** — We have not yet defined what Easy / Medium / Hard means for policy compliance. Candidate definitions to explore in research phase:
   - Number of active policy rules in the episode?
   - Presence of conflicting rules?
   - Adversarial pressure from user simulator?
   - Ambiguity in the policy text itself?
   - This needs empirical grounding — not something we define a priori.

---

## Appendix A: Glossary

| Term | Definition |
|------|-----------|
| **Policy Pack** | Set of encoded policy rules for a domain |
| **Episode** | One multi-turn interaction (task + trace + state) |
| **Trace** | Ordered sequence of messages and tool calls |
| **Verdict** | COMPLIANT / VIOLATION / AMBIGUOUS_* per policy clause |
| **Task Type** | Leaderboard column — a distinct policy capability (Compliance, Understanding, etc.) |
| **Gateway** | Observation point: text gateway or tool gateway |
| **Purple Agent** | Agent under test |
| **Green Agent** | Evaluator + environment (user sim, tools, scorer) |
| **Policy Surface** | Category of policy concern (A-G) |
| **Obligation** | What the policy requires (provisional — see §4.4) |
| **Confidence** | Fraction of episodes with definitive scorer verdicts — measures eval completeness, not policy clarity (see §6.5) |
| **π-bench** | Proposed benchmark name (π for Policy) |
