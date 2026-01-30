"""Tests for sim/types.py - simulation type definitions."""

import pytest

from policybeats.sim.types import (
    DBSnapshot,
    EffectKind,
    LLMCallEffect,
    MessageKind,
    SimMessage,
    SimState,
    StepResult,
    TaskConfig,
    TerminationReason,
    ToolCallData,
    UserInstruction,
)


class TestMessageKind:
    """Test MessageKind enum."""

    def test_message_kinds_exist(self):
        assert MessageKind.USER == "user"
        assert MessageKind.AGENT == "agent"
        assert MessageKind.TOOL_CALL == "tool_call"
        assert MessageKind.TOOL_RESULT == "tool_result"
        assert MessageKind.SYSTEM == "system"


class TestToolCallData:
    """Test ToolCallData frozen dataclass."""

    def test_create_tool_call(self):
        tc = ToolCallData(call_id="call_1", name="echo", arguments={"message": "hi"})
        assert tc.call_id == "call_1"
        assert tc.name == "echo"
        assert tc.arguments == {"message": "hi"}

    def test_tool_call_is_frozen(self):
        tc = ToolCallData(call_id="call_1", name="echo", arguments={})
        with pytest.raises(AttributeError):
            tc.name = "other"  # type: ignore


class TestSimMessage:
    """Test SimMessage frozen dataclass."""

    def test_create_user_message(self):
        msg = SimMessage(kind=MessageKind.USER, content="Hello")
        assert msg.kind == MessageKind.USER
        assert msg.content == "Hello"
        assert msg.tool_calls == ()
        assert msg.call_id is None
        assert msg.error is False

    def test_create_agent_message_with_tools(self):
        tc = ToolCallData(call_id="call_1", name="echo", arguments={"message": "hi"})
        msg = SimMessage(
            kind=MessageKind.AGENT,
            content="Let me echo that.",
            tool_calls=(tc,),
        )
        assert msg.kind == MessageKind.AGENT
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0].name == "echo"

    def test_create_tool_result(self):
        msg = SimMessage(
            kind=MessageKind.TOOL_RESULT,
            content="Echo: hi",
            call_id="call_1",
        )
        assert msg.kind == MessageKind.TOOL_RESULT
        assert msg.call_id == "call_1"

    def test_message_is_frozen(self):
        msg = SimMessage(kind=MessageKind.USER, content="Hello")
        with pytest.raises(AttributeError):
            msg.content = "World"  # type: ignore


class TestDBSnapshot:
    """Test DBSnapshot frozen dataclass."""

    def test_create_empty_snapshot(self):
        db = DBSnapshot()
        assert db.data == {}
        assert db.version == 0

    def test_create_snapshot_with_data(self):
        db = DBSnapshot(data={"users": {"1": {"name": "Alice"}}}, version=5)
        assert db.data["users"]["1"]["name"] == "Alice"
        assert db.version == 5

    def test_with_data_returns_new_snapshot(self):
        db = DBSnapshot(data={"count": 1}, version=0)
        new_db = db.with_data({"count": 2})

        assert db.data["count"] == 1  # Original unchanged
        assert db.version == 0

        assert new_db.data["count"] == 2
        assert new_db.version == 1

    def test_snapshot_is_frozen(self):
        db = DBSnapshot(data={"x": 1})
        with pytest.raises(AttributeError):
            db.version = 10  # type: ignore


class TestUserInstruction:
    """Test UserInstruction frozen dataclass."""

    def test_create_simple_instruction(self):
        inst = UserInstruction(goal="Book a flight")
        assert inst.goal == "Book a flight"
        assert inst.context is None
        assert inst.constraints == ()

    def test_create_full_instruction(self):
        inst = UserInstruction(
            goal="Book a flight to NYC",
            context="Traveling for business",
            constraints=("Under $500", "Direct flight"),
        )
        assert inst.goal == "Book a flight to NYC"
        assert inst.context == "Traveling for business"
        assert len(inst.constraints) == 2


class TestTaskConfig:
    """Test TaskConfig frozen dataclass."""

    def test_create_task_config(self):
        task = TaskConfig(
            task_id="task_1",
            domain="mock",
            system_prompt="You are a helpful assistant.",
            user_instruction=UserInstruction(goal="Test the system"),
            initial_db={"users": {}},
            available_tools=("echo", "get_data"),
            max_steps=20,
        )
        assert task.task_id == "task_1"
        assert task.domain == "mock"
        assert task.max_steps == 20
        assert "echo" in task.available_tools


class TestSimState:
    """Test SimState frozen dataclass."""

    def test_create_empty_state(self):
        state = SimState()
        assert state.trajectory == ()
        assert state.db.data == {}
        assert state.step_count == 0
        assert state.error_count == 0
        assert state.done is False
        assert state.termination_reason is None

    def test_with_message(self):
        state = SimState()
        msg = SimMessage(kind=MessageKind.USER, content="Hello")
        new_state = state.with_message(msg)

        assert len(state.trajectory) == 0  # Original unchanged
        assert len(new_state.trajectory) == 1
        assert new_state.trajectory[0].content == "Hello"

    def test_with_db(self):
        state = SimState()
        new_db = DBSnapshot(data={"updated": True}, version=1)
        new_state = state.with_db(new_db)

        assert state.db.data == {}
        assert new_state.db.data == {"updated": True}

    def test_with_step(self):
        state = SimState()
        new_state = state.with_step()

        assert state.step_count == 0
        assert new_state.step_count == 1

    def test_with_error(self):
        state = SimState()
        new_state = state.with_error()

        assert state.error_count == 0
        assert new_state.error_count == 1

    def test_terminated(self):
        state = SimState()
        new_state = state.terminated(TerminationReason.SUCCESS)

        assert state.done is False
        assert new_state.done is True
        assert new_state.termination_reason == TerminationReason.SUCCESS

    def test_state_is_frozen(self):
        state = SimState()
        with pytest.raises(AttributeError):
            state.done = True  # type: ignore


class TestEffects:
    """Test effect dataclasses."""

    def test_llm_call_effect(self):
        effect = LLMCallEffect(
            role="agent",
            messages=(),
            system_prompt="You are helpful.",
            tools=None,
        )
        assert effect.role == "agent"
        assert effect.system_prompt == "You are helpful."

    def test_step_result(self):
        state = SimState()
        effect = LLMCallEffect(role="user", messages=())
        result = StepResult(state=state, effects=(effect,))

        assert result.state == state
        assert len(result.effects) == 1
