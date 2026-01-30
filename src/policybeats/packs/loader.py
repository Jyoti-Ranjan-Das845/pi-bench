"""
Loader for PolicyBeats packs from data/ directory.

Reads JSON + Markdown files following tau2-bench conventions:
  data/<category>/rules.json   — machine-readable rule definitions
  data/<category>/tasks.json   — scenario/task definitions
  data/<category>/policy.md    — human-readable policy (not loaded into Python objects)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from policybeats.packs.schema import validate_rules_json, validate_tasks_json
from policybeats.types import (
    ObligationType,
    PolicyPack,
    ResolutionSpec,
    ResolutionStrategy,
    RuleScope,
    RuleSpec,
)
from policybeats.a2a.protocol import MultiTurnScenario, ScenarioTurn

_log = logging.getLogger(__name__)

CATEGORIES = [
    "compliance",
    "understanding",
    "robustness",
    "process",
    "restraint",
    "conflict_resolution",
    "detection",
    "explainability",
    "adaptation",
]

# Locate data/ directory: walk up from this file to find it.
# Supports: src/policybeats/packs/loader.py -> ../../.. -> policybeats/ -> data/
def _find_data_dir() -> Path:
    """Walk up from this file to find the data/ directory."""
    d = Path(__file__).resolve().parent
    for _ in range(6):  # max 6 levels up
        candidate = d / "data"
        if candidate.is_dir() and (candidate / "compliance").is_dir():
            return candidate
        d = d.parent
    # Fallback: relative to __file__ (original 4x parent)
    return Path(__file__).resolve().parent.parent.parent.parent / "data"

_DATA_DIR = _find_data_dir()


def _parse_resolution_strategy(s: str) -> ResolutionStrategy:
    return ResolutionStrategy.DENY_OVERRIDES


def _parse_rule(d: dict[str, Any]) -> RuleSpec:
    return RuleSpec(
        rule_id=d["rule_id"],
        kind=d["kind"],
        params=d.get("params", {}),
        scope=RuleScope(d.get("scope", "trace")),
        description=d.get("description"),
        obligation=ObligationType(d.get("obligation", "DO")),
        priority=d.get("priority", 0),
        exception_of=d.get("exception_of"),
        override_mode=d.get("override_mode", "deny"),
    )


def _parse_pack(d: dict[str, Any]) -> PolicyPack:
    res_str = d.get("resolution", "deny_overrides")
    if isinstance(res_str, dict):
        res_str = res_str.get("strategy", "deny_overrides")
    resolution = ResolutionSpec(strategy=_parse_resolution_strategy(res_str))
    rules = tuple(_parse_rule(r) for r in d.get("rules", []))
    return PolicyPack(
        policy_pack_id=d["policy_pack_id"],
        version=d["version"],
        rules=rules,
        resolution=resolution,
    )


def _parse_turn(d: dict[str, Any]) -> ScenarioTurn:
    return ScenarioTurn(
        turn_number=d["turn_number"],
        instruction=d["instruction"],
        expected_env_changes=tuple(d.get("expected_env_changes") or ()),
        rules_to_check=tuple(d.get("rules_to_check") or ()),
        required_tool_calls=tuple(d.get("required_tool_calls") or ()),
        forbidden_tool_calls=tuple(d.get("forbidden_tool_calls") or ()),
    )


def _parse_task(d: dict[str, Any], category: str) -> MultiTurnScenario:
    """Parse a tau2-style task object into MultiTurnScenario."""
    tools_raw = d.get("tools", [])
    tool_names = tuple(t["name"] for t in tools_raw if isinstance(t, dict))

    turns = tuple(_parse_turn(t) for t in d.get("turns", []))

    eval_criteria = d.get("evaluation_criteria", {})

    kwargs: dict[str, Any] = dict(
        scenario_id=d["id"],
        name=d["name"],
        description=d.get("description", ""),
        initial_environment=d.get("initial_state", {}),
        tools=tool_names,
        turns=turns,
        rules_to_check=tuple(eval_criteria.get("rules_to_check") or ()),
        category=category,
        severity=d.get("severity", "medium"),
        task_type=category,
        dynamic_user=eval_criteria.get("dynamic_user", False),
    )

    return MultiTurnScenario(**kwargs)


def load_pack(category: str) -> PolicyPack:
    """Load rules.json for a category and return PolicyPack."""
    rules_path = _DATA_DIR / category / "rules.json"
    with open(rules_path) as f:
        data = json.load(f)
    errors = validate_rules_json(data)
    if errors:
        _log.warning("Validation errors in %s/rules.json: %s", category, errors)
    return _parse_pack(data)


def load_scenarios(category: str) -> list[MultiTurnScenario]:
    """Load tasks.json for a category."""
    tasks_path = _DATA_DIR / category / "tasks.json"
    if not tasks_path.exists():
        return []
    with open(tasks_path) as f:
        tasks = json.load(f)
    errors = validate_tasks_json(tasks)
    if errors:
        _log.warning("Validation errors in %s/tasks.json: %s", category, errors)
    return [_parse_task(t, category) for t in tasks]


def load_scenario_packs(category: str) -> dict[str, PolicyPack]:
    """Load embedded scenario_pack definitions from tasks.json."""
    tasks_path = _DATA_DIR / category / "tasks.json"
    if not tasks_path.exists():
        return {}
    with open(tasks_path) as f:
        tasks = json.load(f)
    packs: dict[str, PolicyPack] = {}
    for t in tasks:
        if "scenario_pack" in t:
            packs[t["id"]] = _parse_pack(t["scenario_pack"])
    return packs


def load_policy_md(category: str) -> str:
    """Load the human-readable policy.md for a category."""
    policy_path = _DATA_DIR / category / "policy.md"
    if not policy_path.exists():
        return ""
    return policy_path.read_text()


def load_all() -> dict[str, tuple[PolicyPack, list[MultiTurnScenario]]]:
    """Load all 9 categories."""
    result = {}
    for cat in CATEGORIES:
        pack = load_pack(cat)
        scenarios = load_scenarios(cat)
        result[cat] = (pack, scenarios)
    return result
