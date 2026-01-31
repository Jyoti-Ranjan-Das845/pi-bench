"""
Policy clause encodings and compilation to pure checkers.

PolicyBeats is POLICY-LITERAL, not rule-centric.

These are NOT invented rules. They are:
- Mechanical encodings of explicit policy clauses
- Lossless operationalizations of policy text
- Checkers that evaluate exactly what the policy says

If a policy clause cannot be encoded without interpretation → AMBIGUOUS.

Two layers:
1. Clause encoding constructors (data)
2. Compilation to executable checkers (pure functions)

Invariants:
- compile_rule returns AMBIGUOUS_POLICY for unknown clause kinds
- All compiled checkers are pure: (Trace, ExposedState) -> RuleResult
- No side effects, no I/O, no interpretation
"""

# Types
from ._types import PolicyFn, RuleFn, RuleResult

# Constructors
from ._constructors import (
    cumulative_risk_threshold,
    detect_delayed_violation,
    detect_refusal,
    forbid_cross_tenant,
    forbid_field_disclosure,
    forbid_input_leakage,
    forbid_over_restriction,
    forbid_pattern,
    forbid_pii_pattern,
    forbid_state_change,
    forbid_substring,
    require_consent_flag,
    require_escalation_on,
    require_prior_tool,
    require_role,
    require_state_field,
    require_tool,
    require_trace_event,
    sequence,
)

# Compilation
from ._pack import compile_policy_pack, compile_rule

__all__ = [
    # Types
    "PolicyFn",
    "RuleFn",
    "RuleResult",
    # Constructors
    "cumulative_risk_threshold",
    "detect_delayed_violation",
    "detect_refusal",
    "forbid_cross_tenant",
    "forbid_field_disclosure",
    "forbid_input_leakage",
    "forbid_over_restriction",
    "forbid_pattern",
    "forbid_pii_pattern",
    "forbid_state_change",
    "forbid_substring",
    "require_consent_flag",
    "require_escalation_on",
    "require_prior_tool",
    "require_role",
    "require_state_field",
    "require_tool",
    "require_trace_event",
    "sequence",
    # Compilation
    "compile_policy_pack",
    "compile_rule",
]
