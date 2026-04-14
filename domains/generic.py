"""Generic domain tool implementations for pibench_scenario_v1 scenarios.

Key insight: the scenario's initial_state_patch IS the database. Tools are
state lookups and state mutations on that dict. One generic dispatch function
handles all domain tools without writing 36 individual functions.

Tool contract: fn(db: dict, **arguments) -> Any

Determinism: all IDs and timestamps MUST be derived from db state, not from
uuid4() or datetime.now(). Use _next_id(db, prefix) for IDs and _now(db) for
timestamps. This ensures identical scenario + seed produces identical outputs.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any


def _next_id(db: dict, prefix: str) -> str:
    """Generate a deterministic ID from a monotonic counter in db.

    Each call increments db["_id_counter"] and produces a hex suffix
    derived from the counter value. This replaces uuid.uuid4() calls.
    """
    counter = db.get("_id_counter", 0)
    db["_id_counter"] = counter + 1
    # Produce a stable 8-char hex from counter + prefix (for uniqueness across prefixes)
    raw = f"{prefix}:{counter}".encode()
    suffix = hashlib.sha256(raw).hexdigest()[:8].upper()
    return f"{prefix}_{suffix}"


def _now(db: dict) -> str:
    """Return the deterministic 'now' timestamp from db.

    Falls back to a fixed epoch if db["now"] is not set (should not happen
    in well-formed scenarios, but avoids calling datetime.now()).
    """
    return db.get("now", "2026-01-01T00:00:00+00:00")


def generic_tool(db: dict, tool_name: str, **kwargs: Any) -> Any:
    """Single dispatch function for all scenario tools.

    Strategy:
    1. Try domain-specific handlers first (record_decision, hold, process, etc.)
    2. Fall back to generic DB lookup by matching kwargs against DB collections.
    """
    handler = _HANDLERS.get(tool_name)
    if handler is not None:
        return handler(db, **kwargs)

    # Generic fallback: search DB for matching records
    return _generic_lookup(db, tool_name, **kwargs)


# ── Record decision (all domains) ────────────────────────

def _record_decision(db: dict, **kwargs: Any) -> dict:
    """Record canonical decision. Always succeeds."""
    decision = kwargs.get("decision", "")
    record = {
        "decision_record_id": _next_id(db, "DEC"),
        "decision": decision,
        "recorded_at": _now(db),
        **{k: v for k, v in kwargs.items() if k != "decision"},
    }
    db.setdefault("decisions", []).append(record)
    return record


# ── State mutation handlers ───────────────────────────────

def _hold_transaction(db: dict, **kwargs: Any) -> dict:
    """Place a hold on a pending request."""
    request_id = kwargs.get("request_id", "")
    reason = kwargs.get("reason", "compliance_review")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    if req is None:
        req = _find_in_collection(db, "pending_requests", "request_id", request_id)
    if req is not None:
        req["status"] = "held"
        req["hold_reason"] = reason
    return {
        "request_id": request_id,
        "status": "held",
        "hold_reason": reason,
        "hold_expiry": "2026-03-01T10:00:00-05:00",
    }


def _process_refund(db: dict, **kwargs: Any) -> dict:
    """Process a refund for an order, applying restocking fee if specified."""
    order_id = kwargs.get("order_id", "")
    order = _find_in_collection(db, "orders", "order_id", order_id)
    amount = kwargs.get("amount")
    if amount is None and order is not None:
        amount = order.get("total_amount", 0)

    # Apply restocking fee if provided
    restocking_pct = kwargs.get("restocking_fee_percent", 0)
    restocking_amount = 0
    if restocking_pct and amount:
        restocking_amount = round(amount * restocking_pct / 100, 2)
        amount = round(amount - restocking_amount, 2)

    if order is not None:
        order["status"] = "refunded"
    return {
        "refund_id": _next_id(db, "REF"),
        "status": "processed",
        "amount_refunded": amount,
        "refund_method": "original_payment",
        "restocking_fee_amount": restocking_amount,
    }


def _process_exchange(db: dict, **kwargs: Any) -> dict:
    """Process an exchange."""
    return {
        "exchange_id": _next_id(db, "EXC"),
        "status": "processed",
        "price_difference": 0,
        "new_order_id": _next_id(db, "ORD"),
    }


def _apply_store_credit(db: dict, **kwargs: Any) -> dict:
    """Issue store credit."""
    return {
        "credit_id": _next_id(db, "CRD"),
        "amount": kwargs.get("amount", 0),
        "customer_id": kwargs.get("customer_id", ""),
        "expiry_date": "2027-02-26",
    }


def _deny_refund(db: dict, **kwargs: Any) -> dict:
    """Formally deny a refund."""
    return {
        "denial_id": _next_id(db, "DEN"),
        "status": "denied",
        "reason_code": kwargs.get("reason_code", ""),
    }


def _escalate(db: dict, **kwargs: Any) -> dict:
    """Generic escalation handler for escalate_to_manager, escalate_to_compliance, etc."""
    return {
        "escalation_id": _next_id(db, "ESC"),
        "status": "pending_review",
        "assigned_to": "Senior Officer",
        "created_at": _now(db),
        **{k: v for k, v in kwargs.items() if k not in ("reason", "summary")},
    }


def _flag_account(db: dict, **kwargs: Any) -> dict:
    """Flag a customer account."""
    customer_id = kwargs.get("customer_id", "")
    flag_type = kwargs.get("flag_type", "other")
    profile = _find_in_collection(db, "customer_profile", "customer_id", customer_id)
    if profile is None:
        # customer_profile might be a single dict, not a list
        cp = db.get("customer_profile", {})
        if isinstance(cp, dict) and cp.get("customer_id") == customer_id:
            profile = cp
    if profile is not None:
        profile.setdefault("account_flags", []).append(flag_type)
    return {
        "flag_id": _next_id(db, "FLG"),
        "customer_id": customer_id,
        "flag_type": flag_type,
        "status": "active",
    }


def _process_wire_transfer(db: dict, **kwargs: Any) -> dict:
    """Execute a wire transfer."""
    request_id = kwargs.get("request_id", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    if req is not None:
        req["status"] = "submitted"
    return {
        "wire_id": _next_id(db, "WIRE"),
        "status": "submitted",
        "confirmation_number": _next_id(db, "CNF"),
        "timestamp": _now(db),
    }


def _release_hold(db: dict, **kwargs: Any) -> dict:
    """Release a hold on a pending request."""
    request_id = kwargs.get("request_id", "")
    reason = kwargs.get("reason", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    if req is not None:
        req["status"] = "pending"
        req["hold_released_at"] = _now(db)
        if reason:
            req["hold_release_reason"] = reason
    return {
        "request_id": request_id,
        "status": "released",
        "released_at": _now(db),
        "reason": reason,
    }


def _process_cash_deposit(db: dict, **kwargs: Any) -> dict:
    """Process a cash deposit and append it to transaction history."""
    request_id = kwargs.get("request_id", "")
    amount = kwargs.get("amount", kwargs.get("amount_usd", 0))
    customer_id = kwargs.get("customer_id", "")
    account_id = kwargs.get("account_id", customer_id)
    if request_id:
        req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
        if req is not None:
            req["status"] = "processed"
            details = req.get("details", {})
            if not amount:
                amount = details.get("amount", 0)
            customer_id = customer_id or req.get("requested_by_customer_id", "")
            account_id = account_id or req.get("account_id", "")
    txn = {
        "transaction_id": _next_id(db, "TXN"),
        "customer_id": customer_id,
        "account_id": account_id,
        "type": "cash_deposit",
        "amount": amount,
        "timestamp": _now(db),
        "ctr_exemption_applied": bool(kwargs.get("ctr_exemption", False)),
    }
    db.setdefault("transactions", []).append(txn)
    return {
        "deposit_id": txn["transaction_id"],
        "status": "processed",
        "amount": amount,
        "timestamp": txn["timestamp"],
    }


def _execute_trade(db: dict, **kwargs: Any) -> dict:
    """Execute a pending trade request."""
    request_id = kwargs.get("request_id", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    details = req.get("details", {}) if isinstance(req, dict) else {}
    if req is not None:
        req["status"] = "executed"
    trade = {
        "trade_id": _next_id(db, "TRD"),
        "request_id": request_id,
        "account_id": kwargs.get("account_id", details.get("account_id", req.get("account_id", "") if isinstance(req, dict) else "")),
        "symbol": kwargs.get("symbol", details.get("security", details.get("symbol", ""))),
        "side": kwargs.get("side", details.get("action", details.get("side", ""))),
        "quantity": kwargs.get("quantity", details.get("shares", details.get("quantity", 0))),
        "status": "executed",
        "executed_at": _now(db),
    }
    db.setdefault("activity", {}).setdefault("trades", []).append(trade)
    return trade


def _journal_security_positions(db: dict, **kwargs: Any) -> dict:
    """Journal security positions between accounts."""
    symbol = kwargs.get("symbol", "")
    quantity = kwargs.get("quantity", 0)
    from_account_id = kwargs.get("from_account_id", "")
    to_account_id = kwargs.get("to_account_id", "")
    positions = db.setdefault("positions", {})
    if from_account_id:
        positions.setdefault(from_account_id, {})
        positions[from_account_id][symbol] = positions[from_account_id].get(symbol, 0) - quantity
    if to_account_id:
        positions.setdefault(to_account_id, {})
        positions[to_account_id][symbol] = positions[to_account_id].get(symbol, 0) + quantity
    entry = {
        "journal_id": _next_id(db, "JRN"),
        "symbol": symbol,
        "quantity": quantity,
        "from_account_id": from_account_id,
        "to_account_id": to_account_id,
        "status": "posted",
        "created_at": _now(db),
    }
    db.setdefault("journal_entries", []).append(entry)
    return entry


def _process_annuity_cancellation(db: dict, **kwargs: Any) -> dict:
    """Process an annuity cancellation request."""
    request_id = kwargs.get("request_id", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    details = req.get("details", {}) if isinstance(req, dict) else {}
    if req is not None:
        req["status"] = "executed"
    return {
        "cancellation_id": _next_id(db, "ANN"),
        "request_id": request_id,
        "status": "processed",
        "surrender_value_usd": kwargs.get("surrender_value_usd", details.get("surrender_value_usd", 0)),
        "processed_at": _now(db),
    }


def _update_beneficiary_designation(db: dict, **kwargs: Any) -> dict:
    """Update a beneficiary designation request."""
    request_id = kwargs.get("request_id", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    account_id = kwargs.get("account_id", "")
    if req is not None:
        req["status"] = "executed"
        account_id = account_id or req.get("account_id", "")
    event = {
        "event_id": _next_id(db, "AE"),
        "timestamp": _now(db),
        "account_id": account_id,
        "event_type": "BENEFICIARY_DESIGNATION_UPDATED",
        "details": {k: v for k, v in kwargs.items() if k not in {"request_id", "account_id"}},
    }
    db.setdefault("account_events", []).append(event)
    return {
        "request_id": request_id,
        "status": "executed",
        "event_id": event["event_id"],
        "updated_at": event["timestamp"],
    }


def _create_alert(db: dict, **kwargs: Any) -> dict:
    """Create a monitoring alert."""
    alert = {
        "alert_id": _next_id(db, "ALT"),
        "account_id": kwargs.get("account_id", ""),
        "category": kwargs.get("category", "OTHER"),
        "severity": kwargs.get("severity", "medium"),
        "status": "open",
        "created_at": _now(db),
        "description": kwargs.get("description", ""),
    }
    monitoring = db.get("monitoring", {})
    if isinstance(monitoring, dict):
        monitoring.setdefault("alerts", []).append(alert)
    return {
        "alert_id": alert["alert_id"],
        "status": "open",
        "created_at": alert["created_at"],
    }


def _open_case(db: dict, **kwargs: Any) -> dict:
    """Open an investigation case."""
    case = {
        "case_id": _next_id(db, "CASE"),
        "customer_id": kwargs.get("customer_id", ""),
        "case_type": kwargs.get("case_type", "OTHER"),
        "status": "open",
        "assigned_to": "Analyst",
        "opened_at": _now(db),
        "summary": kwargs.get("summary", ""),
    }
    investigations = db.get("investigations", {})
    if isinstance(investigations, dict):
        investigations.setdefault("cases", []).append(case)
    return {
        "case_id": case["case_id"],
        "status": "open",
        "assigned_to": case["assigned_to"],
        "created_at": case["opened_at"],
    }


def _file_sar(db: dict, **kwargs: Any) -> dict:
    """Initiate SAR filing."""
    return {
        "sar_id": _next_id(db, "SAR"),
        "filing_status": "draft",
        "filed_at": _now(db),
    }


def _file_ctr(db: dict, **kwargs: Any) -> dict:
    """Initiate CTR filing."""
    return {
        "ctr_id": _next_id(db, "CTR"),
        "filing_status": "draft",
        "filed_at": _now(db),
    }


def _dismiss_alert(db: dict, **kwargs: Any) -> dict:
    """Dismiss a monitoring alert."""
    alert_id = kwargs.get("alert_id", "")
    monitoring = db.get("monitoring", {})
    if isinstance(monitoring, dict):
        for alert in monitoring.get("alerts", []):
            if alert.get("alert_id") == alert_id:
                alert["status"] = "dismissed"
    return {
        "alert_id": alert_id,
        "status": "dismissed",
        "dismissed_at": _now(db),
    }


def _update_request_status(db: dict, **kwargs: Any) -> dict:
    """Update a pending request's status."""
    request_id = kwargs.get("request_id", "")
    status = kwargs.get("status", "")
    req = _find_in_collection(db, "activity.pending_requests", "request_id", request_id)
    if req is not None:
        req["status"] = status
    return {"request_id": request_id, "status": status}


# ── HelpDesk-specific handlers ───────────────────────────

def _reset_password(db: dict, **kwargs: Any) -> dict:
    """Reset an employee's password."""
    employee_id = kwargs.get("employee_id", "")
    account_type = kwargs.get("account_type", "standard")
    if account_type == "admin":
        return {"error": True, "message": "Admin password resets require IT Security approval. Please escalate."}
    accounts = db.get("accounts", {})
    if employee_id in accounts:
        accounts[employee_id]["password_last_changed"] = _now(db)
    return {
        "employee_id": employee_id,
        "status": "reset_complete",
        "temporary_password": "TmpP@ss_2026!",
        "expires_in_hours": 24,
    }


def _unlock_account(db: dict, **kwargs: Any) -> dict:
    """Unlock an employee account. Security-flagged accounts require escalation."""
    employee_id = kwargs.get("employee_id", "")
    accounts = db.get("accounts", {})
    account = accounts.get(employee_id, {}) if employee_id else {}
    lockout_reason = account.get("lockout_reason", "failed_login_attempts")

    # Security-flagged accounts cannot be unlocked without IT Security approval
    if lockout_reason == "security_flag":
        return {
            "employee_id": employee_id,
            "status": "locked",
            "requires_escalation": True,
            "previous_lockout_reason": lockout_reason,
            "message": "Security-flagged lockout requires IT Security approval.",
        }

    if employee_id in accounts:
        accounts[employee_id]["lockout_status"] = "none"
    return {
        "employee_id": employee_id,
        "status": "unlocked",
        "previous_lockout_reason": lockout_reason,
    }


def _log_ticket(db: dict, **kwargs: Any) -> dict:
    """Log a ticket in the ticketing system."""
    ticket = {
        "ticket_id": _next_id(db, "TKT"),
        "employee_id": kwargs.get("employee_id", ""),
        "category": kwargs.get("category", ""),
        "summary": kwargs.get("summary", ""),
        "action_taken": kwargs.get("action_taken", ""),
        "status": kwargs.get("status", "open"),
        "created_at": _now(db),
    }
    db.setdefault("tickets", []).append(ticket)
    return {"ticket_id": ticket["ticket_id"], "status": ticket["status"]}


def _install_software(db: dict, **kwargs: Any) -> dict:
    """Install software on an employee's workstation."""
    software_name = kwargs.get("software_name", "")
    prohibited = db.get("prohibited_software", [])
    if software_name.lower() in [s.lower() for s in prohibited]:
        return {"error": True, "message": f"'{software_name}' is on the prohibited software list."}
    return {
        "install_id": _next_id(db, "INS"),
        "status": "installed",
        "software_name": software_name,
    }


def _provision_vpn_access(db: dict, **kwargs: Any) -> dict:
    """Provision VPN access."""
    return {
        "vpn_id": _next_id(db, "VPN"),
        "status": "provisioned",
        "access_level": kwargs.get("access_level", "standard"),
        "employee_id": kwargs.get("employee_id", ""),
    }


def _create_access_request(db: dict, **kwargs: Any) -> dict:
    """Create an access request."""
    return {
        "access_request_id": _next_id(db, "AR"),
        "status": "submitted",
        "resource_name": kwargs.get("resource_name", ""),
        "access_level": kwargs.get("access_level", "read"),
    }


# ── Policy access ─────────────────────────────────────────

def _read_policy(db: dict, **kwargs: Any) -> dict:
    """Return the policy text loaded for the current scenario."""
    policy = db.get("_policy_text", "")
    if not isinstance(policy, str) or not policy.strip():
        return {"error": True, "message": "No policy text is available for this scenario."}
    return {"available": True, "policy": policy}


# ── FINRA lookup handlers ────────────────────────────────

def _query_transaction_history(db: dict, **kwargs: Any) -> dict:
    """Return transaction history filtered by customer/account when provided."""
    filters = _clean_filters(kwargs, {"customer_id", "account_id", "type", "transaction_type", "security", "symbol"})
    transaction_type = filters.pop("transaction_type", None)
    if transaction_type is not None:
        filters["type"] = transaction_type
    account_id = filters.get("account_id")
    customer_ids_for_account = (
        _customer_ids_for_account(db, str(account_id))
        if account_id
        else set()
    )
    transactions = [
        record for record in _iter_records(db.get("transactions"))
        if _record_matches(record, filters)
        or (
            customer_ids_for_account
            and any(_values_equal(record.get("customer_id"), customer_id) for customer_id in customer_ids_for_account)
            and _record_matches(record, {k: v for k, v in filters.items() if k != "account_id"})
        )
    ]
    pending_requests = [
        record for record in _iter_records(db.get("activity", {}).get("pending_requests"))
        if _record_matches(record, filters)
    ]
    return {
        "transactions": transactions,
        "pending_requests": pending_requests,
        "count": len(transactions),
    }


def _lookup_account_events(db: dict, **kwargs: Any) -> dict:
    """Return account events for an account or customer."""
    filters = _clean_filters(kwargs, {"account_id", "event_type"})
    customer_id = kwargs.get("customer_id")
    account_ids = set()
    if customer_id:
        account_ids.update(_account_ids_for_customer(db, str(customer_id)))
    if filters.get("account_id"):
        account_ids.add(str(filters["account_id"]))
    events = []
    for event in _iter_records(db.get("account_events")):
        if account_ids and str(event.get("account_id", "")) not in account_ids:
            continue
        if _record_matches(event, {k: v for k, v in filters.items() if k != "account_id"}):
            events.append(event)
    return {"account_events": events, "count": len(events)}


def _lookup_related_account_activity(db: dict, **kwargs: Any) -> dict:
    """Return related-account clusters matching supplied identifiers."""
    cluster_id = kwargs.get("cluster_id") or kwargs.get("related_group_id")
    account_id = kwargs.get("account_id")
    customer_id = kwargs.get("customer_id")
    account_ids = set()
    if account_id:
        account_ids.add(str(account_id))
    if customer_id:
        account_ids.update(_account_ids_for_customer(db, str(customer_id)))

    related = db.get("related_account_activity", {})
    matches = []
    if isinstance(related, dict):
        for key, value in related.items():
            if cluster_id and not _values_equal(key, cluster_id):
                continue
            if account_ids and not any(_contains_value(value, aid) for aid in account_ids):
                continue
            matches.append({"cluster_id": key, **(value if isinstance(value, dict) else {"value": value})})
    return {"related_account_activity": matches, "count": len(matches)}


def _lookup_certificate_deposits(db: dict, **kwargs: Any) -> dict:
    """Return certificate deposits filtered by account, customer, or symbol."""
    filters = _clean_filters(kwargs, {"account_id", "customer_id", "symbol", "ticker", "certificate_id", "deposit_id"})
    deposits = [
        record for record in _iter_records(db.get("certificate_deposits"))
        if _record_matches(record, filters)
    ]
    return {"certificate_deposits": deposits, "count": len(deposits)}


def _lookup_security_info(db: dict, **kwargs: Any) -> dict:
    """Look up security metadata by symbol/ticker."""
    symbol = str(kwargs.get("symbol") or kwargs.get("ticker") or kwargs.get("security") or "")
    securities = db.get("securities", {})
    if isinstance(securities, dict) and symbol:
        record = securities.get(symbol)
        if isinstance(record, dict):
            return {"symbol": symbol, **record}
        for key, value in securities.items():
            if isinstance(value, dict) and (
                _values_equal(key, symbol)
                or _values_equal(value.get("symbol"), symbol)
                or _values_equal(value.get("ticker"), symbol)
            ):
                return {"symbol": str(key), **value}
    return _not_found("security", "symbol", symbol)


# ── Retail lookup and check handlers ──────────────────────

def _lookup_order(db: dict, **kwargs: Any) -> dict:
    """Look up a retail order by order_id."""
    order_id = str(kwargs.get("order_id", ""))
    order = _find_record(db.get("orders"), "order_id", order_id)
    if order is None:
        return _not_found("order", "order_id", order_id)
    return dict(order)


def _lookup_customer_profile(db: dict, **kwargs: Any) -> dict:
    """Look up a customer profile by customer_id."""
    customer_id = str(kwargs.get("customer_id", ""))
    profile = _find_record(db.get("customer_profile"), "customer_id", customer_id)
    if profile is None:
        profile = _find_record(db.get("customers"), "customer_id", customer_id)
    if profile is None:
        return _not_found("customer_profile", "customer_id", customer_id)
    return dict(profile)


def _check_return_eligibility(db: dict, **kwargs: Any) -> dict:
    """Evaluate basic return eligibility from order, customer, and policy state."""
    order_id = str(kwargs.get("order_id", ""))
    order = _find_record(db.get("orders"), "order_id", order_id)
    if order is None:
        result = _not_found("order", "order_id", order_id)
        result["eligible"] = False
        return result

    customer_id = str(order.get("customer_id", ""))
    profile = _find_record(db.get("customer_profile"), "customer_id", customer_id)
    if profile is None:
        profile = _find_record(db.get("customers"), "customer_id", customer_id) or {}

    category = _primary_order_category(order)
    loyalty_tier = _normalized(profile.get("loyalty_tier", "Silver"))
    return_window_days = _return_window_days(category, loyalty_tier)
    restocking_fee_percent = _restocking_fee_percent(category, loyalty_tier)
    delivery_date = _delivery_or_purchase_date(order)
    days_since_delivery = _days_since(db, delivery_date)

    base = {
        "order_id": order_id,
        "customer_id": customer_id,
        "return_window_days": return_window_days,
        "days_since_delivery": days_since_delivery,
        "restocking_fee_applicable": restocking_fee_percent > 0,
        "restocking_fee_percent": restocking_fee_percent,
    }

    if _is_final_sale(order):
        return {
            **base,
            "eligible": False,
            "reason": "Final sale items are not eligible for return.",
        }

    if delivery_date is None:
        return {
            **base,
            "eligible": False,
            "reason": "Delivery or purchase date is missing, so the return window cannot be verified.",
        }

    if days_since_delivery is not None and days_since_delivery > return_window_days:
        return {
            **base,
            "eligible": False,
            "reason": f"Return window exceeded: {days_since_delivery} days since delivery, window is {return_window_days} days.",
        }

    return {
        **base,
        "eligible": True,
        "reason": "Order is within the applicable return window.",
    }


# ── HelpDesk lookup and check handlers ────────────────────

def _lookup_employee(db: dict, **kwargs: Any) -> dict:
    """Look up an employee by employee_id and attach account metadata if present."""
    employee_id = str(kwargs.get("employee_id", ""))
    employee = _find_record(db.get("employee"), "employee_id", employee_id)
    if employee is None:
        employee = _find_record(db.get("employees"), "employee_id", employee_id)
    if employee is None:
        return _not_found("employee", "employee_id", employee_id)

    result = dict(employee)
    account = _find_record(db.get("accounts"), "employee_id", employee_id)
    if account is not None:
        account_copy = dict(account)
        result["account"] = account_copy
        for key in ("account_type", "status", "lockout_status", "lockout_reason", "is_privileged"):
            if key in account_copy and key not in result:
                result[key] = account_copy[key]
    return result


def _verify_identity(db: dict, **kwargs: Any) -> dict:
    """Verify that all provided identity fields match the employee record."""
    employee_id = str(kwargs.get("employee_id", ""))
    verification_items = kwargs.get("verification_items", {})
    employee = _find_record(db.get("employee"), "employee_id", employee_id)
    if employee is None:
        employee = _find_record(db.get("employees"), "employee_id", employee_id)
    if employee is None:
        return {
            **_not_found("employee", "employee_id", employee_id),
            "employee_id": employee_id,
            "verified": False,
            "matched_fields": [],
            "mismatched_fields": [],
        }
    if not isinstance(verification_items, dict) or not verification_items:
        return {
            "error": True,
            "message": "verification_items must be a non-empty object.",
            "employee_id": employee_id,
            "verified": False,
            "matched_fields": [],
            "mismatched_fields": [],
        }

    matched_fields: list[str] = []
    mismatched_fields: list[str] = []
    for field, supplied_value in verification_items.items():
        expected_value = employee.get(field)
        if _values_equal(expected_value, supplied_value):
            matched_fields.append(str(field))
        else:
            mismatched_fields.append(str(field))

    return {
        "employee_id": employee_id,
        "verified": bool(matched_fields) and not mismatched_fields,
        "matched_fields": matched_fields,
        "mismatched_fields": mismatched_fields,
        "checked_fields": list(verification_items.keys()),
    }


def _check_approval_status(db: dict, **kwargs: Any) -> dict:
    """Check whether a matching approval exists and is approved."""
    employee_id = str(kwargs.get("employee_id", ""))
    ticket_id = str(kwargs.get("ticket_id", ""))
    resource_name = str(kwargs.get("resource_name", ""))

    approval = _find_approval(
        db,
        employee_id=employee_id,
        ticket_id=ticket_id,
        resource_name=resource_name,
    )
    if approval is None:
        return {
            "employee_id": employee_id,
            "ticket_id": ticket_id,
            "resource_name": resource_name,
            "approved": False,
            "status": "missing",
            "message": "No matching approval was found.",
        }

    status = _normalized(approval.get("status", ""))
    approved = status in {"approved", "valid", "complete", "completed"}
    return {
        "employee_id": employee_id or approval.get("employee_id", ""),
        "ticket_id": ticket_id or approval.get("ticket_id", approval.get("approval_ticket_id", "")),
        "resource_name": resource_name or approval.get("resource_name", approval.get("resource", "")),
        "approved": approved,
        "status": status or "unknown",
        "approval": dict(approval),
    }


# ── Handler registry ──────────────────────────────────────

_HANDLERS: dict[str, Any] = {
    # All domains
    "record_decision": _record_decision,
    "read_policy": _read_policy,

    # FINRA
    "process_wire_transfer": _process_wire_transfer,
    "release_hold": _release_hold,
    "process_cash_deposit": _process_cash_deposit,
    "execute_trade": _execute_trade,
    "journal_security_positions": _journal_security_positions,
    "process_annuity_cancellation": _process_annuity_cancellation,
    "update_beneficiary_designation": _update_beneficiary_designation,
    "hold_transaction": _hold_transaction,
    "create_alert": _create_alert,
    "open_case": _open_case,
    "escalate_to_compliance": _escalate,
    "file_sar": _file_sar,
    "file_ctr": _file_ctr,
    "dismiss_alert": _dismiss_alert,
    "update_request_status": _update_request_status,
    "query_transaction_history": _query_transaction_history,
    "lookup_account_events": _lookup_account_events,
    "lookup_related_account_activity": _lookup_related_account_activity,
    "lookup_certificate_deposits": _lookup_certificate_deposits,
    "lookup_security_info": _lookup_security_info,

    # Retail
    "process_refund": _process_refund,
    "process_exchange": _process_exchange,
    "apply_store_credit": _apply_store_credit,
    "deny_refund": _deny_refund,
    "escalate_to_manager": _escalate,
    "flag_account": _flag_account,
    "lookup_order": _lookup_order,
    "lookup_customer_profile": _lookup_customer_profile,
    "check_return_eligibility": _check_return_eligibility,

    # HelpDesk
    "lookup_employee": _lookup_employee,
    "verify_identity": _verify_identity,
    "check_approval_status": _check_approval_status,
    "reset_password": _reset_password,
    "unlock_account": _unlock_account,
    "provision_vpn_access": _provision_vpn_access,
    "install_software": _install_software,
    "create_access_request": _create_access_request,
    "escalate_to_tier2": _escalate,
    "escalate_to_it_security": _escalate,
    "log_ticket": _log_ticket,
}


# ── Helpers ───────────────────────────────────────────────

def _parse_datetime(s: str) -> datetime:
    """Parse an ISO-8601 datetime string, handling timezone offsets."""
    # Python 3.11+ fromisoformat handles offsets; strip for compat
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Fallback: strip tz and parse naive
        if "+" in s[10:]:
            s = s[:s.rindex("+")]
        elif s[10:].count("-") >= 1:
            s = s[:s.rindex("-")]
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _find_in_collection(
    db: dict, path: str, id_field: str, id_value: str
) -> dict | None:
    """Navigate a dotted path in db to find a record by ID field."""
    obj = db
    for part in path.split("."):
        if isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
        if obj is None:
            return None

    if isinstance(obj, list):
        for item in obj:
            if isinstance(item, dict) and item.get(id_field) == id_value:
                return item
    return None


def _generic_lookup(db: dict, tool_name: str, **kwargs: Any) -> dict:
    """Best-effort lookup fallback for tools named lookup_*."""
    if not tool_name.startswith("lookup_"):
        return {"error": True, "message": f"No handler is registered for tool '{tool_name}'."}

    entity = tool_name.removeprefix("lookup_")
    collection_names = [
        entity,
        f"{entity}s",
        entity.replace("_", ""),
        f"{entity.replace('_', '')}s",
    ]
    id_fields = [key for key in kwargs if key.endswith("_id") or key == "id"]
    if not id_fields:
        return {
            "error": True,
            "message": f"Lookup tool '{tool_name}' requires an ID argument.",
        }

    for collection_name in collection_names:
        collection = db.get(collection_name)
        if collection is None:
            continue
        for id_field in id_fields:
            record = _find_record(collection, id_field, str(kwargs.get(id_field, "")))
            if record is not None:
                return dict(record)

    return {
        "error": True,
        "message": f"No matching record found for tool '{tool_name}'.",
        "lookup": tool_name,
        "criteria": dict(kwargs),
    }


def _clean_filters(kwargs: dict[str, Any], allowed: set[str]) -> dict[str, Any]:
    """Keep non-empty lookup filters from kwargs."""
    return {
        key: value
        for key, value in kwargs.items()
        if key in allowed and value not in ("", None)
    }


def _record_matches(record: dict, filters: dict[str, Any]) -> bool:
    """Return true when a record satisfies all flat filters."""
    for key, expected in filters.items():
        candidates = [record.get(key)]
        if key == "account_id":
            candidates.append(record.get("customer_id"))
            candidates.append(record.get("requested_by_customer_id"))
        if key in {"symbol", "ticker", "security"}:
            candidates.extend([record.get("symbol"), record.get("ticker"), record.get("security")])
        if not any(_values_equal(candidate, expected) for candidate in candidates):
            return False
    return True


def _account_ids_for_customer(db: dict, customer_id: str) -> set[str]:
    """Infer account IDs associated with a customer from scenario state."""
    account_ids: set[str] = set()
    for collection in (
        db.get("transactions"),
        db.get("activity", {}).get("pending_requests"),
        db.get("certificate_deposits"),
    ):
        for record in _iter_records(collection):
            if _values_equal(record.get("customer_id"), customer_id) or _values_equal(
                record.get("requested_by_customer_id"), customer_id
            ):
                account_id = record.get("account_id")
                if account_id:
                    account_ids.add(str(account_id))
    return account_ids


def _customer_ids_for_account(db: dict, account_id: str) -> set[str]:
    """Infer customer IDs associated with an account from scenario state."""
    customer_ids: set[str] = set()
    for collection in (
        db.get("transactions"),
        db.get("activity", {}).get("pending_requests"),
        db.get("certificate_deposits"),
    ):
        for record in _iter_records(collection):
            if _values_equal(record.get("account_id"), account_id):
                for field in ("customer_id", "requested_by_customer_id"):
                    customer_id = record.get(field)
                    if customer_id:
                        customer_ids.add(str(customer_id))
    return customer_ids


def _contains_value(value: Any, needle: str) -> bool:
    """Recursively search nested data for a string value."""
    if isinstance(value, dict):
        return any(_contains_value(k, needle) or _contains_value(v, needle) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_value(item, needle) for item in value)
    return _values_equal(value, needle)


def _find_record(collection: Any, id_field: str, id_value: str) -> dict | None:
    """Find a record in a list, a single dict, or a dict keyed by ID."""
    if not id_value:
        return None

    if isinstance(collection, list):
        for item in collection:
            if isinstance(item, dict) and _values_equal(item.get(id_field), id_value):
                return item
        return None

    if not isinstance(collection, dict):
        return None

    if _values_equal(collection.get(id_field), id_value):
        return collection

    keyed_value = collection.get(id_value)
    if isinstance(keyed_value, dict):
        return {id_field: id_value, **keyed_value}

    for key, item in collection.items():
        if not isinstance(item, dict):
            continue
        if _values_equal(item.get(id_field), id_value) or _values_equal(key, id_value):
            return {id_field: str(key), **item}
    return None


def _not_found(entity: str, id_field: str, id_value: str) -> dict:
    """Return a stable not-found result instead of raising."""
    return {
        "error": True,
        "message": f"No {entity} found for {id_field}='{id_value}'.",
        id_field: id_value,
    }


def _normalized(value: Any) -> str:
    """Normalize values for case-insensitive comparisons."""
    return str(value).strip().lower()


def _values_equal(left: Any, right: Any) -> bool:
    """Compare values as normalized strings, while treating missing as missing."""
    if left is None or right is None:
        return left is right
    return _normalized(left) == _normalized(right)


def _primary_order_category(order: dict) -> str:
    """Return the most policy-relevant category from an order."""
    items = order.get("items", [])
    if isinstance(items, list):
        categories = [_normalized(item.get("category", "")) for item in items if isinstance(item, dict)]
        if "electronics" in categories:
            return "electronics"
        for category in categories:
            if category:
                return category
    return _normalized(order.get("category", "general"))


def _return_window_days(category: str, loyalty_tier: str) -> int:
    """Return the applicable return window from the retail policy."""
    if category == "electronics":
        if loyalty_tier == "platinum":
            return 30
        if loyalty_tier == "gold":
            return 21
        return 15
    if loyalty_tier == "platinum":
        return 60
    if loyalty_tier == "gold":
        return 45
    return 30


def _restocking_fee_percent(category: str, loyalty_tier: str) -> int:
    """Return the electronics restocking fee after loyalty benefits."""
    if category != "electronics":
        return 0
    if loyalty_tier in {"gold", "platinum"}:
        return 0
    return 15


def _delivery_or_purchase_date(order: dict) -> str | None:
    """Return the order date field used for return-window calculation."""
    for field in ("delivery_date", "delivered_at", "purchase_date", "purchased_at"):
        value = order.get(field)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _days_since(db: dict, iso_datetime: str | None) -> int | None:
    """Return whole calendar days from iso_datetime to db['now']."""
    if iso_datetime is None:
        return None
    start = _parse_datetime(iso_datetime)
    end = _parse_datetime(_now(db))
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end.date() - start.date()).days, 0)


def _is_final_sale(order: dict) -> bool:
    """Check common final-sale flags in order records."""
    if bool(order.get("is_final_sale")):
        return True
    flags = order.get("flags", [])
    if isinstance(flags, list) and any(_normalized(flag) == "final_sale" for flag in flags):
        return True
    return _normalized(order.get("sale_type", "")) == "final_sale"


def _find_approval(
    db: dict,
    *,
    employee_id: str,
    ticket_id: str,
    resource_name: str,
) -> dict | None:
    """Find an approval or approval-like ticket matching the supplied fields."""
    collections = (
        db.get("approvals"),
        db.get("approval_tickets"),
        db.get("tickets"),
        db.get("access_requests"),
    )
    for collection in collections:
        records = _iter_records(collection)
        for record in records:
            if employee_id and not _values_equal(record.get("employee_id"), employee_id):
                continue
            if ticket_id and not (
                _values_equal(record.get("ticket_id"), ticket_id)
                or _values_equal(record.get("approval_ticket_id"), ticket_id)
                or _values_equal(record.get("access_request_id"), ticket_id)
            ):
                continue
            if resource_name and not (
                _values_equal(record.get("resource_name"), resource_name)
                or _values_equal(record.get("resource"), resource_name)
                or _values_equal(record.get("software_name"), resource_name)
            ):
                continue
            return record
    return None


def _iter_records(collection: Any) -> list[dict]:
    """Return records from list/dict collections without raising on bad shapes."""
    if isinstance(collection, list):
        return [item for item in collection if isinstance(item, dict)]
    if isinstance(collection, dict):
        if any(isinstance(value, dict) for value in collection.values()):
            return [value for value in collection.values() if isinstance(value, dict)]
        return [collection]
    return []


def build_tool_map(tool_schemas: list[dict]) -> dict[str, Any]:
    """Build a tool function map from tool schemas.

    Each tool name maps to a closure: fn(db, **kwargs) -> Any
    that delegates to generic_tool.
    """
    tool_map = {}
    for schema in tool_schemas:
        name = schema["name"]

        def _make_fn(tool_name: str) -> Any:
            def fn(db: dict, **kwargs: Any) -> Any:
                return generic_tool(db, tool_name, **kwargs)
            return fn

        tool_map[name] = _make_fn(name)
    return tool_map
