"""DB evaluator — replay trajectory and compare DB hashes."""

import logging
import re
from copy import deepcopy
from typing import Any

from pi_bench.environment import make_tool_call, get_db_hash

logger = logging.getLogger(__name__)

# Sentinel for distinguishing "path not found" from actual None values
_MISSING = object()

_BRACKET_RE = re.compile(r"^(\w+)\[(\w+)=([^\]]+)\]$")


def evaluate_db(task: dict, simulation: dict, domain: dict) -> float:
    """Replay trajectory against a fresh environment, compare DB hashes.

    Compares both the expected final state hash and the actual replayed hash.
    Returns 1.0 if hashes match, 0.0 otherwise.
    """
    get_env = domain.get("get_environment")
    if get_env is None:
        return 0.0

    # Pass task so get_environment can build a scenario-specific env
    try:
        replay_env = get_env(task)
    except TypeError:
        # Backward compat: older callers pass get_environment() with no args
        replay_env = get_env()
    initial_state = task.get("initial_state", {})

    # Apply initialization data if present
    init_data = initial_state.get("initialization_data")
    if init_data:
        from pi_bench.environment import set_state
        set_state(replay_env, deepcopy(init_data))

    # Apply initialization actions if present
    # F4: check for errors on init actions
    init_actions = initial_state.get("initialization_actions", [])
    for action in init_actions:
        result = make_tool_call(
            replay_env,
            tool_name=action["name"],
            call_id=action.get("id", "init"),
            arguments=action.get("arguments", {}),
            requestor=action.get("requestor", "assistant"),
        )
        if isinstance(result, dict) and result.get("error"):
            logger.warning(
                "Init action %s failed: %s", action["name"], result["error"]
            )
            return 0.0

    # Replay all tool calls from the trajectory
    for msg in simulation.get("messages", []):
        if msg.get("role") in ("assistant", "user") and msg.get("tool_calls"):
            requestor = "assistant" if msg["role"] == "assistant" else "user"
            for tc in msg["tool_calls"]:
                make_tool_call(
                    replay_env,
                    tool_name=tc["name"],
                    call_id=tc.get("id", "call"),
                    arguments=tc.get("arguments", {}),
                    requestor=requestor,
                )

    replay_hash = get_db_hash(replay_env)
    logger.debug("DB: replay hash=%s", replay_hash)

    # Compare against expected final state if provided
    expected_db = task.get("evaluation_criteria", {}).get("expected_db")
    if expected_db:
        try:
            expected_env = get_env(task)
        except TypeError:
            expected_env = get_env()
        from pi_bench.environment import set_state
        set_state(expected_env, deepcopy(expected_db))
        expected_hash = get_db_hash(expected_env)
        return 1.0 if replay_hash == expected_hash else 0.0

    # If no expected_db, just verify replay succeeded (hash is consistent)
    return 1.0


def evaluate_db_rich(task: dict, simulation: dict, domain: dict) -> list[dict]:
    """Run DB replay check and return an explainable result wrapper."""
    score = evaluate_db(task, simulation, domain)
    expected_db = task.get("evaluation_criteria", {}).get("expected_db")
    if score == 1.0 and expected_db:
        detail = "replayed trajectory matched expected final DB"
    elif score == 1.0:
        detail = "replayed trajectory without expected_db completed"
    elif expected_db:
        detail = "replayed trajectory did not match expected final DB"
    else:
        detail = "DB replay failed before expected_db comparison"
    return [{
        "outcome_id": "DB",
        "type": "db_replay",
        "passed": score == 1.0,
        "detail": detail,
    }]


def evaluate_db_checks(
    state_field_outcomes: list[dict],
    env: dict,
) -> list[dict]:
    """Check state_field outcomes against env["db"].

    Returns list of {outcome_id, type, passed, detail} dicts.
    """
    results = []
    for outcome in state_field_outcomes:
        passed, detail = _check_state_field(outcome, env)
        results.append({
            "outcome_id": outcome.get("outcome_id", "unknown"),
            "type": "state_field",
            "passed": passed,
            "detail": detail,
        })
    return results


def _check_state_field(outcome: dict, env: dict) -> tuple[bool, str]:
    """Navigate env["db"] with JSONPath-like field_path.

    Supports bracket filter: collection[key=value].field
    Example: activity.pending_requests[request_id=REQ_010_1].status
    """
    field_path = outcome.get("field_path", "")
    expected = outcome.get("equals")
    db = env.get("db", {})

    # B3: use sentinel to distinguish missing path from None value
    value = _navigate_db(db, field_path)
    if value is _MISSING:
        return False, f"state_field({field_path}): path not found in db"

    passed = value == expected
    return passed, f"state_field({field_path}): expected={expected}, actual={value}"


def _navigate_db(db: dict, path: str) -> Any:
    """Navigate a dotted path with optional bracket filters.

    Returns _MISSING sentinel if the path doesn't exist.
    """
    current: Any = db
    segments = path.split(".")

    for segment in segments:
        if current is None or current is _MISSING:
            return _MISSING

        m = _BRACKET_RE.match(segment)
        if m:
            collection_name, filter_key, filter_value = m.groups()
            if isinstance(current, dict):
                current = current.get(collection_name, _MISSING)
            else:
                return _MISSING
            if current is _MISSING:
                return _MISSING
            if isinstance(current, list):
                found = _MISSING
                for item in current:
                    if isinstance(item, dict) and str(item.get(filter_key)) == filter_value:
                        found = item
                        break
                current = found
            else:
                return _MISSING
        elif isinstance(current, dict):
            current = current.get(segment, _MISSING)
        else:
            return _MISSING

    return current
