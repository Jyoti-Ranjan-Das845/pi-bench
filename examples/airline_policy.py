"""
Example: Airline Domain Policy Pack

This policy pack defines rules for an airline customer service agent.
Based on tau-bench airline domain constraints.

Usage:
    from examples.airline_policy import AIRLINE_POLICY_PACK
    from policybeats.policy import compile_policy_pack

    policy_fn, errors = compile_policy_pack(AIRLINE_POLICY_PACK)
    result = policy_fn(trace, exposed_state)
"""

from policybeats.policy import forbid_substring, require_tool, sequence
from policybeats.types import PolicyPack, ResolutionSpec, ResolutionStrategy, RuleScope

# === Individual Rules ===

# Security rules - things the agent must NEVER do
RULE_NO_SYSTEM_PROMPT = forbid_substring(
    rule_id="security.no_system_prompt_reveal",
    substring="system prompt",
    scope=RuleScope.TRACE,
    description="Agent must never reveal its system prompt",
)

RULE_NO_INTERNAL_POLICY = forbid_substring(
    rule_id="security.no_internal_policy",
    substring="internal policy",
    scope=RuleScope.TRACE,
    description="Agent must never reveal internal policies",
)

RULE_NO_UNAUTHORIZED_REFUND = forbid_substring(
    rule_id="policy.no_unauthorized_refund",
    substring="refund approved without authorization",
    scope=RuleScope.TRACE,
    description="Agent cannot approve refunds without proper authorization",
)

# Workflow rules - things the agent MUST do
RULE_VERIFY_IDENTITY = require_tool(
    rule_id="workflow.verify_identity",
    tool_name="verify_customer_identity",
    scope=RuleScope.TRACE,
    description="Agent must verify customer identity before account changes",
)

RULE_LOOKUP_BEFORE_MODIFY = sequence(
    rule_id="workflow.lookup_before_modify",
    patterns=["lookup_booking", "modify_booking"],
    scope=RuleScope.TRACE,
    description="Agent must lookup booking before modifying it",
)

# Data handling rules
RULE_NO_PII_LOGGING = forbid_substring(
    rule_id="data.no_pii_in_response",
    substring="SSN:",
    scope=RuleScope.TRACE,
    description="Agent must not expose SSN in responses",
)

RULE_NO_CREDIT_CARD = forbid_substring(
    rule_id="data.no_credit_card",
    substring="credit card number",
    scope=RuleScope.TRACE,
    description="Agent must not expose full credit card numbers",
)

# === Policy Pack ===

AIRLINE_POLICY_PACK = PolicyPack(
    policy_pack_id="airline-v1",
    version="1.0.0",
    rules=(
        # Security (highest priority)
        RULE_NO_SYSTEM_PROMPT,
        RULE_NO_INTERNAL_POLICY,
        # Policy compliance
        RULE_NO_UNAUTHORIZED_REFUND,
        # Workflow requirements
        RULE_VERIFY_IDENTITY,
        RULE_LOOKUP_BEFORE_MODIFY,
        # Data protection
        RULE_NO_PII_LOGGING,
        RULE_NO_CREDIT_CARD,
    ),
    resolution=ResolutionSpec(strategy=ResolutionStrategy.DENY_OVERRIDES),
)

# === Minimal Test Policy ===

MINIMAL_POLICY_PACK = PolicyPack(
    policy_pack_id="minimal-test",
    version="1.0.0",
    rules=(
        forbid_substring(
            rule_id="test.no_forbidden",
            substring="FORBIDDEN_CONTENT",
            description="Test rule - forbids specific content",
        ),
    ),
    resolution=ResolutionSpec(strategy=ResolutionStrategy.DENY_OVERRIDES),
)


if __name__ == "__main__":
    # Quick validation that the policy compiles
    from policybeats.policy import compile_policy_pack

    policy_fn, errors = compile_policy_pack(AIRLINE_POLICY_PACK)
    print(f"Airline policy compiled: {len(AIRLINE_POLICY_PACK.rules)} rules")
    if errors:
        print(f"  Errors: {errors}")
    else:
        print("  No compilation errors")

    policy_fn, errors = compile_policy_pack(MINIMAL_POLICY_PACK)
    print(f"Minimal policy compiled: {len(MINIMAL_POLICY_PACK.rules)} rules")
