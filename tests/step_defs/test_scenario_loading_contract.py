"""Scenario/domain loading contract tests."""

import copy
import json
from pathlib import Path

import pytest

from pi_bench.evaluator.generated_scenario_checks import (
    domain_tool_names_for_domain,
    validate_generated_scenario_tools,
)
from pi_bench.scenario_loader import load


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios" / "finra" / "scen_015_cross_account_pattern.json"


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2))


@pytest.fixture
def minimal_workspace(tmp_path: Path) -> tuple[Path, Path, dict]:
    workspace = tmp_path
    domain_dir = workspace / "domains" / "demo"
    scenario_dir = workspace / "scenarios" / "demo"
    domain_dir.mkdir(parents=True)
    scenario_dir.mkdir(parents=True)

    (domain_dir / "policy.md").write_text("Demo policy: use tools and record a decision.")
    _write_json(domain_dir / "db.json", {"base": {"keep": True}})
    _write_json(
        domain_dir / "tools.json",
        [
            {
                "name": "record_decision",
                "description": "Record final decision",
                "parameters": {
                    "decision": {
                        "type": "string",
                        "required": True,
                    }
                },
            },
            {
                "name": "blocked_tool",
                "description": "A real domain tool intentionally not exposed",
                "parameters": {},
            },
        ],
    )

    scenario = {
        "schema_version": "pibench_scenario_v1",
        "meta": {
            "scenario_id": "SCEN_DEMO",
            "domain": "demo",
            "created_at": "2026-04-13",
            "notes": "Demo scenario.",
        },
        "label": "DENY",
        "leaderboard": {"primary": "Policy Activation"},
        "policy_context": {
            "policy_text_ref": "domains/demo/policy.md",
            "policy_version": "DEMO_POLICY_V1",
            "policy_clauses": [],
        },
        "environment_setup": {
            "now": "2026-04-13T10:00:00+05:30",
            "initial_state_patch": {"base": {"scenario": True}},
        },
        "user_simulation": {
            "persona": "customer",
            "initial_user_message": "Please do the thing.",
            "pressure_script": [],
        },
        "evaluation_criteria": {
            "reward_basis": ["POLICY"],
            "policy_checks": [
                {
                    "outcome_id": "D1",
                    "type": "decision_equals",
                    "equals": "DENY",
                },
                {
                    "outcome_id": "T1",
                    "type": "tool_called",
                    "tool_name": "record_decision",
                },
                {
                    "outcome_id": "T2",
                    "type": "tool_not_called",
                    "tool_name": "blocked_tool",
                },
            ],
        },
        "available_tools": ["record_decision"],
    }
    scenario_path = scenario_dir / "scen_demo.json"
    _write_json(scenario_path, scenario)
    return workspace, scenario_path, scenario


def test_load_is_strict_about_missing_domain(minimal_workspace):
    workspace, scenario_path, scenario = minimal_workspace
    scenario["meta"]["domain"] = "missing_domain"
    _write_json(scenario_path, scenario)

    with pytest.raises(FileNotFoundError, match="Domain directory not found"):
        load(scenario_path, workspace_root=workspace)


def test_load_is_strict_about_missing_policy(minimal_workspace):
    workspace, scenario_path, scenario = minimal_workspace
    scenario["policy_context"]["policy_text_ref"] = "domains/demo/missing.md"
    _write_json(scenario_path, scenario)

    with pytest.raises(FileNotFoundError, match="Policy file not found"):
        load(scenario_path, workspace_root=workspace)


def test_load_is_strict_about_unknown_available_tools(minimal_workspace):
    workspace, scenario_path, scenario = minimal_workspace
    scenario["available_tools"] = ["record_decision", "typo_tool"]
    _write_json(scenario_path, scenario)

    with pytest.raises(ValueError, match="unknown available_tools"):
        load(scenario_path, workspace_root=workspace)


def test_loader_keeps_db_merge_and_metadata(minimal_workspace):
    workspace, scenario_path, _scenario = minimal_workspace
    loaded = load(scenario_path, workspace_root=workspace)

    assert loaded["env"]["db"]["base"] == {"keep": True, "scenario": True}
    assert {tool["name"] for tool in loaded["env"]["tool_schemas"]} == {
        "record_decision"
    }
    assert loaded["task"]["domain"] == "demo"
    assert loaded["task"]["scenario_id"] == "SCEN_DEMO"
    assert loaded["task"]["leaderboard_primary"] == "Policy Activation"
    assert loaded["task"]["policy_version"] == "DEMO_POLICY_V1"


def test_tool_not_called_may_reference_real_domain_tool_outside_available_tools():
    scenario = json.loads(SCENARIO.read_text())
    full_domain_tools = domain_tool_names_for_domain(
        scenario["meta"]["domain"],
        ROOT,
    )

    assert "process_wire_transfer" not in scenario["available_tools"]
    assert "process_wire_transfer" in full_domain_tools
    assert validate_generated_scenario_tools(scenario, full_domain_tools) == []


def test_required_tool_must_be_exposed_when_available_tools_is_present():
    scenario = json.loads(SCENARIO.read_text())
    scenario = copy.deepcopy(scenario)
    scenario["evaluation_criteria"]["policy_checks"].append(
        {
            "outcome_id": "BAD_REQUIRED_TOOL",
            "type": "tool_called",
            "tool_name": "process_wire_transfer",
        }
    )
    full_domain_tools = domain_tool_names_for_domain(
        scenario["meta"]["domain"],
        ROOT,
    )

    errors = validate_generated_scenario_tools(scenario, full_domain_tools)

    assert any("Required tool 'process_wire_transfer'" in error for error in errors)
