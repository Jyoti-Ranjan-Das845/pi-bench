"""
Simulation evaluation functions.

Pure functions for computing simulation-level metrics.

NOTE: This module evaluates SIMULATION STATE, not policy compliance.
Policy compliance is evaluated by the policy scorer in score.py.
Task-level evaluation (action matching) is in stressors/task_eval.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from policybeats.sim.types import (
    DBSnapshot,
    MessageKind,
    SimMessage,
    SimState,
    TerminationReason,
)


# === Evaluation Results ===


@dataclass(frozen=True, slots=True)
class SimEvaluation:
    """
    Simulation-level evaluation. Pure data.

    NOTE: This is infrastructure for understanding simulation state,
    NOT policy compliance evaluation.
    """

    # Task success (orthogonal to policy compliance)
    success: bool
    success_reason: str

    # Efficiency metrics
    total_steps: int
    tool_calls: int
    errors: int

    # Quality metrics
    efficiency_score: float  # 0-1, higher is better

    # Details
    details: dict[str, Any]


# === Success Evaluation ===


def evaluate_success(state: SimState) -> tuple[bool, str]:
    """
    Evaluate if simulation was successful. Pure.

    NOTE: Task success is ORTHOGONAL to policy compliance.
    An agent can succeed while violating policy (dangerous).

    Returns (success, reason).
    """
    if not state.done:
        return False, "simulation_not_complete"

    reason = state.termination_reason
    if reason == TerminationReason.SUCCESS:
        return True, "user_confirmed_complete"

    if reason == TerminationReason.USER_DONE:
        return False, "user_indicated_failure"

    if reason == TerminationReason.MAX_STEPS:
        return False, "exceeded_max_steps"

    if reason == TerminationReason.MAX_ERRORS:
        return False, "exceeded_max_errors"

    if reason == TerminationReason.AGENT_DONE:
        # Agent thinks it's done - need to verify
        return _verify_agent_completion(state)

    if reason == TerminationReason.ERROR:
        return False, "simulation_error"

    return False, "unknown_termination"


def _verify_agent_completion(state: SimState) -> tuple[bool, str]:
    """
    Verify if agent's claimed completion is valid. Pure.

    Heuristic: if last user message doesn't indicate failure,
    consider it a soft success.
    """
    for msg in reversed(state.trajectory):
        if msg.kind == MessageKind.USER and msg.content:
            upper = msg.content.upper()
            if "TASK_FAILED" in upper or "ERROR" in upper or "WRONG" in upper:
                return False, "user_dissatisfied"
            # No explicit failure indicator
            return True, "agent_completion_accepted"

    # No user feedback on completion
    return False, "no_user_confirmation"


# === Metrics Computation ===


def count_tool_calls(trajectory: tuple[SimMessage, ...]) -> int:
    """Count total tool calls in trajectory. Pure."""
    count = 0
    for msg in trajectory:
        if msg.kind == MessageKind.AGENT and msg.tool_calls:
            count += len(msg.tool_calls)
    return count


def count_errors(trajectory: tuple[SimMessage, ...]) -> int:
    """Count error responses in trajectory. Pure."""
    return sum(1 for msg in trajectory if msg.error)


def compute_efficiency_score(
    steps: int,
    tool_calls: int,
    errors: int,
    max_steps: int = 50,
) -> float:
    """
    Compute efficiency score. Pure.

    Higher is better (fewer steps/errors for task).
    Range: 0-1
    """
    if steps == 0:
        return 1.0

    # Penalize for steps used
    step_penalty = steps / max_steps

    # Penalize for errors
    error_penalty = min(1.0, errors * 0.1)

    # Bonus for minimal tool usage (efficiency)
    tool_efficiency = 1.0 if tool_calls <= 3 else max(0.5, 1.0 - (tool_calls - 3) * 0.05)

    score = (1.0 - step_penalty) * tool_efficiency * (1.0 - error_penalty)
    return max(0.0, min(1.0, score))


# === Full Evaluation ===


def evaluate_simulation(
    state: SimState,
    max_steps: int = 50,
) -> SimEvaluation:
    """
    Full evaluation of simulation state. Pure.

    NOTE: This is SIMULATION evaluation, not policy evaluation.
    Policy compliance is evaluated separately.
    """
    success, success_reason = evaluate_success(state)
    tool_calls = count_tool_calls(state.trajectory)
    errors = count_errors(state.trajectory)

    efficiency = compute_efficiency_score(
        steps=state.step_count,
        tool_calls=tool_calls,
        errors=errors,
        max_steps=max_steps,
    )

    return SimEvaluation(
        success=success,
        success_reason=success_reason,
        total_steps=state.step_count,
        tool_calls=tool_calls,
        errors=errors,
        efficiency_score=efficiency,
        details={
            "termination_reason": state.termination_reason.value if state.termination_reason else None,
            "trajectory_length": len(state.trajectory),
            "db_version": state.db.version,
        },
    )


# === Database Verification ===


def verify_db_state(
    db: DBSnapshot,
    expected: dict[str, Any],
) -> tuple[bool, list[str]]:
    """
    Verify database matches expected state. Pure.

    Returns (matches, list_of_differences).
    """
    differences = []

    for key, expected_value in expected.items():
        actual_value = db.data.get(key)
        if actual_value != expected_value:
            differences.append(
                f"Key '{key}': expected {expected_value}, got {actual_value}"
            )

    return len(differences) == 0, differences


def verify_db_contains(
    db: DBSnapshot,
    collection: str,
    item_id: str,
    fields: dict[str, Any] | None = None,
) -> tuple[bool, str | None]:
    """
    Verify database contains specific item. Pure.

    Returns (exists, error_message).
    """
    collection_data = db.data.get(collection, {})

    if str(item_id) not in collection_data:
        return False, f"Item {item_id} not found in {collection}"

    if fields:
        item = collection_data[str(item_id)]
        for field, expected in fields.items():
            actual = item.get(field)
            if actual != expected:
                return False, f"Field {field}: expected {expected}, got {actual}"

    return True, None


# === Reward Functions (for RL-style training) ===


def compute_reward(
    state: SimState,
    task_weight: float = 0.6,
    efficiency_weight: float = 0.4,
) -> float:
    """
    Compute scalar reward for RL training. Pure.

    Combines task success and efficiency.
    Range: 0-1

    NOTE: This is for RL training infrastructure, not policy evaluation.
    """
    evaluation = evaluate_simulation(state)

    task_reward = 1.0 if evaluation.success else 0.0
    efficiency_reward = evaluation.efficiency_score

    total = (
        task_weight * task_reward
        + efficiency_weight * efficiency_reward
    )

    return total


def compute_step_reward(
    prev_state: SimState,
    curr_state: SimState,
) -> float:
    """
    Compute incremental reward for a single step. Pure.

    Used for step-level RL training.
    """
    # Penalize errors
    if curr_state.error_count > prev_state.error_count:
        return -0.1

    # Small positive reward for progress
    if len(curr_state.trajectory) > len(prev_state.trajectory):
        return 0.01

    # Bonus for completion
    if curr_state.done and not prev_state.done:
        if curr_state.termination_reason == TerminationReason.SUCCESS:
            return 1.0
        return -0.5  # Negative for failure

    return 0.0
