"""
Assessment flow orchestration for PolicyBeats Green Agent.

This module handles the A2A assessment flow:
1. Receive assessment request with Purple Agent endpoint
2. Send policy compliance scenarios to Purple Agent
3. Collect responses and build traces
4. Score using PolicyBeats deterministic checkers
5. Return results in AgentBeats format
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any

from pi_bench.a2a.tool_executor import env_from_context, execute_tool
from pi_bench.a2a.results import to_agentbeats_results
from pi_bench.a2a.scenarios import (
    ALL_SCENARIOS,
    Scenario,
    scenario_to_task_message,
)
from pi_bench.artifact import make_artifact
from pi_bench.score import aggregate, score_episode
from pi_bench.trace import normalize_trace
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EpisodeResult,
    EventKind,
    ExposedState,
    PolicyPack,
    RunMetadata,
    TraceEvent,
)


@dataclass
class AssessmentConfig:
    """Configuration for an assessment run."""

    num_tasks: int = 8  # Number of scenarios to run
    timeout_per_task: float = 60.0  # Timeout per task in seconds
    domain: str = "policy_compliance"


@dataclass
class AssessmentRequest:
    """Request to run an assessment."""

    purple_agent_url: str
    purple_agent_id: str
    config: AssessmentConfig


@dataclass
class AssessmentResult:
    """Result of an assessment run."""

    success: bool
    results_json: dict[str, Any]
    error: str | None = None


async def send_task_to_purple_agent(
    purple_agent_url: str,
    task_message: dict[str, Any],
    timeout: float = 60.0,
) -> dict[str, Any] | None:
    """
    Send a task to the purple agent via A2A protocol.

    This is a simplified implementation. In production, use the full
    A2A SDK from litellm.a2a_protocol.

    Args:
        purple_agent_url: URL of the purple agent's A2A endpoint
        task_message: Task message to send
        timeout: Timeout in seconds

    Returns:
        Response from purple agent, or None on error
    """
    import aiohttp

    # Build A2A message
    message_id = uuid.uuid4().hex
    a2a_request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "parts": [
                    {
                        "kind": "text",
                        "text": json.dumps(task_message),
                    }
                ],
                "messageId": message_id,
            }
        },
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                purple_agent_url,
                json=a2a_request,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    return result
                else:
                    return None
    except Exception:
        return None


def _execute_scenario_tool(
    tool_name: str, arguments: dict[str, Any], scenario: Scenario
) -> dict[str, Any]:
    """Execute a tool using scenario context as environment seed."""
    env = env_from_context(scenario.context or {})
    return execute_tool(tool_name, arguments, env)


def response_to_trace(
    scenario: Scenario,
    response: dict[str, Any] | None,
) -> tuple[TraceEvent, ...]:
    """
    Convert purple agent response to a trace.

    Args:
        scenario: The scenario that was run
        response: Response from the purple agent (or None if failed)

    Returns:
        Trace of events
    """
    events: list[dict[str, Any]] = []

    # Event 0: User message (the task instruction)
    events.append({
        "i": 0,
        "kind": "user_message",
        "actor": "user",
        "payload": {"content": scenario.task_instruction},
    })

    if response is None:
        # Agent failed to respond - add termination
        events.append({
            "i": 1,
            "kind": "termination",
            "actor": "env",
            "payload": {"reason": "agent_timeout"},
        })
        return normalize_trace(events)

    # Parse response
    try:
        result = response.get("result", {})
        message = result.get("message", {})
        parts = message.get("parts", [])

        event_i = 1

        for part in parts:
            kind = part.get("kind", "text")

            if kind == "text":
                # Agent text response
                events.append({
                    "i": event_i,
                    "kind": "agent_message",
                    "actor": "agent",
                    "payload": {"content": part.get("text", "")},
                })
                event_i += 1

            elif kind == "tool_call":
                # Agent made a tool call
                call_id = part.get("callId", f"call_{event_i}")
                events.append({
                    "i": event_i,
                    "kind": "tool_call",
                    "actor": "agent",
                    "payload": {
                        "tool": part.get("name", "unknown"),
                        "arguments": part.get("arguments", {}),
                    },
                    "call_id": call_id,
                })
                event_i += 1

                # Execute tool against environment
                tool_name = part.get("name", "unknown")
                tool_args = part.get("arguments", {})
                tool_result = _execute_scenario_tool(tool_name, tool_args, scenario)
                events.append({
                    "i": event_i,
                    "kind": "tool_result",
                    "actor": "tool",
                    "payload": {"result": tool_result},
                    "call_id": call_id,
                })
                event_i += 1

            elif kind == "tool_result":
                # Tool result from agent
                call_id = part.get("callId", f"call_{event_i}")
                events.append({
                    "i": event_i,
                    "kind": "tool_result",
                    "actor": "tool",
                    "payload": {"result": part.get("result", "")},
                    "call_id": call_id,
                })
                event_i += 1

    except Exception:
        # Failed to parse - add simple agent message
        events.append({
            "i": 1,
            "kind": "agent_message",
            "actor": "agent",
            "payload": {"content": str(response)},
        })

    return normalize_trace(events)


async def run_scenario(
    scenario: Scenario,
    purple_agent_url: str,
    timeout: float = 60.0,
) -> EpisodeResult:
    """
    Run a single scenario against the purple agent.

    Args:
        scenario: The scenario to run
        purple_agent_url: URL of the purple agent
        timeout: Timeout in seconds

    Returns:
        EpisodeResult with scoring
    """
    # Build task message
    task_message = scenario_to_task_message(scenario)

    # Send to purple agent
    response = await send_task_to_purple_agent(
        purple_agent_url,
        task_message,
        timeout=timeout,
    )

    # Convert response to trace
    trace = response_to_trace(scenario, response)

    # Build episode bundle
    bundle = EpisodeBundle(
        episode_id=scenario.scenario_id,
        trace=trace,
        exposed_state=ExposedState(
            success=response is not None,
            data=scenario.context,
        ),
        metadata=EpisodeMetadata(
            domain=scenario.surface,
            config={"scenario_name": scenario.name},
        ),
    )

    # Score episode
    result = score_episode(bundle, scenario.policy_pack)

    return result


async def run_assessment(request: AssessmentRequest) -> AssessmentResult:
    """
    Run a complete assessment against a purple agent.

    Args:
        request: Assessment request with purple agent details

    Returns:
        AssessmentResult with scores
    """
    start_time = time.time()

    try:
        # Select scenarios to run
        scenarios = ALL_SCENARIOS[: request.config.num_tasks]

        # Run all scenarios
        results: list[EpisodeResult] = []
        for scenario in scenarios:
            result = await run_scenario(
                scenario,
                request.purple_agent_url,
                timeout=request.config.timeout_per_task,
            )
            results.append(result)

        # Sort results by episode_id for determinism
        results_tuple = tuple(sorted(results, key=lambda r: r.episode_id))

        # Aggregate metrics
        summary = aggregate(results_tuple)

        # Build artifact
        # Use the first scenario's policy pack for artifact metadata
        # In practice, we might want a combined policy pack
        first_policy = scenarios[0].policy_pack if scenarios else PolicyPack(
            policy_pack_id="empty",
            version="0.0.0",
            rules=(),
        )

        artifact = make_artifact(
            results=results_tuple,
            summary=summary,
            policy_pack=first_policy,
            run_metadata=RunMetadata(
                evaluator_version="policybeats-0.1.0",
                config={
                    "num_tasks": request.config.num_tasks,
                    "domain": request.config.domain,
                },
            ),
        )

        # Convert to AgentBeats format
        time_used = time.time() - start_time
        results_json = to_agentbeats_results(
            artifact,
            request.purple_agent_id,
            time_used,
        )

        return AssessmentResult(
            success=True,
            results_json=results_json,
        )

    except Exception as e:
        return AssessmentResult(
            success=False,
            results_json={},
            error=str(e),
        )


def run_assessment_sync(request: AssessmentRequest) -> AssessmentResult:
    """Synchronous wrapper for run_assessment."""
    return asyncio.run(run_assessment(request))
