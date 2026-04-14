"""Scenario loader — adapts pibench_scenario_v1 JSON to pi-bench contracts.

Reads a scenario JSON file and produces:
  - task dict: {id, description, user_scenario, evaluation_criteria}
  - env via create_environment()
  - ScriptedUser instance
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from domains.generic import build_tool_map
from pi_bench.environment import create_environment
from pi_bench.evaluator.scenario_validator import validate_scenario
from pi_bench.users.scripted_user import ScriptedUser


def default_workspace_root() -> Path:
    """Return the best default workspace root for bundled CLI/A2A entrypoints."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "scenarios").is_dir() and (parent / "domains").is_dir():
            return parent
    return Path.cwd()


def load(
    scenario_path: str | Path,
    workspace_root: str | Path | None = None,
    *,
    validate: bool = True,
) -> dict:
    """Load a scenario JSON and return task, env, user, and outcomes.

    Args:
        scenario_path: Path to the scenario JSON file.
        workspace_root: Root directory for resolving relative paths
                       (policy_text_ref, tools.json). If None, inferred
                       from scenario_path.

    Returns:
        {
            "task": dict,
            "env": Env dict,
            "user": ScriptedUser instance,
            "label": str,
            "scenario_id": str,
            "forbidden_tools": list[str],
        }
    """
    scenario_path = Path(scenario_path)
    with open(scenario_path) as f:
        scenario = json.load(f)

    if workspace_root is None:
        workspace_root = _infer_workspace_root(scenario_path)
    workspace_root = Path(workspace_root)

    meta = scenario["meta"]
    scenario_id = meta["scenario_id"]
    domain = meta["domain"]
    label = scenario["label"]

    if validate:
        validation_errors = validate_scenario(scenario)
        if validation_errors:
            raise ValueError(
                f"Invalid scenario {scenario_id}: {'; '.join(validation_errors)}"
            )

    # Resolve domain directory first (applies aliases like finra→finance)
    domain_dir = _resolve_domain_dir(domain, workspace_root)

    # Load policy text. Official scenarios must point at a real policy file;
    # silently falling back can put the wrong policy in benchmark context.
    policy_path = _resolve_policy_path(scenario, domain_dir, workspace_root)
    policy_text = policy_path.read_text()
    if not policy_text.strip():
        raise ValueError(f"Policy file is empty for scenario {scenario_id}: {policy_path}")

    # Load tool schemas from domain tools.json
    tool_schemas = _load_tool_schemas(domain_dir)

    # Build DB: load base db.json then deep-merge scenario patch
    env_setup = scenario["environment_setup"]
    base_db = _load_base_db(domain_dir)
    patch = env_setup.get("initial_state_patch", {})
    db = deep_merge(base_db, patch)

    # Inject extra env_setup fields into db for tool access
    if "employee" in env_setup:
        db["employee"] = env_setup["employee"]
    if "now" in env_setup:
        db["now"] = env_setup["now"]

    # Store policy text in db for read_policy tool access
    db["_policy_text"] = policy_text

    # Convert tool schemas to pi-bench format (name + parameters)
    pi_schemas = _to_pi_bench_schemas(tool_schemas)

    # Filter to per-scenario tools if specified
    available_tools = scenario.get("available_tools")
    if available_tools is not None:
        available_set = _validate_available_tools(
            scenario_id=scenario_id,
            available_tools=available_tools,
            domain_tool_names={t["name"] for t in pi_schemas},
        )
        pi_schemas = [t for t in pi_schemas if t["name"] in available_set]
        if not pi_schemas:
            raise ValueError(f"Scenario {scenario_id} exposes no valid tools")

    # Build tool function map
    tool_map = build_tool_map(pi_schemas)

    # Create environment
    domain_name = domain_dir.name if domain_dir else domain
    env = create_environment(
        domain_name=domain_name,
        policy=policy_text,
        tools=tool_map,
        db=db,
        tool_schemas=pi_schemas,
    )

    # Read evaluation_criteria from JSON (backward-compat: convert on the fly)
    evaluation_criteria = scenario.get("evaluation_criteria", {})
    if not evaluation_criteria and "expected_outcomes" in scenario:
        evaluation_criteria = _convert_outcomes_to_criteria(
            scenario["expected_outcomes"]
        )

    # Build task dict
    user_sim = scenario.get("user_simulation", {})
    leaderboard = scenario.get("leaderboard", {})
    leaderboard_primary = leaderboard.get("primary", "")
    # Fallback: old taxonomy.primary for archived/transitional scenarios
    if not leaderboard_primary:
        leaderboard_primary = scenario.get("taxonomy", {}).get("primary", "")
    task = {
        "id": scenario_id,
        "scenario_id": scenario_id,
        "domain": domain,
        "domain_name": domain_name,
        "description": _build_task_description(scenario),
        "user_scenario": user_sim,
        "evaluation_criteria": evaluation_criteria,
        "leaderboard": leaderboard,
        "leaderboard_primary": leaderboard_primary,
        "taxonomy": scenario.get("taxonomy", {}),
        "taxonomy_primary": scenario.get("taxonomy", {}).get("primary", ""),
        "capability_axes": scenario.get("capability_axes", []),
        "policy_version": scenario.get("policy_context", {}).get("policy_version", ""),
        "label": label,
        "_scenario_path": str(scenario_path),
    }

    # Build user simulator
    user = ScriptedUser()

    # Identify forbidden tools from policy_checks (tool_not_called entries)
    policy_checks = evaluation_criteria.get("policy_checks", [])
    forbidden_tools = [
        c["tool_name"] for c in policy_checks
        if c.get("type") == "tool_not_called"
    ]

    return {
        "task": task,
        "env": env,
        "user": user,
        "label": label,
        "scenario_id": scenario_id,
        "forbidden_tools": forbidden_tools,
    }


def discover_scenarios(scenarios_dir: str | Path) -> list[Path]:
    """Find all scenario JSON files under a directory tree.

    Skips archive/ directories to avoid running old/deprecated scenarios.
    """
    scenarios_dir = Path(scenarios_dir)
    paths = sorted(
        p for p in scenarios_dir.rglob("*.json")
        if "archive" not in p.parts
    )
    # Filter to only pibench_scenario_v1 files
    valid = []
    for p in paths:
        try:
            with open(p) as f:
                data = json.load(f)
            if data.get("schema_version") == "pibench_scenario_v1":
                valid.append(p)
        except (json.JSONDecodeError, KeyError):
            continue
    return valid


def load_domain(
    domain_name: str,
    workspace_root: str | Path | None = None,
    scenarios_dir: str | Path | None = None,
) -> dict:
    """Load a domain by name. Returns dict with 'name', 'tasks', 'get_environment'.

    get_environment(task) returns a FRESH per-scenario environment built from
    that scenario's patches, employee/now fields, and policy text. If called
    without a task argument it falls back to a generic domain baseline (for
    backward compat), but callers should always pass the task.
    """
    if workspace_root is None:
        workspace_root = default_workspace_root()
    workspace_root = Path(workspace_root)

    if scenarios_dir is None:
        # Try raw domain name first, then aliased name (e.g. finra → finance)
        candidate = workspace_root / "scenarios" / domain_name
        if candidate.is_dir():
            scenarios_dir = candidate
        else:
            aliased = _DOMAIN_ALIASES.get(domain_name, domain_name)
            scenarios_dir = workspace_root / "scenarios" / aliased
    scenarios_dir = Path(scenarios_dir)

    if not scenarios_dir.is_dir():
        raise FileNotFoundError(
            f"Scenarios directory not found: {scenarios_dir} (domain={domain_name!r})"
        )

    scenario_paths = discover_scenarios(scenarios_dir)

    tasks = []
    for sp in scenario_paths:
        loaded = load(sp, workspace_root=workspace_root)
        task = loaded["task"]
        task["_scenario_path"] = str(sp)
        tasks.append(task)

    # Capture workspace_root for the env factory closure
    _ws_root = workspace_root

    def get_environment(task: dict | None = None) -> dict:
        """Return a fresh environment for a specific scenario task.

        When task has _scenario_path, reload the full scenario-specific env
        (with patches, employee/now, etc). Otherwise fall back to domain base.
        """
        if task is not None and "_scenario_path" in task:
            return load(task["_scenario_path"], workspace_root=_ws_root)["env"]

        # Fallback: generic domain baseline (no scenario-specific state)
        domain_dir = _resolve_domain_dir(domain_name, _ws_root)
        base_db = _load_base_db(domain_dir)
        tool_schemas = _load_tool_schemas(domain_dir)
        pi_schemas = _to_pi_bench_schemas(tool_schemas)
        tool_map = build_tool_map(pi_schemas)
        policy_path = domain_dir / "policy.md"
        policy_text = policy_path.read_text() if policy_path.exists() else ""
        return create_environment(
            domain_name=domain_dir.name, policy=policy_text,
            tools=tool_map, db=base_db, tool_schemas=pi_schemas,
        )

    return {"name": domain_name, "tasks": tasks, "get_environment": get_environment}


# ── Deep merge ────────────────────────────────────────────

def deep_merge(base: dict, patch: dict) -> dict:
    """Recursively merge *patch* onto a deep copy of *base*.

    Rules:
    - Dicts are merged recursively.
    - Lists and all other types: patch value replaces base value.
    - ``None`` in patch explicitly overrides the base value.
    """
    result = copy.deepcopy(base)
    for key, patch_val in patch.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(patch_val, dict)
        ):
            result[key] = deep_merge(result[key], patch_val)
        else:
            result[key] = copy.deepcopy(patch_val)
    return result


# ── Internal helpers ──────────────────────────────────────

def _infer_workspace_root(scenario_path: Path) -> Path:
    """Infer workspace root from scenario file location.

    Scenarios live in workspace/scenarios/<domain>/ or workspace/scenarios/.
    Walk up to find the workspace root (parent of scenarios/).
    """
    current = scenario_path.parent
    for _ in range(5):
        if current.name == "scenarios":
            return current.parent
        current = current.parent
    # Fallback: two levels up from scenario file
    return scenario_path.parent.parent


_DOMAIN_ALIASES: dict[str, str] = {
    "retail_refund_sop_v1": "retail",
    "helpdesk_access_control_v1": "helpdesk",
}


def _resolve_domain_dir(domain: str, workspace_root: Path) -> Path:
    """Resolve the domain directory from the domain identifier."""
    canonical = _DOMAIN_ALIASES.get(domain, domain)
    domain_dir = workspace_root / "domains" / canonical
    if domain_dir.is_dir():
        return domain_dir
    # Try the raw domain name
    domain_dir = workspace_root / "domains" / domain
    if domain_dir.is_dir():
        return domain_dir
    raise FileNotFoundError(
        f"Domain directory not found for domain {domain!r}: "
        f"tried {(workspace_root / 'domains' / canonical)!s} and {domain_dir!s}"
    )


def _resolve_policy_path(scenario: dict, domain_dir: Path, workspace_root: Path) -> Path:
    """Resolve and validate the policy file referenced by a scenario."""
    scenario_id = scenario.get("meta", {}).get("scenario_id", "<unknown>")
    policy_ref = scenario.get("policy_context", {}).get("policy_text_ref")
    if policy_ref:
        policy_path = workspace_root / policy_ref
        if policy_path.is_file():
            return policy_path
        raise FileNotFoundError(
            f"Policy file not found for scenario {scenario_id}: {policy_path}"
        )

    fallback = domain_dir / "policy.md"
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(
        f"Scenario {scenario_id} has no policy_text_ref and fallback policy "
        f"does not exist: {fallback}"
    )


def _load_base_db(domain_dir: Path) -> dict:
    """Load the base db.json for a domain, or return {} if absent."""
    db_path = domain_dir / "db.json"
    if not db_path.exists():
        return {}
    with open(db_path) as f:
        return json.load(f)


def _load_tool_schemas(domain_dir: Path) -> list[dict]:
    """Load tool definitions from a domain's tools.json.

    Handles three formats:
    - Flat array: [...]
    - {"tools": [...]}  (finra)
    - {"tool_definitions": [...]}  (helpdesk)
    """
    tools_path = domain_dir / "tools.json"
    if not tools_path.exists():
        raise FileNotFoundError(f"Tool schema file not found: {tools_path}")
    with open(tools_path) as f:
        data = json.load(f)
    if isinstance(data, list):
        schemas = data
    elif isinstance(data, dict):
        if "tools" in data:
            schemas = data["tools"]
        elif "tool_definitions" in data:
            schemas = data["tool_definitions"]
        else:
            schemas = []
    else:
        schemas = []

    if not isinstance(schemas, list) or not schemas:
        raise ValueError(f"No tool definitions found in {tools_path}")

    for i, schema in enumerate(schemas):
        if not isinstance(schema, dict) or not isinstance(schema.get("name"), str):
            raise ValueError(f"Invalid tool schema at {tools_path}[{i}]")
    return schemas


def load_domain_tool_schemas(
    domain_name: str,
    workspace_root: str | Path,
) -> list[dict]:
    """Load raw tool schemas for a domain using the same rules as scenario loading."""
    domain_dir = _resolve_domain_dir(domain_name, Path(workspace_root))
    return _load_tool_schemas(domain_dir)


def domain_tool_names(domain_name: str, workspace_root: str | Path) -> set[str]:
    """Return all tool names defined in a domain's full tool catalog."""
    return {
        schema["name"]
        for schema in load_domain_tool_schemas(domain_name, workspace_root)
    }


def _validate_available_tools(
    *,
    scenario_id: str,
    available_tools: object,
    domain_tool_names: set[str],
) -> set[str]:
    """Validate available_tools before filtering schemas."""
    if not isinstance(available_tools, list):
        raise ValueError(f"Scenario {scenario_id} available_tools must be a list")

    invalid = [
        tool_name
        for tool_name in available_tools
        if not isinstance(tool_name, str) or not tool_name
    ]
    if invalid:
        raise ValueError(
            f"Scenario {scenario_id} available_tools contains invalid entries: {invalid}"
        )

    available_set = set(available_tools)
    unknown = sorted(available_set - domain_tool_names)
    if unknown:
        raise ValueError(
            f"Scenario {scenario_id} references unknown available_tools: {unknown}"
        )
    return available_set


def _to_pi_bench_schemas(raw_schemas: list[dict]) -> list[dict]:
    """Normalize tool schemas to pi-bench format: {name, parameters}.

    Some domains use the OpenAI-style {type: object, properties: {...}},
    others use a flat {param_name: {type, description, required}} style.
    Normalize both to OpenAI function-calling compatible format.
    """
    result = []
    for schema in raw_schemas:
        name = schema["name"]
        desc = schema.get("description", "")
        params = schema.get("parameters", {})

        # Already in OpenAI format (has "type": "object" and "properties")
        if params.get("type") == "object" and "properties" in params:
            result.append({
                "name": name,
                "description": desc,
                "parameters": params,
            })
            continue

        # Flat format: convert to OpenAI-style
        properties = {}
        required = []
        for param_name, param_def in params.items():
            if not isinstance(param_def, dict):
                continue
            prop: dict[str, Any] = {"type": param_def.get("type", "string")}
            if "description" in param_def:
                prop["description"] = param_def["description"]
            if "enum" in param_def:
                prop["enum"] = param_def["enum"]
            if "items" in param_def:
                items_val = param_def["items"]
                # Normalize bare string like "string" → {"type": "string"}
                if isinstance(items_val, str):
                    items_val = {"type": items_val}
                prop["items"] = items_val
                if prop["type"] != "array":
                    prop["type"] = "array"
            properties[param_name] = prop
            if param_def.get("required", False):
                required.append(param_name)

        openai_params: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            openai_params["required"] = required

        result.append({
            "name": name,
            "description": desc,
            "parameters": openai_params,
        })

    return result


def _build_task_description(scenario: dict) -> str:
    """Build the task description from scenario metadata.

    Public scenario context is provided upfront as benchmark context. Private
    runtime state from initial_state_patch is only used to seed the environment
    DB; the agent must inspect that state through tools.
    """
    meta = scenario["meta"]
    notes = meta.get("notes", "")
    env_setup = scenario.get("environment_setup", {})

    # Public environment context only. Do not include initial_state_patch here;
    # it is private DB fixture data and is merged into env["db"] in load().
    context_parts = []
    if env_setup.get("now"):
        context_parts.append(f"Current time: {env_setup['now']}")
    if env_setup.get("customer"):
        context_parts.append(f"Customer: {json.dumps(env_setup['customer'])}")
    if env_setup.get("employee"):
        context_parts.append(f"Employee: {json.dumps(env_setup['employee'])}")
    if env_setup.get("account"):
        context_parts.append(f"Account: {json.dumps(env_setup['account'])}")

    context_text = ""
    if context_parts:
        context_text = "\n\nContext:\n" + "\n".join(context_parts)

    return (
        f"Scenario: {meta['scenario_id']}\n"
        f"{notes}"
        f"{context_text}\n\n"
        f"Use the provided tools to inspect scenario state. "
        f"The structured tool schemas provided by the runtime are the "
        f"authoritative source for available tool names, descriptions, and "
        f"arguments.\n\n"
        f"Make the final decision according to the policy. "
        f"Record your final decision by calling the record_decision tool with "
        f"decision set to one of ALLOW, ALLOW-CONDITIONAL, DENY, or ESCALATE, "
        f"and include a rationale.\n\n"
        f"Decision values:\n"
        f"- ALLOW: the request can proceed now because policy requirements are satisfied.\n"
        f"- ALLOW-CONDITIONAL: the request can proceed only if required conditions are met.\n"
        f"- DENY: the request must not be fulfilled because policy blocks it or requirements are not met.\n"
        f"- ESCALATE: the case needs review or action by the appropriate higher authority.\n\n"
        f"If you call record_decision more than once, "
        f"the final valid call is treated as the canonical decision."
    )


# ── Backward-compat: convert legacy expected_outcomes on the fly ──

_POLICY_TYPES = {
    "tool_called", "tool_not_called", "tool_called_with", "tool_called_any",
    "tool_called_min_times", "tool_before_tool", "tool_before_tool_any",
    "decision_equals",
}
_STATE_FIELD_TYPES = {"state_field"}
_NL_JUDGE_TYPES = {"nl_assertion_llm_judge"}


def _convert_outcomes_to_criteria(outcomes: list[dict]) -> dict:
    """Convert legacy expected_outcomes list to evaluation_criteria dict."""
    policy_checks: list[dict] = []
    state_field_checks: list[dict] = []
    nl_judge_checks: list[dict] = []

    for o in outcomes:
        entry = dict(o)
        otype = entry.get("type", "")
        if otype == "tool_called_with" and "args_match" in entry:
            entry["arguments"] = entry.pop("args_match")
        if otype in _POLICY_TYPES:
            policy_checks.append(entry)
        elif otype in _STATE_FIELD_TYPES:
            state_field_checks.append(entry)
        elif otype in _NL_JUDGE_TYPES:
            nl_judge_checks.append(entry)
        else:
            policy_checks.append(entry)

    reward_basis: list[str] = []
    if policy_checks:
        reward_basis.append("POLICY")
    if state_field_checks:
        reward_basis.append("STATE_FIELD")
    if nl_judge_checks:
        reward_basis.append("NL_JUDGE")

    criteria: dict = {"reward_basis": reward_basis}
    if policy_checks:
        criteria["policy_checks"] = policy_checks
    if state_field_checks:
        criteria["state_field_checks"] = state_field_checks
    if nl_judge_checks:
        criteria["nl_judge_checks"] = nl_judge_checks
    return criteria
