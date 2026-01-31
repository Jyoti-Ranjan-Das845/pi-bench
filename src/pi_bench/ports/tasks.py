"""
Task Loader Port - abstract interface for loading task configurations.

Implementations provide task configs from different sources (files, APIs, etc.).
"""

from __future__ import annotations

from typing import Protocol

from pi_bench.sim.types import TaskConfig, UserInstruction


class TaskLoaderPort(Protocol):
    """
    Protocol for task loading.

    Implementations load task configurations from various sources.
    """

    def load(self, task_id: str) -> TaskConfig:
        """
        Load a task configuration by ID.

        Args:
            task_id: Unique task identifier

        Returns:
            TaskConfig for the task

        Raises:
            KeyError: If task_id not found
        """
        ...

    def list_tasks(self) -> tuple[str, ...]:
        """
        List all available task IDs.

        Returns:
            Tuple of task IDs
        """
        ...

    def list_domains(self) -> tuple[str, ...]:
        """
        List all available domains.

        Returns:
            Tuple of domain names
        """
        ...


class InMemoryTaskLoader:
    """In-memory task loader for testing."""

    def __init__(self):
        self._tasks: dict[str, TaskConfig] = {}

    def register(self, task: TaskConfig) -> None:
        """Register a task."""
        self._tasks[task.task_id] = task

    def load(self, task_id: str) -> TaskConfig:
        if task_id not in self._tasks:
            raise KeyError(f"Task not found: {task_id}")
        return self._tasks[task_id]

    def list_tasks(self) -> tuple[str, ...]:
        return tuple(self._tasks.keys())

    def list_domains(self) -> tuple[str, ...]:
        domains = {t.domain for t in self._tasks.values()}
        return tuple(sorted(domains))


def create_mock_task_loader() -> InMemoryTaskLoader:
    """Create a mock task loader with sample tasks."""
    loader = InMemoryTaskLoader()

    # Simple echo task
    loader.register(
        TaskConfig(
            task_id="echo_task",
            domain="mock",
            system_prompt="You are a helpful assistant with access to an echo tool.",
            user_instruction=UserInstruction(
                goal="Use the echo tool to repeat 'Hello, World!'",
                context="Testing the echo functionality.",
            ),
            initial_db={},
            available_tools=("echo",),
            max_steps=10,
        )
    )

    # Data retrieval task
    loader.register(
        TaskConfig(
            task_id="get_data_task",
            domain="mock",
            system_prompt="You are a helpful assistant that can get and set data.",
            user_instruction=UserInstruction(
                goal="Retrieve the value stored under 'greeting'",
                context="There should be a greeting stored in the system.",
            ),
            initial_db={"greeting": "Hello from the database!"},
            available_tools=("get_data", "set_data"),
            max_steps=10,
        )
    )

    # Data modification task
    loader.register(
        TaskConfig(
            task_id="set_data_task",
            domain="mock",
            system_prompt="You are a helpful assistant that can get and set data.",
            user_instruction=UserInstruction(
                goal="Store the value 'Task completed!' under the key 'status'",
                context="You need to update the system status.",
            ),
            initial_db={},
            available_tools=("get_data", "set_data"),
            max_steps=10,
        )
    )

    # Multi-step task
    loader.register(
        TaskConfig(
            task_id="multi_step_task",
            domain="mock",
            system_prompt="You are a helpful assistant that can get and set data.",
            user_instruction=UserInstruction(
                goal="Read the current count, increment it by 1, and save the new value",
                context="The count starts at 5.",
                constraints=("You must read before writing", "Confirm the new value"),
            ),
            initial_db={"count": 5},
            available_tools=("get_data", "set_data"),
            max_steps=15,
        )
    )

    return loader


def load_tasks_from_dict(data: dict) -> InMemoryTaskLoader:
    """
    Load tasks from a dictionary (e.g., parsed from JSON).

    Expected format:
    {
        "tasks": [
            {
                "task_id": "...",
                "domain": "...",
                "system_prompt": "...",
                "user_instruction": {
                    "goal": "...",
                    "context": "...",
                    "constraints": [...]
                },
                "initial_db": {...},
                "available_tools": [...],
                "max_steps": 50
            },
            ...
        ]
    }
    """
    loader = InMemoryTaskLoader()

    for task_data in data.get("tasks", []):
        instruction_data = task_data.get("user_instruction", {})
        instruction = UserInstruction(
            goal=instruction_data.get("goal", ""),
            context=instruction_data.get("context"),
            constraints=tuple(instruction_data.get("constraints", [])),
        )

        task = TaskConfig(
            task_id=task_data["task_id"],
            domain=task_data.get("domain", "unknown"),
            system_prompt=task_data.get("system_prompt", "You are a helpful assistant."),
            user_instruction=instruction,
            initial_db=task_data.get("initial_db", {}),
            available_tools=tuple(task_data.get("available_tools", [])),
            max_steps=task_data.get("max_steps", 50),
            max_errors=task_data.get("max_errors", 3),
            seed=task_data.get("seed"),
            extra=task_data.get("extra", {}),
        )
        loader.register(task)

    return loader
