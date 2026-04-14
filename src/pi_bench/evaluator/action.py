"""ACTION evaluator — check expected tool calls appear in trajectory.

Matches tau2-bench behavior: partial argument matching via compare_args,
all-or-nothing scoring. Requestor check is optional (tau2 doesn't check it).
"""

import logging

logger = logging.getLogger(__name__)


def evaluate_actions(expected_actions: list[dict], trajectory: list[dict]) -> float:
    """Check that all expected tool calls appear in the trajectory.

    Matches by name + optional requestor + compared arguments.
    Returns 1.0 if all found, 0.0 if any missing.
    """
    results = evaluate_actions_rich(expected_actions, trajectory)
    return 1.0 if all(r["passed"] for r in results) else 0.0


def evaluate_actions_rich(expected_actions: list[dict], trajectory: list[dict]) -> list[dict]:
    """Return one explainable result per expected action."""
    if not expected_actions:
        return []

    actual_calls = _extract_tool_calls(trajectory)
    results = []

    for idx, expected in enumerate(expected_actions):
        matched = next(
            (actual for actual in actual_calls if _action_matches(expected, actual)),
            None,
        )
        passed = matched is not None
        if not passed:
            logger.info(
                "ACTION: expected action not found: %s(%s)",
                expected.get("name"), expected.get("arguments", {}),
            )
        results.append({
            "outcome_id": expected.get("outcome_id", expected.get("action_id", f"ACTION_{idx}")),
            "type": "tool_called",
            "passed": passed,
            "detail": _action_detail(expected, matched),
        })

    logger.debug("ACTION: %d/%d expected actions found", sum(r["passed"] for r in results), len(results))
    return results


def _extract_tool_calls(trajectory: list[dict]) -> list[dict]:
    """Extract all tool calls from a trajectory."""
    calls = []
    for msg in trajectory:
        if msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                tc_with_role = dict(tc)
                tc_with_role["requestor"] = (
                    "assistant" if msg.get("role") == "assistant" else "user"
                )
                calls.append(tc_with_role)
    return calls


def _action_matches(expected: dict, actual: dict) -> bool:
    """Check if an actual tool call matches an expected action.

    Follows tau2-bench's compare_with_tool_call pattern:
    - Name must match
    - Requestor checked only if specified in expected (pi-bench extension)
    - If compare_args is None, compare all actual args against expected
    - If compare_args is empty list, match on name only
    - If compare_args lists keys, compare only those keys
    """
    if expected.get("name") != actual.get("name"):
        return False

    # Requestor is a pi-bench extension; skip if not specified
    if expected.get("requestor") is not None and expected.get("requestor") != actual.get("requestor"):
        return False

    compare_keys = expected.get("compare_args")
    expected_args = expected.get("arguments", {})
    actual_args = actual.get("arguments", {})

    # tau2 behavior: compare_args=None → use actual's keys (check all)
    # tau2 behavior: compare_args=[] → match on name only
    if compare_keys is None:
        compare_keys = list(actual_args.keys())

    if len(compare_keys) == 0:
        return True

    tool_args = {k: v for k, v in actual_args.items() if k in compare_keys}
    action_args = {k: v for k, v in expected_args.items() if k in compare_keys}
    return tool_args == action_args


def _action_detail(expected: dict, actual: dict | None) -> str:
    """Build a compact action match explanation."""
    name = expected.get("name", "")
    expected_args = expected.get("arguments", {})
    compare_args = expected.get("compare_args")
    if actual is None:
        return (
            f"expected tool {name} not found "
            f"(expected_args={expected_args}, compare_args={compare_args})"
        )
    return (
        f"expected tool {name} found "
        f"(actual_args={actual.get('arguments', {})}, requestor={actual.get('requestor')})"
    )
