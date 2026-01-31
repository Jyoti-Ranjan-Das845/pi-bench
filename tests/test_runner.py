"""Tests for adapters/runner.py - simulation runner."""

import pytest

from pi_bench.adapters.domains.mock import create_mock_domain
from pi_bench.adapters.runner import run_simulation, run_with_mock_llm
from pi_bench.ports.llm import MockLLMPort
from pi_bench.sim.types import (
    MessageKind,
    TaskConfig,
    TerminationReason,
    UserInstruction,
)


def make_task(
    task_id: str = "test_task",
    goal: str = "Complete a test task",
    max_steps: int = 20,
) -> TaskConfig:
    """Create a test task config."""
    return TaskConfig(
        task_id=task_id,
        domain="mock",
        system_prompt="You are a helpful assistant with access to tools.",
        user_instruction=UserInstruction(goal=goal),
        initial_db={},
        available_tools=("echo", "get_data", "set_data"),
        max_steps=max_steps,
    )


class TestRunSimulation:
    """Test run_simulation function."""

    def test_run_simple_conversation(self):
        """Test a simple user-agent conversation that completes."""
        task = make_task()
        tools = create_mock_domain()

        # Mock LLM that alternates between user and agent
        # User says task complete after agent responds once
        mock_llm = MockLLMPort(responses=[
            "Hello! Please help me test this.",  # User first message
            "I'll help you test this. The test is complete!",  # Agent response
            "Thank you! TASK_COMPLETE",  # User confirms done
        ])

        result = run_simulation(task, mock_llm, tools, max_iterations=10)

        assert result.task_id == "test_task"
        assert result.domain == "mock"
        assert result.success is True
        assert result.termination_reason == TerminationReason.SUCCESS

    def test_run_reaches_max_iterations(self):
        """Test that simulation stops at max_iterations."""
        task = make_task()
        tools = create_mock_domain()

        # Mock LLM that never says TASK_COMPLETE
        mock_llm = MockLLMPort(responses=[
            "Please help me.",
            "Sure, how can I help?",
            "I need more help.",
            "What else do you need?",
        ])

        result = run_simulation(task, mock_llm, tools, max_iterations=5)

        # Should hit max steps and not complete successfully
        assert result.termination_reason == TerminationReason.MAX_STEPS
        assert result.success is False


class TestRunWithMockLLM:
    """Test run_with_mock_llm convenience function."""

    def test_basic_mock_run(self):
        """Test running with predefined mock responses."""
        task = make_task()
        tools = create_mock_domain()

        result = run_with_mock_llm(
            task=task,
            tools=tools,
            agent_responses=["I can help you with that.", "All done!"],
            user_responses=["Please help me.", "TASK_COMPLETE"],
        )

        assert result.task_id == "test_task"
        # Check trajectory has messages
        assert len(result.trajectory) > 0


class TestMockDomainTools:
    """Test mock domain tools work correctly in simulation."""

    def test_echo_tool_available(self):
        """Test echo tool is registered."""
        tools = create_mock_domain()

        assert "echo" in tools.list_tools()
        assert tools.get_tool("echo") is not None

    def test_data_tools_available(self):
        """Test data tools are registered."""
        tools = create_mock_domain()

        assert "get_data" in tools.list_tools()
        assert "set_data" in tools.list_tools()
        assert tools.get_tool("get_data") is not None
        assert tools.get_tool("set_data") is not None

    def test_user_tools_available(self):
        """Test user management tools are registered."""
        tools = create_mock_domain()

        assert "list_users" in tools.list_tools()
        assert "create_user" in tools.list_tools()
        assert "get_user" in tools.list_tools()
        assert "update_user" in tools.list_tools()

    def test_task_tools_available(self):
        """Test task management tools are registered."""
        tools = create_mock_domain()

        assert "list_tasks" in tools.list_tools()
        assert "create_task" in tools.list_tools()
        assert "complete_task" in tools.list_tools()

    def test_tool_schemas_generated(self):
        """Test tool schemas are available."""
        tools = create_mock_domain()

        schemas = tools.get_schemas()
        assert len(schemas) > 0

        # Check schema format
        for schema in schemas:
            assert schema["type"] == "function"
            assert "function" in schema
            assert "name" in schema["function"]
            assert "description" in schema["function"]


class TestTaskLoader:
    """Test task loader functionality."""

    def test_mock_task_loader(self):
        """Test mock task loader has tasks."""
        from pi_bench.ports.tasks import create_mock_task_loader

        loader = create_mock_task_loader()

        tasks = loader.list_tasks()
        assert len(tasks) > 0
        assert "echo_task" in tasks

    def test_load_task(self):
        """Test loading a specific task."""
        from pi_bench.ports.tasks import create_mock_task_loader

        loader = create_mock_task_loader()
        task = loader.load("echo_task")

        assert task.task_id == "echo_task"
        assert task.domain == "mock"
        assert "echo" in task.available_tools

    def test_load_missing_task_raises(self):
        """Test loading missing task raises KeyError."""
        from pi_bench.ports.tasks import create_mock_task_loader

        loader = create_mock_task_loader()

        with pytest.raises(KeyError):
            loader.load("nonexistent_task")


class TestMockLLMPort:
    """Test MockLLMPort for testing."""

    def test_mock_cycles_responses(self):
        """Test mock LLM cycles through responses."""
        mock = MockLLMPort(responses=["first", "second", "third"])

        r1 = mock.generate(messages=(), role="agent")
        r2 = mock.generate(messages=(), role="user")
        r3 = mock.generate(messages=(), role="agent")
        r4 = mock.generate(messages=(), role="user")

        assert r1.content == "first"
        assert r2.content == "second"
        assert r3.content == "third"
        assert r4.content == "first"  # Cycles back

    def test_mock_returns_correct_kind(self):
        """Test mock returns correct message kind."""
        mock = MockLLMPort(responses=["test"])

        agent_msg = mock.generate(messages=(), role="agent")
        user_msg = mock.generate(messages=(), role="user")

        assert agent_msg.kind == MessageKind.AGENT
        assert user_msg.kind == MessageKind.USER

    def test_mock_model_name(self):
        """Test mock model name."""
        mock = MockLLMPort(model="test-model")
        assert mock.model_name == "test-model"
