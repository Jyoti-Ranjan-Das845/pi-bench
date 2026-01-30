"""
Mock domain - simple domain for testing.

Provides basic CRUD operations on a mock database
for testing the simulation framework.
"""

from __future__ import annotations

import json
from typing import Any

from policybeats.sim.tools import ToolFn, tool_schema
from policybeats.sim.types import DBSnapshot


class MockDomainRegistry:
    """
    Mock domain tool registry.

    Provides a simple set of tools for testing:
    - echo: Echo a message back
    - list_users: List all users
    - get_user: Get user by ID
    - create_user: Create a new user
    - update_user: Update user details
    - list_tasks: List all tasks
    - create_task: Create a new task
    - complete_task: Mark a task as complete
    """

    def __init__(self):
        self._tools: dict[str, ToolFn] = {}
        self._schemas: dict[str, dict[str, Any]] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        """Register all mock domain tools."""
        # Echo tool
        self._register("echo", _echo_tool, _echo_schema())

        # User tools
        self._register("list_users", _list_users_tool, _list_users_schema())
        self._register("get_user", _get_user_tool, _get_user_schema())
        self._register("create_user", _create_user_tool, _create_user_schema())
        self._register("update_user", _update_user_tool, _update_user_schema())

        # Task tools
        self._register("list_tasks", _list_tasks_tool, _list_tasks_schema())
        self._register("create_task", _create_task_tool, _create_task_schema())
        self._register("complete_task", _complete_task_tool, _complete_task_schema())

        # Data tools
        self._register("get_data", _get_data_tool, _get_data_schema())
        self._register("set_data", _set_data_tool, _set_data_schema())

    def _register(
        self,
        name: str,
        tool: ToolFn,
        schema: dict[str, Any],
    ) -> None:
        """Register a tool with its schema."""
        self._tools[name] = tool
        self._schemas[name] = schema

    def get_tool(self, name: str) -> ToolFn | None:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> tuple[str, ...]:
        """List all tool names."""
        return tuple(self._tools.keys())

    def get_schemas(self) -> tuple[dict[str, Any], ...]:
        """Get all tool schemas."""
        return tuple(self._schemas.values())

    def get_schema(self, name: str) -> dict[str, Any] | None:
        """Get schema for a specific tool."""
        return self._schemas.get(name)


# === Echo Tool ===


def _echo_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Echo a message back."""
    message = args.get("message", "")
    return db, f"Echo: {message}"


def _echo_schema() -> dict[str, Any]:
    return tool_schema(
        name="echo",
        description="Echo a message back to the user.",
        parameters={
            "message": {"type": "string", "description": "The message to echo"},
        },
        required=["message"],
    )


# === User Tools ===


def _list_users_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """List all users."""
    users = db.data.get("users", {})
    user_list = list(users.values())
    return db, json.dumps({"users": user_list, "count": len(user_list)})


def _list_users_schema() -> dict[str, Any]:
    return tool_schema(
        name="list_users",
        description="List all users in the system.",
        parameters={},
    )


def _get_user_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Get user by ID."""
    user_id = args.get("user_id")
    if not user_id:
        return db, json.dumps({"error": "user_id is required"})

    users = db.data.get("users", {})
    user = users.get(str(user_id))

    if not user:
        return db, json.dumps({"error": f"User {user_id} not found"})

    return db, json.dumps(user)


def _get_user_schema() -> dict[str, Any]:
    return tool_schema(
        name="get_user",
        description="Get a user by their ID.",
        parameters={
            "user_id": {"type": "string", "description": "The user's ID"},
        },
        required=["user_id"],
    )


def _create_user_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Create a new user."""
    name = args.get("name")
    email = args.get("email")

    if not name:
        return db, json.dumps({"error": "name is required"})

    users = db.data.get("users", {})
    user_id = f"user_{len(users) + 1}"

    new_user = {
        "id": user_id,
        "name": name,
        "email": email,
        "created": True,
    }

    new_users = {**users, user_id: new_user}
    new_data = {**db.data, "users": new_users}

    return db.with_data(new_data), json.dumps({"created": user_id, "user": new_user})


def _create_user_schema() -> dict[str, Any]:
    return tool_schema(
        name="create_user",
        description="Create a new user.",
        parameters={
            "name": {"type": "string", "description": "The user's name"},
            "email": {"type": "string", "description": "The user's email (optional)"},
        },
        required=["name"],
    )


def _update_user_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Update user details."""
    user_id = args.get("user_id")
    if not user_id:
        return db, json.dumps({"error": "user_id is required"})

    users = db.data.get("users", {})
    user = users.get(str(user_id))

    if not user:
        return db, json.dumps({"error": f"User {user_id} not found"})

    # Update fields
    updated_user = {**user}
    if "name" in args:
        updated_user["name"] = args["name"]
    if "email" in args:
        updated_user["email"] = args["email"]

    new_users = {**users, str(user_id): updated_user}
    new_data = {**db.data, "users": new_users}

    return db.with_data(new_data), json.dumps({"updated": user_id, "user": updated_user})


def _update_user_schema() -> dict[str, Any]:
    return tool_schema(
        name="update_user",
        description="Update a user's details.",
        parameters={
            "user_id": {"type": "string", "description": "The user's ID"},
            "name": {"type": "string", "description": "New name (optional)"},
            "email": {"type": "string", "description": "New email (optional)"},
        },
        required=["user_id"],
    )


# === Task Tools ===


def _list_tasks_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """List all tasks."""
    tasks = db.data.get("tasks", {})
    task_list = list(tasks.values())
    return db, json.dumps({"tasks": task_list, "count": len(task_list)})


def _list_tasks_schema() -> dict[str, Any]:
    return tool_schema(
        name="list_tasks",
        description="List all tasks in the system.",
        parameters={},
    )


def _create_task_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Create a new task."""
    title = args.get("title")
    description = args.get("description", "")
    assignee = args.get("assignee")

    if not title:
        return db, json.dumps({"error": "title is required"})

    tasks = db.data.get("tasks", {})
    task_id = f"task_{len(tasks) + 1}"

    new_task = {
        "id": task_id,
        "title": title,
        "description": description,
        "assignee": assignee,
        "status": "pending",
    }

    new_tasks = {**tasks, task_id: new_task}
    new_data = {**db.data, "tasks": new_tasks}

    return db.with_data(new_data), json.dumps({"created": task_id, "task": new_task})


def _create_task_schema() -> dict[str, Any]:
    return tool_schema(
        name="create_task",
        description="Create a new task.",
        parameters={
            "title": {"type": "string", "description": "The task title"},
            "description": {"type": "string", "description": "Task description (optional)"},
            "assignee": {"type": "string", "description": "User ID to assign (optional)"},
        },
        required=["title"],
    )


def _complete_task_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Mark a task as complete."""
    task_id = args.get("task_id")
    if not task_id:
        return db, json.dumps({"error": "task_id is required"})

    tasks = db.data.get("tasks", {})
    task = tasks.get(str(task_id))

    if not task:
        return db, json.dumps({"error": f"Task {task_id} not found"})

    updated_task = {**task, "status": "completed"}
    new_tasks = {**tasks, str(task_id): updated_task}
    new_data = {**db.data, "tasks": new_tasks}

    return db.with_data(new_data), json.dumps({"completed": task_id, "task": updated_task})


def _complete_task_schema() -> dict[str, Any]:
    return tool_schema(
        name="complete_task",
        description="Mark a task as complete.",
        parameters={
            "task_id": {"type": "string", "description": "The task's ID"},
        },
        required=["task_id"],
    )


# === Generic Data Tools ===


def _get_data_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Get data by key."""
    key = args.get("key")
    if not key:
        return db, json.dumps({"error": "key is required"})

    value = db.data.get(key)
    if value is None:
        return db, json.dumps({"error": f"Key '{key}' not found"})

    return db, json.dumps({"key": key, "value": value})


def _get_data_schema() -> dict[str, Any]:
    return tool_schema(
        name="get_data",
        description="Get data by key from the database.",
        parameters={
            "key": {"type": "string", "description": "The key to retrieve"},
        },
        required=["key"],
    )


def _set_data_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
    """Set data by key."""
    key = args.get("key")
    value = args.get("value")

    if not key:
        return db, json.dumps({"error": "key is required"})

    new_data = {**db.data, key: value}
    return db.with_data(new_data), json.dumps({"success": True, "key": key, "value": value})


def _set_data_schema() -> dict[str, Any]:
    return tool_schema(
        name="set_data",
        description="Set data by key in the database.",
        parameters={
            "key": {"type": "string", "description": "The key to set"},
            "value": {"description": "The value to store"},
        },
        required=["key", "value"],
    )


# === Factory Function ===


def create_mock_domain() -> MockDomainRegistry:
    """Create a new mock domain registry with all tools."""
    return MockDomainRegistry()
