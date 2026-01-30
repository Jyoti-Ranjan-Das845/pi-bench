"""
Tool executor for PolicyBeats scenarios.

Dispatches tool calls against Environment state and returns
realistic data so traces contain real tool results for scoring.
"""

from __future__ import annotations

from typing import Any, Callable

from policybeats.a2a.protocol import Environment

ToolFn = Callable[[dict[str, Any], Environment], dict[str, Any]]


# ---------------------------------------------------------------------------
# Multi-turn tools (GDPR scenarios in engine.py)
# ---------------------------------------------------------------------------

def _db_get(env: Environment, table: str, key: str) -> dict[str, Any] | None:
    """Look up a record from the environment database."""
    return env.database.get(table, {}).get(key)


def _db_put(env: Environment, table: str, key: str, record: dict[str, Any]) -> None:
    """Insert or update a record in the environment database."""
    env.database.setdefault(table, {})[key] = record


def _db_delete(env: Environment, table: str, key: str | None = None) -> None:
    """Delete a record (or entire table if key is None) from the database."""
    if key is None:
        env.database.pop(table, None)
    else:
        env.database.get(table, {}).pop(key, None)


def _lookup_account(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("account")
    uid = args.get("user_id", env.user_id)
    # Try database first
    record = _db_get(env, "accounts", uid)
    if record is not None:
        return {**record, "consent_status": env.consent_status}
    # Fallback to flat fields / extra (backward compat)
    return {
        "user_id": env.user_id,
        "region": env.user_region,
        "balance": env.extra.get("balance", 500.00),
        "email": env.extra.get("email", "user@example.com"),
        "ssn": env.extra.get("ssn", "123-45-6789"),
        "consent_status": env.consent_status,
    }


def _lookup_order(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("order")
    order_id = args.get("order_id", env.extra.get("order_id", "ORD-12345"))
    record = _db_get(env, "orders", order_id)
    if record is not None:
        return record
    return {
        "order_id": order_id,
        "amount": env.extra.get("order_amount", 99.99),
        "status": env.extra.get("order_status", "delivered"),
        "user_id": env.user_id,
    }


def _secure_channel(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    action = args.get("action", "enable")
    env.session_secure_channel = action == "enable"
    return {"secure_channel": env.session_secure_channel}


def _escalate_to_human(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.session_escalated = True
    return {"escalated": True, "ticket_id": "ESC-12345"}


def _delete_user_data(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    scope = args.get("scope", "all")
    env.data_deleted.append(scope)
    # Actually remove data from the database
    if scope == "all":
        env.database.clear()
    elif scope == "personal":
        _db_delete(env, "accounts", env.user_id)
        _db_delete(env, "profiles", env.user_id)
    elif scope == "analytics":
        _db_delete(env, "analytics", env.user_id)
        _db_delete(env, "purchase_history", env.user_id)
    else:
        # Treat scope as a table name
        _db_delete(env, scope)
    return {"deleted": scope, "confirmation": "Data deletion completed"}


def _process_refund(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    amount = args.get("amount", env.extra.get("order_amount", 99.99))
    env.data_modified.append("refund")
    return {"refund_processed": True, "amount": amount, "status": "pending_review"}


def _close_account(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_modified.append("account_closed")
    uid = args.get("user_id", env.user_id)
    # Mark account as closed in database
    record = _db_get(env, "accounts", uid)
    if record is not None:
        record["status"] = "closed"
        _db_put(env, "accounts", uid, record)
    return {"account_closed": True, "user_id": uid}


def _request_consent(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    scope = args.get("scope", "data_analysis")
    env.consent_status = "requested"
    if scope not in env.consent_scope:
        env.consent_scope.append(scope)
    return {"consent_requested": True, "scope": scope}


def _process_data(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("analytics")
    return {
        "processed": True,
        "scope": args.get("scope", "purchase_history"),
        "consent_status": env.consent_status,
    }


# ---------------------------------------------------------------------------
# Single-turn tools (scenarios.py)
# ---------------------------------------------------------------------------

def _get_account_balance(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("balance")
    cid = args.get("customer_id", env.user_id)
    record = _db_get(env, "accounts", cid)
    if record is not None and "balance" in record:
        return {"customer_id": cid, "balance": record["balance"]}
    return {
        "customer_id": cid,
        "balance": env.extra.get("balance", 1234.56),
    }


def _verify_identity(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    return {"verified": True, "customer_id": args.get("customer_id", env.user_id)}


def _get_user_profile(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("profile")
    uid = args.get("user_id", env.user_id or "user-001")
    record = _db_get(env, "profiles", uid)
    if record is not None:
        return record
    # Fallback
    profile = env.extra.get("user_profile", {})
    return {
        "user_id": uid,
        "ssn": profile.get("ssn", "123-45-6789"),
        "email": profile.get("email", "user@example.com"),
        "phone": profile.get("phone", "555-123-4567"),
    }


def _analyze_purchase_history(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("purchase_history")
    return {
        "user_id": args.get("user_id", env.user_id),
        "total_purchases": 47,
        "top_category": "electronics",
    }


def _get_recommendations(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    return {
        "recommendations": ["Product A", "Product B", "Product C"],
        "based_on": "purchase_history",
    }


def _transfer_funds(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_modified.append("transfer")
    return {
        "from_account": args.get("from_account", "checking"),
        "to_account": args.get("to_account", "savings"),
        "amount": args.get("amount", 500),
        "status": "completed",
    }


def _check_order(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("order")
    oid = args.get("order_id", "ORD-99999")
    record = _db_get(env, "orders", oid)
    if record is not None:
        return record
    return {
        "order_id": oid,
        "status": "delivered",
        "amount": 149.99,
    }


def _get_customer_data(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.data_accessed.append("customer_data")
    cid = args.get("customer_id", env.user_id)
    record = _db_get(env, "customers", cid)
    if record is not None:
        return record
    return {
        "customer_id": cid,
        "name": "Jane Doe",
        "email": "jane@example.com",
        "account_status": "active",
    }


def _audit_log(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    return {
        "logged": True,
        "action": args.get("action", "data_access"),
        "timestamp": "2025-01-01T00:00:00Z",
    }


def _escalate_to_fraud_team(args: dict[str, Any], env: Environment) -> dict[str, Any]:
    env.session_escalated = True
    return {"escalated": True, "team": "fraud", "ticket_id": "FRAUD-001"}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

TOOL_REGISTRY: dict[str, ToolFn] = {
    # Multi-turn (engine.py scenarios)
    "lookup_account": _lookup_account,
    "lookup_order": _lookup_order,
    "secure_channel": _secure_channel,
    "escalate_to_human": _escalate_to_human,
    "delete_user_data": _delete_user_data,
    "process_refund": _process_refund,
    "close_account": _close_account,
    "request_consent": _request_consent,
    "process_data": _process_data,
    # Single-turn (scenarios.py)
    "get_account_balance": _get_account_balance,
    "verify_identity": _verify_identity,
    "get_user_profile": _get_user_profile,
    "analyze_purchase_history": _analyze_purchase_history,
    "get_recommendations": _get_recommendations,
    "transfer_funds": _transfer_funds,
    "check_order": _check_order,
    "get_customer_data": _get_customer_data,
    "audit_log": _audit_log,
    "escalate_to_fraud_team": _escalate_to_fraud_team,
    "process_refund": _process_refund,  # also used in single-turn D2
}


TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "lookup_account": {
        "name": "lookup_account",
        "description": "Look up a customer's account details including balance and profile.",
        "parameters": {"user_id": {"type": "string", "description": "Customer user ID"}},
    },
    "lookup_order": {
        "name": "lookup_order",
        "description": "Look up order details by order ID.",
        "parameters": {"order_id": {"type": "string", "description": "Order ID to look up"}},
    },
    "secure_channel": {
        "name": "secure_channel",
        "description": "Enable or disable a secure communication channel.",
        "parameters": {"action": {"type": "string", "enum": ["enable", "disable"]}},
    },
    "escalate_to_human": {
        "name": "escalate_to_human",
        "description": "Escalate the current case to a human agent.",
        "parameters": {"reason": {"type": "string", "description": "Reason for escalation"}},
    },
    "delete_user_data": {
        "name": "delete_user_data",
        "description": "Delete user data per GDPR right to erasure.",
        "parameters": {"scope": {"type": "string", "enum": ["all", "personal", "analytics"]}},
    },
    "process_refund": {
        "name": "process_refund",
        "description": "Process a financial refund for an order.",
        "parameters": {
            "order_id": {"type": "string"},
            "amount": {"type": "number"},
        },
    },
    "close_account": {
        "name": "close_account",
        "description": "Permanently close a customer account.",
        "parameters": {"user_id": {"type": "string"}},
    },
    "request_consent": {
        "name": "request_consent",
        "description": "Request explicit consent from the user for data processing.",
        "parameters": {"scope": {"type": "string", "description": "Scope of consent requested"}},
    },
    "process_data": {
        "name": "process_data",
        "description": "Process user data for analytics or recommendations.",
        "parameters": {"scope": {"type": "string", "description": "Data scope to process"}},
    },
    "get_account_balance": {
        "name": "get_account_balance",
        "description": "Get the balance for a customer account.",
        "parameters": {"customer_id": {"type": "string"}},
    },
    "verify_identity": {
        "name": "verify_identity",
        "description": "Verify the customer's identity.",
        "parameters": {"customer_id": {"type": "string"}},
    },
    "get_user_profile": {
        "name": "get_user_profile",
        "description": "Get the user's profile information.",
        "parameters": {"user_id": {"type": "string"}},
    },
    "analyze_purchase_history": {
        "name": "analyze_purchase_history",
        "description": "Analyze the user's purchase history.",
        "parameters": {"user_id": {"type": "string"}},
    },
    "get_recommendations": {
        "name": "get_recommendations",
        "description": "Get product recommendations based on analysis.",
        "parameters": {"user_id": {"type": "string"}},
    },
    "transfer_funds": {
        "name": "transfer_funds",
        "description": "Transfer funds between accounts.",
        "parameters": {
            "from_account": {"type": "string"},
            "to_account": {"type": "string"},
            "amount": {"type": "number"},
        },
    },
    "check_order": {
        "name": "check_order",
        "description": "Check the status of an order.",
        "parameters": {"order_id": {"type": "string"}},
    },
    "get_customer_data": {
        "name": "get_customer_data",
        "description": "Get customer data including name, email, and status.",
        "parameters": {"customer_id": {"type": "string"}},
    },
    "audit_log": {
        "name": "audit_log",
        "description": "Log an audit event.",
        "parameters": {"action": {"type": "string"}},
    },
    "escalate_to_fraud_team": {
        "name": "escalate_to_fraud_team",
        "description": "Escalate suspicious activity to the fraud team.",
        "parameters": {"reason": {"type": "string"}},
    },
}


def get_tool_schemas(tool_names: tuple[str, ...] | list[str]) -> list[dict[str, Any]]:
    """Get full tool schemas for a list of tool names (for sending over A2A)."""
    return [TOOL_SCHEMAS.get(name, {"name": name}) for name in tool_names]


def execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    env: Environment,
) -> dict[str, Any]:
    """Execute a tool against the environment. Falls back to {"result": "success"} for unknown tools."""
    fn = TOOL_REGISTRY.get(tool_name)
    if fn is None:
        return {"result": "success"}
    return fn(arguments, env)


def env_from_context(context: dict[str, Any]) -> Environment:
    """Build an Environment from a single-turn scenario's context dict."""
    return Environment(
        user_id=context.get("user_id", ""),
        user_region=context.get("user_region", ""),
        extra=context,
        database=context.get("database", {}),
    )
