"""
Tests for simulation adapter.

Uses native frozen types — no mocks needed.
"""

from policybeats.simulation_adapter import (
    Message,
    RewardInfo,
    SimulationRun,
    ToolCall,
    message_to_event,
    simulation_to_bundle,
)
from policybeats.types import EventKind


def test_message_to_event_user_message():
    msg = Message(role="user", content="Hello, I need help")
    event = message_to_event(msg, 0)

    assert event.i == 0
    assert event.kind == EventKind.USER_MESSAGE
    assert event.actor == "user"
    assert event.payload["content"] == "Hello, I need help"


def test_message_to_event_assistant_message():
    msg = Message(role="assistant", content="I can help you")
    event = message_to_event(msg, 1)

    assert event.kind == EventKind.AGENT_MESSAGE
    assert event.actor == "assistant"


def test_message_to_event_with_tool_calls():
    tc = ToolCall(name="search_flights", arguments={"origin": "NYC", "dest": "LAX"}, id="call_123")
    msg = Message(role="assistant", tool_calls=(tc,))
    event = message_to_event(msg, 2)

    assert event.kind == EventKind.AGENT_MESSAGE
    assert len(event.payload["tool_calls"]) == 1
    assert event.payload["tool_calls"][0]["name"] == "search_flights"


def test_message_to_event_tool_result():
    msg = Message(role="tool", content='{"flights": [...]}', tool_call_id="call_123")
    event = message_to_event(msg, 3)

    assert event.kind == EventKind.TOOL_RESULT
    assert event.actor == "tool"
    assert event.call_id == "call_123"


def test_message_to_event_tool_error():
    msg = Message(role="tool", content="Error: Invalid arguments", error=True, tool_call_id="call_456")
    event = message_to_event(msg, 4)

    assert event.kind == EventKind.TOOL_RESULT
    assert event.payload.get("error") is True


def test_simulation_to_bundle_success():
    sim = SimulationRun(
        task_id="task_0",
        messages=(
            Message(role="user", content="Book a flight"),
            Message(role="assistant", content="I'll help you"),
        ),
        reward_info=RewardInfo(reward=1.0),
        termination_reason="agent_stop",
        seed=42,
        trial=1,
        duration=5.5,
        agent_cost=0.01,
    )
    bundle = simulation_to_bundle(sim, "airline")

    assert bundle.episode_id == "airline_task_0_1"
    assert bundle.exposed_state.success is True
    assert bundle.exposed_state.end_reason == "agent_stop"
    assert bundle.exposed_state.data["reward"] == 1.0
    assert bundle.metadata.domain == "airline"
    assert bundle.metadata.seed == 42
    assert len(bundle.trace) == 2


def test_simulation_to_bundle_failure():
    sim = SimulationRun(
        task_id="task_5",
        messages=(Message(role="assistant", content="Error occurred"),),
        reward_info=RewardInfo(reward=0.0),
        termination_reason="max_steps",
        duration=60.0,
        agent_cost=0.5,
    )
    bundle = simulation_to_bundle(sim, "retail")

    assert bundle.episode_id == "retail_task_5_0"
    assert bundle.exposed_state.success is False
    assert bundle.exposed_state.end_reason == "max_steps"


def test_simulation_to_bundle_no_reward_info():
    sim = SimulationRun(
        task_id="task_0",
        messages=(Message(role="user", content="hi"),),
    )
    bundle = simulation_to_bundle(sim, "telecom")

    assert bundle.exposed_state.success is False
    assert bundle.exposed_state.data["reward"] == 0.0
