"""
Pure tool execution functions.

Tools are pure functions: (db, args) -> (new_db, result).
No side effects - database changes are returned as new immutable snapshots.

Tool types:
- Read tools: return result, db unchanged
- Write tools: return new db with changes
"""

from __future__ import annotations

from typing import Any, Callable, TypeAlias

from pi_bench.sim.types import DBSnapshot


# Type alias for tool functions
# (db, args) -> (new_db, result_string)
ToolFn: TypeAlias = Callable[[DBSnapshot, dict[str, Any]], tuple[DBSnapshot, str]]


# === Tool Execution ===


def execute_tool(
    tool_fn: ToolFn,
    db: DBSnapshot,
    args: dict[str, Any],
) -> tuple[DBSnapshot, str, bool]:
    """
    Execute a tool function purely.

    Returns (new_db, result_string, is_error).
    On error, db is unchanged and result contains error message.
    """
    try:
        new_db, result = tool_fn(db, args)
        return new_db, result, False
    except Exception as e:
        return db, f"Error: {type(e).__name__}: {e}", True


# === Tool Factories ===


def read_tool(
    accessor: Callable[[dict[str, Any], dict[str, Any]], str],
) -> ToolFn:
    """
    Create a read-only tool. DB is not modified.

    Args:
        accessor: (db_data, args) -> result_string

    Returns:
        ToolFn that returns unchanged db with accessor result
    """

    def tool_fn(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
        result = accessor(db.data, args)
        return db, result

    return tool_fn


def write_tool(
    mutator: Callable[[dict[str, Any], dict[str, Any]], tuple[dict[str, Any], str]],
) -> ToolFn:
    """
    Create a write tool that modifies database.

    Args:
        mutator: (db_data, args) -> (new_db_data, result_string)

    Returns:
        ToolFn that returns new db with mutator changes
    """

    def tool_fn(db: DBSnapshot, args: dict[str, Any]) -> tuple[DBSnapshot, str]:
        new_data, result = mutator(db.data, args)
        return db.with_data(new_data), result

    return tool_fn


# === Tool Schema ===


def tool_schema(
    name: str,
    description: str,
    parameters: dict[str, Any],
    required: list[str] | None = None,
) -> dict[str, Any]:
    """
    Create OpenAI-compatible tool schema.

    Returns dict suitable for LLM API tools parameter.
    """
    param_schema: dict[str, Any] = {
        "type": "object",
        "properties": parameters,
    }
    if required:
        param_schema["required"] = required

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": param_schema,
        },
    }


# === Validation Helpers ===


def validate_args(
    args: dict[str, Any],
    required: list[str],
) -> tuple[bool, str | None]:
    """
    Validate tool arguments. Pure.

    Returns (is_valid, error_message).
    """
    missing = [k for k in required if k not in args]
    if missing:
        return False, f"Missing required arguments: {', '.join(missing)}"
    return True, None


def get_arg(
    args: dict[str, Any],
    key: str,
    default: Any = None,
    expected_type: type | None = None,
) -> tuple[Any, str | None]:
    """
    Get and validate a single argument. Pure.

    Returns (value, error_message).
    """
    if key not in args:
        if default is not None:
            return default, None
        return None, f"Missing required argument: {key}"

    value = args[key]

    if expected_type is not None and not isinstance(value, expected_type):
        return None, f"Argument '{key}' must be {expected_type.__name__}, got {type(value).__name__}"

    return value, None


# === Common Tool Patterns ===


def crud_read(
    collection: str,
    id_field: str = "id",
) -> ToolFn:
    """
    Create a CRUD read tool for a collection.

    Reads a single item by ID from db.data[collection][id].
    """
    import json

    def accessor(data: dict[str, Any], args: dict[str, Any]) -> str:
        item_id = args.get(id_field)
        if not item_id:
            return json.dumps({"error": f"Missing {id_field}"})

        collection_data = data.get(collection, {})
        item = collection_data.get(str(item_id))

        if item is None:
            return json.dumps({"error": f"Item {item_id} not found"})

        return json.dumps(item)

    return read_tool(accessor)


def crud_list(collection: str) -> ToolFn:
    """
    Create a CRUD list tool for a collection.

    Lists all items in db.data[collection].
    """
    import json

    def accessor(data: dict[str, Any], args: dict[str, Any]) -> str:
        collection_data = data.get(collection, {})
        items = list(collection_data.values())
        return json.dumps({"items": items, "count": len(items)})

    return read_tool(accessor)


def crud_create(
    collection: str,
    id_field: str = "id",
    auto_id: bool = True,
) -> ToolFn:
    """
    Create a CRUD create tool for a collection.

    Creates new item in db.data[collection].
    """
    import json

    def mutator(
        data: dict[str, Any], args: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        new_data = {**data}
        collection_data = {**new_data.get(collection, {})}

        # Generate or get ID
        if auto_id:
            item_id = f"{collection}_{len(collection_data) + 1}"
        else:
            item_id = args.get(id_field)
            if not item_id:
                return data, json.dumps({"error": f"Missing {id_field}"})

        # Create item from args
        item = {**args, id_field: item_id}
        collection_data[str(item_id)] = item
        new_data[collection] = collection_data

        return new_data, json.dumps({"created": item_id, "item": item})

    return write_tool(mutator)


def crud_update(
    collection: str,
    id_field: str = "id",
) -> ToolFn:
    """
    Create a CRUD update tool for a collection.

    Updates existing item in db.data[collection].
    """
    import json

    def mutator(
        data: dict[str, Any], args: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        item_id = args.get(id_field)
        if not item_id:
            return data, json.dumps({"error": f"Missing {id_field}"})

        collection_data = data.get(collection, {})
        if str(item_id) not in collection_data:
            return data, json.dumps({"error": f"Item {item_id} not found"})

        # Update
        new_data = {**data}
        new_collection = {**collection_data}
        existing = new_collection[str(item_id)]
        updated = {**existing, **args}
        new_collection[str(item_id)] = updated
        new_data[collection] = new_collection

        return new_data, json.dumps({"updated": item_id, "item": updated})

    return write_tool(mutator)


def crud_delete(
    collection: str,
    id_field: str = "id",
) -> ToolFn:
    """
    Create a CRUD delete tool for a collection.

    Deletes item from db.data[collection].
    """
    import json

    def mutator(
        data: dict[str, Any], args: dict[str, Any]
    ) -> tuple[dict[str, Any], str]:
        item_id = args.get(id_field)
        if not item_id:
            return data, json.dumps({"error": f"Missing {id_field}"})

        collection_data = data.get(collection, {})
        if str(item_id) not in collection_data:
            return data, json.dumps({"error": f"Item {item_id} not found"})

        # Delete
        new_data = {**data}
        new_collection = {**collection_data}
        del new_collection[str(item_id)]
        new_data[collection] = new_collection

        return new_data, json.dumps({"deleted": item_id})

    return write_tool(mutator)
