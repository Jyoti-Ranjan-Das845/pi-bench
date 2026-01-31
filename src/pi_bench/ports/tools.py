"""
Tool Registry Port - abstract interface for tool management.

Implementations provide actual tool functions for different domains.
"""

from __future__ import annotations

from typing import Any, Protocol

from pi_bench.sim.tools import ToolFn


class ToolRegistryPort(Protocol):
    """
    Protocol for tool registry.

    Implementations provide domain-specific tools.
    """

    def get_tool(self, name: str) -> ToolFn | None:
        """
        Get a tool function by name.

        Args:
            name: Tool name

        Returns:
            ToolFn if found, None otherwise
        """
        ...

    def list_tools(self) -> tuple[str, ...]:
        """
        List all available tool names.

        Returns:
            Tuple of tool names
        """
        ...

    def get_schemas(self) -> tuple[dict[str, Any], ...]:
        """
        Get OpenAI-compatible tool schemas for all tools.

        Returns:
            Tuple of tool schema dicts
        """
        ...


class MockToolRegistry:
    """Mock tool registry for testing."""

    def __init__(self):
        self._tools: dict[str, ToolFn] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        tool: ToolFn,
        schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool."""
        self._tools[name] = tool
        if schema:
            self._schemas[name] = schema

    def get_tool(self, name: str) -> ToolFn | None:
        return self._tools.get(name)

    def list_tools(self) -> tuple[str, ...]:
        return tuple(self._tools.keys())

    def get_schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(self._schemas.values())


def create_mock_registry() -> MockToolRegistry:
    """Create a mock registry with basic CRUD tools for testing."""
    import json
    from pi_bench.sim.tools import tool_schema
    from pi_bench.sim.types import DBSnapshot

    registry = MockToolRegistry()

    # Echo tool - returns what you send
    def echo_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
        message = args.get("message", "")
        return db, f"Echo: {message}"

    registry.register(
        "echo",
        echo_tool,
        tool_schema(
            name="echo",
            description="Echo back a message",
            parameters={"message": {"type": "string", "description": "Message to echo"}},
            required=["message"],
        ),
    )

    # Get data tool - reads from db
    def get_data_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
        key = args.get("key", "")
        value = db.data.get(key, None)
        if value is None:
            return db, json.dumps({"error": f"Key '{key}' not found"})
        return db, json.dumps({"key": key, "value": value})

    registry.register(
        "get_data",
        get_data_tool,
        tool_schema(
            name="get_data",
            description="Get data by key",
            parameters={"key": {"type": "string", "description": "Key to retrieve"}},
            required=["key"],
        ),
    )

    # Set data tool - writes to db
    def set_data_tool(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
        key = args.get("key", "")
        value = args.get("value")
        if not key:
            return db, json.dumps({"error": "Key required"})
        new_data = {**db.data, key: value}
        return db.with_data(new_data), json.dumps({"success": True, "key": key})

    registry.register(
        "set_data",
        set_data_tool,
        tool_schema(
            name="set_data",
            description="Set data by key",
            parameters={
                "key": {"type": "string", "description": "Key to set"},
                "value": {"type": "string", "description": "Value to store"},
            },
            required=["key", "value"],
        ),
    )

    return registry
