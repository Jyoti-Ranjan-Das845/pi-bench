"""Tests for sim/orchestration.py - pure orchestration functions."""

import pytest

from pi_bench.sim.orchestration import (
    init_simulation,
    integrate_tool_result,
    step,
    to_episode_trace,
)
from pi_bench.sim.types import (
    DBSnapshot,
    DoneEffect,
    LLMCallEffect,
    MessageKind,
    SimMessage,
    SimState,
    TaskConfig,
    TerminationReason,
    ToolCallData,
    ToolExecEffect,
    UserInstruction,
)


def make_task(
    task_id: str = "test_task",
    goal: str = "Test goal",
    max_steps: int = 50,
) -> TaskConfig:
    """Create a test task config."""
    return TaskConfig(
        task_id=task_id,
        domain="mock",
        system_prompt="You are a helpful assistant.",
        user_instruction=UserInstruction(goal=goal),
        initial_db={},
        available_tools=("echo",),
        max_steps=max_steps,
    )


class TestInitSimulation:
    """Test init_simulation function."""

    def test_init_creates_state(self):
        task = make_task()
        result = init_simulation(task)

        assert result.state.trajectory == ()
        assert result.state.step_count == 0
        assert result.state.done is False
        assert result.state.task_id == "test_task"
        assert result.state.domain == "mock"

    def test_init_returns_user_effect(self):
        task = make_task()
        result = init_simulation(task)

        assert len(result.effects) == 1
        effect = result.effects[0]
        assert isinstance(effect, LLMCallEffect)
        assert effect.role == "user"

    def test_init_with_initial_db(self):
        task = TaskConfig(
            task_id="test",
            domain="mock",
            system_prompt="Test",
            user_instruction=UserInstruction(goal="Test"),
            initial_db={"count": 5},
        )
        result = init_simulation(task)

        assert result.state.db.data == {"count": 5}
        assert result.state.db.version == 0


class TestStep:
    """Test step function."""

    def test_step_on_done_state_noop(self):
        state = SimState(done=True, termination_reason=TerminationReason.SUCCESS)
        result = step(state, None)

        assert result.state.done is True
        assert result.effects == ()

    def test_step_integrates_response(self):
        state = SimState()
        msg = SimMessage(kind=MessageKind.USER, content="Hello")
        result = step(state, msg)

        assert len(result.state.trajectory) == 1
        assert result.state.trajectory[0].content == "Hello"
        assert result.state.step_count == 1

    def test_step_after_user_returns_agent_effect(self):
        # Create state with user message
        user_msg = SimMessage(kind=MessageKind.USER, content="Hi there")
        state = SimState(trajectory=(user_msg,))

        result = step(state, None)

        # Should return effect for agent to respond
        assert len(result.effects) == 1
        effect = result.effects[0]
        assert isinstance(effect, LLMCallEffect)
        assert effect.role == "agent"

    def test_step_after_agent_no_tools_returns_user_effect(self):
        # Create state with user + agent messages
        user_msg = SimMessage(kind=MessageKind.USER, content="Hi")
        agent_msg = SimMessage(kind=MessageKind.AGENT, content="Hello!")
        state = SimState(trajectory=(user_msg, agent_msg))

        result = step(state, None)

        # Should return effect for user to respond
        assert len(result.effects) == 1
        effect = result.effects[0]
        assert isinstance(effect, LLMCallEffect)
        assert effect.role == "user"

    def test_step_after_agent_with_tools_returns_tool_effect(self):
        # Create state with agent message that has tool calls
        user_msg = SimMessage(kind=MessageKind.USER, content="Echo hello")
        tool_call = ToolCallData(call_id="call_1", name="echo", arguments={"message": "hello"})
        agent_msg = SimMessage(
            kind=MessageKind.AGENT,
            content="Let me echo that.",
            tool_calls=(tool_call,),
        )
        state = SimState(trajectory=(user_msg, agent_msg))

        result = step(state, None)

        # Should return effect to execute tool
        assert len(result.effects) == 1
        effect = result.effects[0]
        assert isinstance(effect, ToolExecEffect)
        assert effect.tool_name == "echo"
        assert effect.call_id == "call_1"

    def test_step_after_tool_result_returns_agent_effect(self):
        # Create state with tool result
        user_msg = SimMessage(kind=MessageKind.USER, content="Echo hello")
        tool_call = ToolCallData(call_id="call_1", name="echo", arguments={"message": "hello"})
        agent_msg = SimMessage(
            kind=MessageKind.AGENT,
            content="Echoing...",
            tool_calls=(tool_call,),
        )
        tool_result = SimMessage(
            kind=MessageKind.TOOL_RESULT,
            content="Echo: hello",
            call_id="call_1",
        )
        state = SimState(trajectory=(user_msg, agent_msg, tool_result))

        result = step(state, None)

        # Should return effect for agent to continue
        assert len(result.effects) == 1
        effect = result.effects[0]
        assert isinstance(effect, LLMCallEffect)
        assert effect.role == "agent"


class TestTermination:
    """Test termination checking."""

    def test_terminates_on_task_complete(self):
        user_msg = SimMessage(kind=MessageKind.USER, content="TASK_COMPLETE")
        state = SimState(trajectory=(user_msg,), step_count=1)

        result = step(state, None)

        assert result.state.done is True
        assert result.state.termination_reason == TerminationReason.SUCCESS
        assert len(result.effects) == 1
        assert isinstance(result.effects[0], DoneEffect)

    def test_terminates_on_task_failed(self):
        user_msg = SimMessage(kind=MessageKind.USER, content="TASK_FAILED - I give up")
        state = SimState(trajectory=(user_msg,), step_count=1)

        result = step(state, None)

        assert result.state.done is True
        assert result.state.termination_reason == TerminationReason.USER_DONE

    def test_terminates_on_max_errors(self):
        state = SimState(error_count=3)
        result = step(state, None)

        assert result.state.done is True
        assert result.state.termination_reason == TerminationReason.MAX_ERRORS


class TestIntegrateToolResult:
    """Test integrate_tool_result function."""

    def test_integrate_success(self):
        state = SimState()
        new_db = DBSnapshot(data={"updated": True}, version=1)

        new_state = integrate_tool_result(
            state,
            call_id="call_1",
            result='{"success": true}',
            new_db=new_db,
            is_error=False,
        )

        assert len(new_state.trajectory) == 1
        msg = new_state.trajectory[0]
        assert msg.kind == MessageKind.TOOL_RESULT
        assert msg.call_id == "call_1"
        assert msg.error is False
        assert new_state.db == new_db

    def test_integrate_error(self):
        state = SimState()
        db = DBSnapshot()

        new_state = integrate_tool_result(
            state,
            call_id="call_1",
            result="Error: Something went wrong",
            new_db=db,
            is_error=True,
        )

        assert new_state.trajectory[0].error is True
        assert new_state.error_count == 1


class TestToEpisodeTrace:
    """Test to_episode_trace conversion."""

    def test_convert_simple_trajectory(self):
        user_msg = SimMessage(kind=MessageKind.USER, content="Hello")
        agent_msg = SimMessage(kind=MessageKind.AGENT, content="Hi there!")
        state = SimState(trajectory=(user_msg, agent_msg))

        trace = to_episode_trace(state)

        assert len(trace) == 2
        assert trace[0]["i"] == 0
        assert trace[0]["kind"] == "user_message"
        assert trace[0]["actor"] == "user"
        assert trace[0]["payload"]["content"] == "Hello"

        assert trace[1]["i"] == 1
        assert trace[1]["kind"] == "agent_message"
        assert trace[1]["actor"] == "agent"

    def test_convert_tool_calls(self):
        tool_call = ToolCallData(call_id="call_1", name="echo", arguments={"message": "hi"})
        agent_msg = SimMessage(
            kind=MessageKind.AGENT,
            content="Calling echo",
            tool_calls=(tool_call,),
        )
        tool_result = SimMessage(
            kind=MessageKind.TOOL_RESULT,
            content="Echo: hi",
            call_id="call_1",
        )
        state = SimState(trajectory=(agent_msg, tool_result))

        trace = to_episode_trace(state)

        assert len(trace) == 2
        assert "tool_calls" in trace[0]["payload"]
        assert trace[0]["payload"]["tool_calls"][0]["name"] == "echo"
        assert trace[1]["call_id"] == "call_1"
