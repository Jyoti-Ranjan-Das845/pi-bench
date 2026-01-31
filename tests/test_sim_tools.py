"""Tests for sim/tools.py - pure tool execution functions."""

import json

import pytest

from pi_bench.sim.tools import (
    crud_create,
    crud_delete,
    crud_list,
    crud_read,
    crud_update,
    execute_tool,
    read_tool,
    tool_schema,
    write_tool,
)
from pi_bench.sim.types import DBSnapshot


class TestExecuteTool:
    """Test execute_tool function."""

    def test_execute_success(self):
        def my_tool(db: DBSnapshot, args: dict) -> tuple[DBSnapshot, str]:
            return db, "success"

        db = DBSnapshot()
        new_db, result, is_error = execute_tool(my_tool, db, {})

        assert result == "success"
        assert is_error is False
        assert new_db == db

    def test_execute_with_db_change(self):
        def my_tool(db: DBSnapshot, args: dict) -> tuple[DBSnapshot, str]:
            return db.with_data({"updated": True}), "done"

        db = DBSnapshot()
        new_db, result, is_error = execute_tool(my_tool, db, {})

        assert new_db.data == {"updated": True}
        assert new_db.version == 1
        assert is_error is False

    def test_execute_error_handling(self):
        def my_tool(db: DBSnapshot, args: dict) -> tuple[DBSnapshot, str]:
            raise ValueError("Something went wrong")

        db = DBSnapshot()
        new_db, result, is_error = execute_tool(my_tool, db, {})

        assert is_error is True
        assert "ValueError" in result
        assert "Something went wrong" in result
        assert new_db == db  # DB unchanged on error


class TestReadTool:
    """Test read_tool factory."""

    def test_read_tool_basic(self):
        def accessor(data: dict, args: dict) -> str:
            return json.dumps({"value": data.get("key")})

        tool = read_tool(accessor)
        db = DBSnapshot(data={"key": "hello"})
        new_db, result = tool(db, {})

        assert db == new_db  # DB unchanged
        assert json.loads(result)["value"] == "hello"

    def test_read_tool_uses_args(self):
        def accessor(data: dict, args: dict) -> str:
            key = args.get("key", "default")
            return json.dumps({"key": key, "value": data.get(key)})

        tool = read_tool(accessor)
        db = DBSnapshot(data={"name": "Alice"})
        new_db, result = tool(db, {"key": "name"})

        parsed = json.loads(result)
        assert parsed["key"] == "name"
        assert parsed["value"] == "Alice"


class TestWriteTool:
    """Test write_tool factory."""

    def test_write_tool_updates_db(self):
        def mutator(data: dict, args: dict) -> tuple[dict, str]:
            new_data = {**data, "count": data.get("count", 0) + 1}
            return new_data, json.dumps({"new_count": new_data["count"]})

        tool = write_tool(mutator)
        db = DBSnapshot(data={"count": 5})
        new_db, result = tool(db, {})

        assert db.data["count"] == 5  # Original unchanged
        assert new_db.data["count"] == 6
        assert new_db.version == db.version + 1


class TestToolSchema:
    """Test tool_schema function."""

    def test_basic_schema(self):
        schema = tool_schema(
            name="echo",
            description="Echo a message",
            parameters={"message": {"type": "string", "description": "Message to echo"}},
            required=["message"],
        )

        assert schema["type"] == "function"
        assert schema["function"]["name"] == "echo"
        assert schema["function"]["description"] == "Echo a message"
        assert "message" in schema["function"]["parameters"]["properties"]
        assert schema["function"]["parameters"]["required"] == ["message"]

    def test_schema_no_required(self):
        schema = tool_schema(
            name="list_all",
            description="List everything",
            parameters={},
        )

        assert "required" not in schema["function"]["parameters"]


class TestCRUDTools:
    """Test CRUD tool factories."""

    def test_crud_list(self):
        tool = crud_list("users")
        db = DBSnapshot(data={
            "users": {
                "1": {"id": "1", "name": "Alice"},
                "2": {"id": "2", "name": "Bob"},
            }
        })
        new_db, result = tool(db, {})

        parsed = json.loads(result)
        assert parsed["count"] == 2
        assert len(parsed["items"]) == 2
        assert db == new_db

    def test_crud_list_empty(self):
        tool = crud_list("users")
        db = DBSnapshot()
        new_db, result = tool(db, {})

        parsed = json.loads(result)
        assert parsed["count"] == 0
        assert parsed["items"] == []

    def test_crud_read(self):
        tool = crud_read("users", id_field="user_id")
        db = DBSnapshot(data={
            "users": {"123": {"id": "123", "name": "Alice"}}
        })
        new_db, result = tool(db, {"user_id": "123"})

        parsed = json.loads(result)
        assert parsed["name"] == "Alice"
        assert db == new_db

    def test_crud_read_not_found(self):
        tool = crud_read("users", id_field="user_id")
        db = DBSnapshot(data={"users": {}})
        new_db, result = tool(db, {"user_id": "999"})

        parsed = json.loads(result)
        assert "error" in parsed

    def test_crud_create(self):
        tool = crud_create("users", auto_id=True)
        db = DBSnapshot(data={"users": {}})
        new_db, result = tool(db, {"name": "Alice", "email": "alice@example.com"})

        parsed = json.loads(result)
        assert "created" in parsed
        assert parsed["item"]["name"] == "Alice"
        assert new_db.data["users"][parsed["created"]]["name"] == "Alice"

    def test_crud_update(self):
        tool = crud_update("users", id_field="id")
        db = DBSnapshot(data={
            "users": {"1": {"id": "1", "name": "Alice", "email": "old@example.com"}}
        })
        new_db, result = tool(db, {"id": "1", "email": "new@example.com"})

        parsed = json.loads(result)
        assert parsed["updated"] == "1"
        assert new_db.data["users"]["1"]["email"] == "new@example.com"
        assert new_db.data["users"]["1"]["name"] == "Alice"  # Preserved

    def test_crud_update_not_found(self):
        tool = crud_update("users", id_field="id")
        db = DBSnapshot(data={"users": {}})
        new_db, result = tool(db, {"id": "999", "name": "Nobody"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert db.data == new_db.data  # Data unchanged (version may differ)

    def test_crud_delete(self):
        tool = crud_delete("users", id_field="id")
        db = DBSnapshot(data={
            "users": {
                "1": {"id": "1", "name": "Alice"},
                "2": {"id": "2", "name": "Bob"},
            }
        })
        new_db, result = tool(db, {"id": "1"})

        parsed = json.loads(result)
        assert parsed["deleted"] == "1"
        assert "1" not in new_db.data["users"]
        assert "2" in new_db.data["users"]

    def test_crud_delete_not_found(self):
        tool = crud_delete("users", id_field="id")
        db = DBSnapshot(data={"users": {}})
        new_db, result = tool(db, {"id": "999"})

        parsed = json.loads(result)
        assert "error" in parsed
        assert db.data == new_db.data  # Data unchanged (version may differ)
