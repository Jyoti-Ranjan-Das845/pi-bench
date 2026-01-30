"""
Gateway helpers for checking trace events across failure modes.

Per GOAL.md Section 18, checkers must cover BOTH execution gateways:
- TEXT GATEWAY: agent_message.content
- TOOL GATEWAY: tool_call.tool, tool_call.arguments, tool_result.result
"""

from __future__ import annotations

from collections.abc import Callable

from policybeats.types import EventKind, EvidencePointer, Trace


def _extract_all_strings_from_value(value: object, max_depth: int = 5) -> list[str]:
    """Recursively extract all string values from a nested structure."""
    if max_depth <= 0:
        return []

    strings: list[str] = []

    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for v in value.values():
            strings.extend(_extract_all_strings_from_value(v, max_depth - 1))
    elif isinstance(value, (list, tuple)):
        for item in value:
            strings.extend(_extract_all_strings_from_value(item, max_depth - 1))

    return strings


def _check_text_gateway(
    trace: Trace,
    match_fn: Callable[[str], tuple[int, int] | None],
) -> EvidencePointer | None:
    """
    Check TEXT GATEWAY (agent_message.content) for matches.

    Args:
        trace: The trace to check
        match_fn: Function that returns (start, end) span if match found, None otherwise

    Returns:
        EvidencePointer if violation found, None otherwise
    """
    for event in trace:
        if event.kind == EventKind.AGENT_MESSAGE:
            content = str(event.payload.get("content", ""))
            match = match_fn(content)
            if match:
                return EvidencePointer(
                    event_i=event.i,
                    field_path=("payload", "content"),
                    span=match,
                    note="text_gateway",
                )
    return None


def _check_tool_args_gateway(
    trace: Trace,
    match_fn: Callable[[str], tuple[int, int] | None],
) -> EvidencePointer | None:
    """
    Check TOOL GATEWAY - arguments (tool_call.arguments) for matches.

    Args:
        trace: The trace to check
        match_fn: Function that returns (start, end) span if match found, None otherwise

    Returns:
        EvidencePointer if violation found, None otherwise
    """
    for event in trace:
        if event.kind == EventKind.TOOL_CALL:
            arguments = event.payload.get("arguments", {})
            # Check all string values in arguments recursively
            all_strings = _extract_all_strings_from_value(arguments)
            for arg_str in all_strings:
                match = match_fn(arg_str)
                if match:
                    return EvidencePointer(
                        event_i=event.i,
                        field_path=("payload", "arguments"),
                        span=match,
                        note="tool_args_gateway",
                    )
    return None


def _check_tool_result_gateway(
    trace: Trace,
    match_fn: Callable[[str], tuple[int, int] | None],
) -> EvidencePointer | None:
    """
    Check TOOL GATEWAY - results (tool_result.result) for matches.

    This catches policy violations where sensitive data is returned by a tool
    and could be echoed or processed by the agent.

    Args:
        trace: The trace to check
        match_fn: Function that returns (start, end) span if match found, None otherwise

    Returns:
        EvidencePointer if violation found, None otherwise
    """
    for event in trace:
        if event.kind == EventKind.TOOL_RESULT:
            result = event.payload.get("result", {})
            # Check all string values in result recursively
            all_strings = _extract_all_strings_from_value(result)
            for result_str in all_strings:
                match = match_fn(result_str)
                if match:
                    return EvidencePointer(
                        event_i=event.i,
                        field_path=("payload", "result"),
                        span=match,
                        note="tool_result_gateway",
                    )
    return None


def _check_all_gateways(
    trace: Trace,
    match_fn: Callable[[str], tuple[int, int] | None],
) -> tuple[EvidencePointer, ...]:
    """
    Check ALL THREE gateways for matches:
    1. TEXT GATEWAY: agent_message.content
    2. TOOL ARGS GATEWAY: tool_call.arguments
    3. TOOL RESULT GATEWAY: tool_result.result

    Returns all violations found (may be multiple).
    """
    violations: list[EvidencePointer] = []

    text_violation = _check_text_gateway(trace, match_fn)
    if text_violation:
        violations.append(text_violation)

    tool_args_violation = _check_tool_args_gateway(trace, match_fn)
    if tool_args_violation:
        violations.append(tool_args_violation)

    tool_result_violation = _check_tool_result_gateway(trace, match_fn)
    if tool_result_violation:
        violations.append(tool_result_violation)

    return tuple(violations)


# Backwards compatibility alias
def _check_both_gateways(
    trace: Trace,
    match_fn: Callable[[str], tuple[int, int] | None],
) -> tuple[EvidencePointer, ...]:
    """
    DEPRECATED: Use _check_all_gateways instead.

    This now checks all three gateways for security completeness.
    """
    return _check_all_gateways(trace, match_fn)
