"""
Validation for policy pack JSON files (tasks.json, rules.json).

Returns lists of human-readable error strings. Empty list = valid.
"""

from __future__ import annotations

# Static set — must match policybeats.policy._compilers.RULE_COMPILERS keys.
# Kept static to avoid coupling validation to internal compiler module.
KNOWN_RULE_KINDS: frozenset[str] = frozenset({
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
})

KNOWN_SCOPES: frozenset[str] = frozenset({"trace", "exposed_state", "both"})

KNOWN_OBLIGATIONS: frozenset[str] = frozenset({"DO", "DONT", "ORDER", "ACHIEVE"})


def validate_rules_json(data: dict) -> list[str]:
    """Validate a rules.json structure. Returns list of error messages."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["rules.json must be a JSON object"]

    for field in ("policy_pack_id", "version"):
        if field not in data:
            errors.append(f"Missing required field: {field}")

    rules = data.get("rules", [])
    if not isinstance(rules, list):
        errors.append("'rules' must be an array")
        return errors

    seen_ids: set[str] = set()
    for i, rule in enumerate(rules):
        prefix = f"rules[{i}]"

        if not isinstance(rule, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        # Required fields
        for field in ("rule_id", "kind"):
            if field not in rule:
                errors.append(f"{prefix}: missing required field '{field}'")

        rule_id = rule.get("rule_id", "")
        if rule_id in seen_ids:
            errors.append(f"{prefix}: duplicate rule_id '{rule_id}'")
        seen_ids.add(rule_id)

        kind = rule.get("kind", "")
        if kind and kind not in KNOWN_RULE_KINDS:
            errors.append(f"{prefix}: unknown rule kind '{kind}' (known: {sorted(KNOWN_RULE_KINDS)})")

        scope = rule.get("scope", "trace")
        if scope not in KNOWN_SCOPES:
            errors.append(f"{prefix}: invalid scope '{scope}' (known: {sorted(KNOWN_SCOPES)})")

        obligation = rule.get("obligation", "DO")
        if obligation not in KNOWN_OBLIGATIONS:
            errors.append(f"{prefix}: invalid obligation '{obligation}' (known: {sorted(KNOWN_OBLIGATIONS)})")

        if "params" in rule and not isinstance(rule["params"], dict):
            errors.append(f"{prefix}: 'params' must be an object")

    return errors


def validate_tasks_json(data: list) -> list[str]:
    """Validate a tasks.json structure. Returns list of error messages."""
    errors: list[str] = []

    if not isinstance(data, list):
        return ["tasks.json must be a JSON array"]

    seen_ids: set[str] = set()
    for i, task in enumerate(data):
        prefix = f"tasks[{i}]"

        if not isinstance(task, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        # Required fields
        for field in ("id", "name"):
            if field not in task:
                errors.append(f"{prefix}: missing required field '{field}'")

        task_id = task.get("id", "")
        if task_id in seen_ids:
            errors.append(f"{prefix}: duplicate task id '{task_id}'")
        seen_ids.add(task_id)

        # Validate turns if present
        turns = task.get("turns", [])
        if not isinstance(turns, list):
            errors.append(f"{prefix}: 'turns' must be an array")
        else:
            for j, turn in enumerate(turns):
                turn_prefix = f"{prefix}.turns[{j}]"
                if not isinstance(turn, dict):
                    errors.append(f"{turn_prefix}: must be an object")
                    continue
                if "turn_number" not in turn:
                    errors.append(f"{turn_prefix}: missing 'turn_number'")
                if "instruction" not in turn:
                    errors.append(f"{turn_prefix}: missing 'instruction'")

        # Validate tools if present
        tools = task.get("tools", [])
        if not isinstance(tools, list):
            errors.append(f"{prefix}: 'tools' must be an array")
        else:
            for j, tool in enumerate(tools):
                tool_prefix = f"{prefix}.tools[{j}]"
                if not isinstance(tool, dict):
                    errors.append(f"{tool_prefix}: must be an object")
                    continue
                if "name" not in tool:
                    errors.append(f"{tool_prefix}: missing 'name'")

    return errors
