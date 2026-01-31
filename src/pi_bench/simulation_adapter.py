"""
Simulation adapter — bridges external simulation data to PolicyBeats scoring.

Native types replace the former tau2 dependency.
All types are frozen dataclasses (FP, no mutation).
Adapter functions are pure (hexagonal: imperative shell stays outside).

This module provides:
- Native simulation types: ToolCall, Message, RewardInfo, SimulationRun
- message_to_event: Message → TraceEvent
- simulation_to_bundle: SimulationRun → EpisodeBundle
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pi_bench.score import score_episode
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EpisodeResult,
    EventKind,
    ExposedState,
    PolicyPack,
    TraceEvent,
)

# === Native simulation types (replace tau2 dependency) ===


@dataclass(frozen=True, slots=True)
class ToolCall:
    """A single tool invocation."""

    name: str
    arguments: dict[str, Any]
    id: str


@dataclass(frozen=True, slots=True)
class Message:
    """A conversation message from any actor."""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str | None = None
    tool_calls: tuple[ToolCall, ...] | None = None
    tool_call_id: str | None = None
    error: bool = False


@dataclass(frozen=True, slots=True)
class RewardInfo:
    """Task reward from environment."""

    reward: float


@dataclass(frozen=True, slots=True)
class SimulationRun:
    """Result of a simulation episode."""

    task_id: str
    messages: tuple[Message, ...]
    reward_info: RewardInfo | None = None
    termination_reason: str | None = None
    duration: float | None = None
    agent_cost: float | None = None
    trial: int | None = None
    seed: int | None = None


# === Pure conversion functions ===


def message_to_event(msg: Message, i: int) -> TraceEvent:
    """
    Convert Message to PolicyBeats TraceEvent.

    Pure function. No I/O.
    """
    kind_map: dict[str, EventKind] = {
        "user": EventKind.USER_MESSAGE,
        "assistant": EventKind.AGENT_MESSAGE,
        "tool": EventKind.TOOL_RESULT,
        "system": EventKind.STATE_CHANGE,
    }

    payload: dict[str, Any] = {}
    if msg.content:
        payload["content"] = msg.content

    if msg.tool_calls:
        payload["tool_calls"] = [
            {"name": tc.name, "arguments": tc.arguments, "id": tc.id}
            for tc in msg.tool_calls
        ]

    if msg.error:
        payload["error"] = True

    return TraceEvent(
        i=i,
        kind=kind_map.get(msg.role, EventKind.AGENT_MESSAGE),
        actor=msg.role,
        payload=payload,
        call_id=msg.tool_call_id,
    )


def simulation_to_bundle(sim: SimulationRun, domain: str) -> EpisodeBundle:
    """
    Convert SimulationRun to PolicyBeats EpisodeBundle.

    Pure function. No I/O.
    """
    trace = tuple(message_to_event(msg, i) for i, msg in enumerate(sim.messages))

    reward = sim.reward_info.reward if sim.reward_info else 0.0

    data: dict[str, Any] = {"reward": reward}
    if sim.duration is not None:
        data["duration"] = sim.duration
    if sim.agent_cost is not None:
        data["agent_cost"] = sim.agent_cost

    exposed_state = ExposedState(
        success=reward > 0,
        end_reason=sim.termination_reason,
        data=data,
    )

    config: dict[str, Any] = {"task_id": sim.task_id}
    if sim.trial is not None:
        config["trial"] = sim.trial

    metadata = EpisodeMetadata(
        domain=domain,
        seed=sim.seed,
        config=config,
    )

    return EpisodeBundle(
        episode_id=f"{domain}_{sim.task_id}_{sim.trial or 0}",
        trace=trace,
        exposed_state=exposed_state,
        metadata=metadata,
    )


def score_simulation(
    sim: SimulationRun,
    domain: str,
    policy_pack: PolicyPack,
) -> EpisodeResult:
    """
    Score a SimulationRun with PolicyBeats.

    Pure function (delegates to score_episode).
    """
    bundle = simulation_to_bundle(sim, domain)
    return score_episode(bundle, policy_pack)
