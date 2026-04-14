"""Helpers for validating generated scenario output.

These checks complement :mod:`pi_bench.evaluator.scenario_validator` by
verifying that a scenario is structurally complete and only references tools
that exist in its domain's tool catalog.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pi_bench.evaluator.scenario_validator import validate_scenario
from pi_bench.scenario_loader import domain_tool_names, load


def validate_generated_scenario_structure(scenario: dict[str, Any]) -> list[str]:
    """Validate the top-level structure expected from generated scenarios."""
    errors: list[str] = []

    if not isinstance(scenario, dict):
        return ["Scenario payload must be a JSON object"]

    if scenario.get("schema_version") != "pibench_scenario_v1":
        errors.append("Generated scenario must use schema_version='pibench_scenario_v1'")

    meta = scenario.get("meta")
    if not isinstance(meta, dict):
        errors.append("Missing meta object")
    else:
        if not meta.get("scenario_id"):
            errors.append("Missing meta.scenario_id")
        if not meta.get("domain"):
            errors.append("Missing meta.domain")
        if not meta.get("created_at"):
            errors.append("Missing meta.created_at")

    leaderboard = scenario.get("leaderboard")
    if not isinstance(leaderboard, dict):
        errors.append("Missing leaderboard object")
    else:
        if not leaderboard.get("primary"):
            errors.append("Missing leaderboard.primary")
        if "subskills" in leaderboard and not isinstance(leaderboard["subskills"], list):
            errors.append("leaderboard.subskills must be a list")
        if "stressors" in leaderboard and not isinstance(leaderboard["stressors"], list):
            errors.append("leaderboard.stressors must be a list")

    if not isinstance(scenario.get("decision_contract"), dict):
        errors.append("Missing decision_contract object")
    if not isinstance(scenario.get("policy_context"), dict):
        errors.append("Missing policy_context object")
    if not isinstance(scenario.get("environment_setup"), dict):
        errors.append("Missing environment_setup object")
    if not isinstance(scenario.get("evaluation_criteria"), dict):
        errors.append("Missing evaluation_criteria object")

    return errors


def domain_tool_names_for_domain(domain_name: str, workspace_root: str | Path) -> set[str]:
    """Return the tool names defined for a domain."""
    return domain_tool_names(domain_name, workspace_root)


def collect_tool_references(scenario: dict[str, Any]) -> set[str]:
    """Collect tool names referenced anywhere in a scenario payload."""
    refs: set[str] = set()

    def add_ref(value: Any) -> None:
        if isinstance(value, str) and value:
            refs.add(value)

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"tool_name", "first_tool", "second_tool", "preferred_tool"}:
                    add_ref(item)
                elif key in {"tool_names", "first_tools"} and isinstance(item, list):
                    for name in item:
                        add_ref(name)
                elif key == "nodes" and isinstance(item, list):
                    for node in item:
                        if isinstance(node, list) and node:
                            add_ref(node[0])
                        else:
                            walk(node)
                else:
                    walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(scenario)
    return refs


def collect_required_tool_references(scenario: dict[str, Any]) -> set[str]:
    """Collect tools the evaluator expects the agent to call."""
    refs: set[str] = set()
    criteria = scenario.get("evaluation_criteria", {})

    for check in criteria.get("policy_checks", []):
        check_type = check.get("type")
        if check_type in {"tool_called", "tool_called_with", "tool_called_min_times"}:
            tool_name = check.get("tool_name")
            if isinstance(tool_name, str) and tool_name:
                refs.add(tool_name)
        elif check_type == "tool_called_any":
            for tool_name in check.get("tool_names", []) or []:
                if isinstance(tool_name, str) and tool_name:
                    refs.add(tool_name)
        elif check_type == "tool_before_tool":
            for key in ("first_tool", "second_tool"):
                tool_name = check.get(key)
                if isinstance(tool_name, str) and tool_name:
                    refs.add(tool_name)
        elif check_type == "tool_before_tool_any":
            for tool_name in check.get("first_tools", []) or []:
                if isinstance(tool_name, str) and tool_name:
                    refs.add(tool_name)
            second_tool = check.get("second_tool")
            if isinstance(second_tool, str) and second_tool:
                refs.add(second_tool)

    return refs


def validate_generated_scenario_tools(
    scenario: dict[str, Any],
    valid_tools: set[str],
) -> list[str]:
    """Ensure scenario tool references are consistent with the domain catalog.

    Tool references are validated against the full domain catalog. This is
    intentionally different from per-scenario available_tools: a scenario may
    include a tool_not_called check for a real domain tool that is not exposed
    to the agent in that scenario.
    """
    errors: list[str] = []
    scenario_id = scenario.get("meta", {}).get("scenario_id", "<unknown>")

    for tool_name in sorted(collect_tool_references(scenario)):
        if tool_name not in valid_tools:
            errors.append(
                f"Unknown tool reference '{tool_name}' for scenario {scenario_id}"
            )

    available_tools = scenario.get("available_tools")
    if available_tools is not None:
        if not isinstance(available_tools, list):
            errors.append(f"available_tools must be a list for scenario {scenario_id}")
            return errors

        available_set = {
            tool_name
            for tool_name in available_tools
            if isinstance(tool_name, str) and tool_name
        }
        if len(available_set) != len(available_tools):
            errors.append(
                f"available_tools contains invalid entries for scenario {scenario_id}"
            )

        for tool_name in sorted(available_set - valid_tools):
            errors.append(
                f"Unknown available_tools entry '{tool_name}' for scenario {scenario_id}"
            )

        for tool_name in sorted(collect_required_tool_references(scenario)):
            if tool_name in valid_tools and tool_name not in available_set:
                errors.append(
                    f"Required tool '{tool_name}' is not exposed in available_tools "
                    f"for scenario {scenario_id}"
                )
    return errors


def validate_generated_scenario_file(
    path: str | Path,
    workspace_root: str | Path,
) -> list[str]:
    """Validate a generated scenario file end-to-end."""
    path = Path(path)
    workspace_root = Path(workspace_root)

    try:
        scenario = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return [f"Cannot read scenario file: {exc}"]

    errors = []
    errors.extend(validate_generated_scenario_structure(scenario))
    errors.extend(validate_scenario(scenario))

    try:
        loaded = load(path, workspace_root=workspace_root)
    except Exception as exc:  # pragma: no cover - defensive surface for CLI use
        errors.append(f"Failed to load scenario environment: {exc}")
        return errors

    domain_name = scenario.get("meta", {}).get("domain", "")
    valid_tools = domain_tool_names_for_domain(domain_name, workspace_root)
    errors.extend(validate_generated_scenario_tools(scenario, valid_tools))
    return errors
