"""Smoke tests for retail/helpdesk/finra domain execution.

Verifies that all domains can be loaded via the scenario CLI path
(scenario_loader) and the runner API path (get_environment), that tools
dispatch correctly, and that semantic tool logic matches policy rules.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from domains.generic import generic_tool, build_tool_map, _HANDLERS
from pi_bench.scenario_loader import load, discover_scenarios

WORKSPACE = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = WORKSPACE / "scenarios"


# ── Helpers ──────────────────────────────────────────────


def _load_scenario(path: Path) -> dict:
    """Load a scenario via scenario_loader.load()."""
    return load(path, workspace_root=WORKSPACE)


def _all_scenario_paths(domain_subdir: str) -> list[Path]:
    """Return all scenario JSON paths for a domain subdirectory."""
    d = SCENARIOS_DIR / domain_subdir
    assert d.is_dir(), f"Missing scenarios directory: {d}"
    paths = sorted(d.glob("*.json"))
    assert paths, f"No scenario files found in {d}"
    return paths


# ── Test Group A: Scenario Loading ───────────────────────


class TestScenarioLoading:
    """Verify that every scenario loads via the generic scenario_loader path."""

    @pytest.mark.parametrize(
        "path", _all_scenario_paths("retail"),
        ids=lambda p: p.stem,
    )
    def test_load_retail_scenario(self, path: Path):
        result = _load_scenario(path)
        self._assert_env_complete(result, "retail")

    @pytest.mark.parametrize(
        "path", _all_scenario_paths("helpdesk"),
        ids=lambda p: p.stem,
    )
    def test_load_helpdesk_scenario(self, path: Path):
        result = _load_scenario(path)
        self._assert_env_complete(result, "helpdesk")

    @pytest.mark.parametrize(
        "path", _all_scenario_paths("finra"),
        ids=lambda p: p.stem,
    )
    def test_load_finra_scenario(self, path: Path):
        result = _load_scenario(path)
        self._assert_env_complete(result, "finra")

    def _assert_env_complete(self, result: dict, domain: str):
        env = result["env"]
        assert env["domain_name"] == domain, f"Expected domain '{domain}', got '{env['domain_name']}'"
        assert env["policy"], "Policy text must be non-empty"
        assert env["tools"], "Tool map must be non-empty"
        assert env["tool_schemas"], "Tool schemas must be non-empty"
        assert isinstance(env["db"], dict), "DB must be a dict"
        # Every tool in the schema must be callable
        for schema in env["tool_schemas"]:
            fn = env["tools"].get(schema["name"])
            assert callable(fn), f"Tool '{schema['name']}' not callable"


# ── Test Group B: Tool Dispatch ──────────────────────────


class TestToolDispatch:
    """Verify that calling tools via generic_tool returns dicts (no exceptions)."""

    def test_lookup_order_returns_order(self):
        db = {
            "orders": [
                {"order_id": "ORD_001", "customer_id": "C1", "total_amount": 49.99},
            ],
        }
        result = generic_tool(db, "lookup_order", order_id="ORD_001")
        assert isinstance(result, dict)
        assert result["order_id"] == "ORD_001"

    def test_lookup_order_missing(self):
        db = {"orders": []}
        result = generic_tool(db, "lookup_order", order_id="NONEXISTENT")
        assert isinstance(result, dict)
        assert "error" in result or "message" in result

    def test_lookup_customer_profile(self):
        db = {"customer_profile": {"customer_id": "C1", "loyalty_tier": "Silver"}}
        result = generic_tool(db, "lookup_customer_profile", customer_id="C1")
        assert isinstance(result, dict)
        assert result.get("customer_id") == "C1"

    def test_lookup_employee(self):
        db = {
            "employee": {
                "employee_id": "EMP_2201",
                "display_name": "David Park",
                "email": "dpark@globex.com",
            },
            "accounts": {},
        }
        result = generic_tool(db, "lookup_employee", employee_id="EMP_2201")
        assert isinstance(result, dict)
        assert result.get("employee_id") == "EMP_2201"

    def test_record_decision(self):
        db = {}
        result = generic_tool(db, "record_decision", decision="ALLOW", rationale="OK")
        assert result["decision"] == "ALLOW"
        assert db["decisions"][0]["decision"] == "ALLOW"

    def test_process_refund_basic(self):
        db = {"orders": [{"order_id": "ORD_1", "total_amount": 100.0, "status": "delivered"}]}
        result = generic_tool(db, "process_refund", order_id="ORD_1")
        assert result["status"] == "processed"
        assert result["amount_refunded"] == 100.0

    def test_reset_password_standard(self):
        db = {"accounts": {"EMP_1": {"account_type": "standard", "password_last_changed": "2025-01-01"}}}
        result = generic_tool(db, "reset_password", employee_id="EMP_1", account_type="standard")
        assert result["status"] == "reset_complete"

    def test_reset_password_admin_blocked(self):
        db = {"accounts": {}}
        result = generic_tool(db, "reset_password", employee_id="EMP_1", account_type="admin")
        assert result.get("error") is True

    def test_log_ticket(self):
        db = {"tickets": []}
        result = generic_tool(db, "log_ticket", employee_id="EMP_1", category="password_reset")
        assert "ticket_id" in result
        assert len(db["tickets"]) == 1

    def test_install_software_prohibited(self):
        db = {"prohibited_software": ["BitTorrent"]}
        result = generic_tool(db, "install_software", software_name="BitTorrent")
        assert result.get("error") is True

    def test_install_software_allowed(self):
        db = {"prohibited_software": ["BitTorrent"]}
        result = generic_tool(db, "install_software", software_name="VSCode")
        assert result["status"] == "installed"

    def test_all_retail_handlers_registered(self):
        retail_tools = [
            "lookup_order", "lookup_customer_profile", "process_refund",
            "process_exchange", "apply_store_credit", "deny_refund",
            "escalate_to_manager", "flag_account", "check_return_eligibility",
            "record_decision",
        ]
        for name in retail_tools:
            assert name in _HANDLERS, f"Retail tool '{name}' missing from _HANDLERS"

    def test_all_helpdesk_handlers_registered(self):
        helpdesk_tools = [
            "lookup_employee", "verify_identity", "reset_password",
            "unlock_account", "provision_vpn_access", "install_software",
            "create_access_request", "escalate_to_tier2", "escalate_to_it_security",
            "check_approval_status", "log_ticket", "record_decision",
        ]
        for name in helpdesk_tools:
            assert name in _HANDLERS, f"Helpdesk tool '{name}' missing from _HANDLERS"


# ── Test Group C: Semantic Correctness ───────────────────


class TestSemanticCorrectness:
    """Verify tool handlers produce semantically correct results per policy."""

    # -- check_return_eligibility --

    def test_check_return_eligibility_within_window(self):
        """Standard apparel item delivered 10 days ago → eligible, 30-day window."""
        db = {
            "orders": [{
                "order_id": "ORD_1",
                "delivery_date": "2026-02-16T09:15:00-05:00",
                "is_final_sale": False,
                "items": [{"category": "apparel", "price": 49.99}],
                "customer_id": "C1",
            }],
            "customer_profile": {"customer_id": "C1", "loyalty_tier": "Silver"},
            "now": "2026-02-26T14:20:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_1")
        assert result["eligible"] is True

    def test_check_return_eligibility_final_sale(self):
        """Final sale item → always ineligible."""
        db = {
            "orders": [{
                "order_id": "ORD_2",
                "delivery_date": "2026-02-20T10:00:00-05:00",
                "is_final_sale": True,
                "items": [{"category": "apparel", "price": 245.0}],
                "customer_id": "C2",
            }],
            "customer_profile": {"customer_id": "C2", "loyalty_tier": "Gold"},
            "now": "2026-02-26T15:30:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_2")
        assert result["eligible"] is False
        assert "final sale" in result["reason"].lower()

    def test_check_return_eligibility_electronics_restocking_fee(self):
        """Electronics within 15-day window → eligible but 15% restocking fee."""
        db = {
            "orders": [{
                "order_id": "ORD_3",
                "delivery_date": "2026-02-14T14:22:00-05:00",
                "is_final_sale": False,
                "items": [{"category": "electronics", "price": 1299.99}],
                "customer_id": "C3",
            }],
            "customer_profile": {"customer_id": "C3", "loyalty_tier": "Silver"},
            "now": "2026-02-26T11:15:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_3")
        assert result["eligible"] is True
        assert result["restocking_fee_applicable"] is True
        assert result["restocking_fee_percent"] == 15

    def test_check_return_eligibility_past_window(self):
        """Apparel delivered 45 days ago, Silver tier → outside 30-day window."""
        db = {
            "orders": [{
                "order_id": "ORD_4",
                "delivery_date": "2026-01-12T10:00:00-05:00",
                "is_final_sale": False,
                "items": [{"category": "apparel", "price": 50.0}],
                "customer_id": "C4",
            }],
            "customer_profile": {"customer_id": "C4", "loyalty_tier": "Silver"},
            "now": "2026-02-26T10:00:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_4")
        assert result["eligible"] is False
        assert "window" in result["reason"].lower()

    def test_check_return_eligibility_gold_extended_window(self):
        """Gold tier gets 45-day window for general merchandise.
        Item delivered 35 days ago → eligible for Gold, not for Silver."""
        db = {
            "orders": [{
                "order_id": "ORD_5",
                "delivery_date": "2026-01-22T10:00:00-05:00",
                "is_final_sale": False,
                "items": [{"category": "apparel", "price": 99.0}],
                "customer_id": "C5",
            }],
            "customer_profile": {"customer_id": "C5", "loyalty_tier": "Gold"},
            "now": "2026-02-26T10:00:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_5")
        assert result["eligible"] is True

    def test_check_return_eligibility_electronics_past_15_days(self):
        """Electronics delivered 20 days ago, Silver → past 15-day window."""
        db = {
            "orders": [{
                "order_id": "ORD_6",
                "delivery_date": "2026-02-06T10:00:00-05:00",
                "is_final_sale": False,
                "items": [{"category": "electronics", "price": 500.0}],
                "customer_id": "C6",
            }],
            "customer_profile": {"customer_id": "C6", "loyalty_tier": "Silver"},
            "now": "2026-02-26T10:00:00-05:00",
        }
        result = generic_tool(db, "check_return_eligibility", order_id="ORD_6")
        assert result["eligible"] is False
        assert "window" in result["reason"].lower()

    # -- verify_identity --

    def test_verify_identity_rejects_wrong_items(self):
        """Identity check with wrong verification data → verified=False."""
        db = {
            "employee": {
                "employee_id": "EMP_001",
                "date_of_birth": "1991-06-14",
                "manager": "Lisa Huang",
                "department": "Marketing",
                "job_title": "Marketing Analyst",
                "phone_last_four": "8823",
            },
        }
        result = generic_tool(
            db, "verify_identity",
            employee_id="EMP_001",
            verification_items={
                "date_of_birth": "1985-01-01",  # WRONG
                "manager": "John Smith",          # WRONG
                "department": "Engineering",       # WRONG
            },
        )
        assert result["verified"] is False

    def test_verify_identity_accepts_correct_items(self):
        """Identity check with correct data → verified=True."""
        db = {
            "employee": {
                "employee_id": "EMP_001",
                "date_of_birth": "1991-06-14",
                "manager": "Lisa Huang",
                "department": "Marketing",
                "job_title": "Marketing Analyst",
                "phone_last_four": "8823",
            },
        }
        result = generic_tool(
            db, "verify_identity",
            employee_id="EMP_001",
            verification_items={
                "date_of_birth": "1991-06-14",
                "manager": "Lisa Huang",
                "department": "Marketing",
            },
        )
        assert result["verified"] is True

    # -- process_refund --

    def test_process_refund_applies_restocking_fee(self):
        """Electronics refund → 15% restocking fee deducted."""
        db = {
            "orders": [{
                "order_id": "ORD_E1",
                "total_amount": 1000.0,
                "status": "delivered",
                "items": [{"category": "electronics", "price": 1000.0}],
            }],
        }
        result = generic_tool(
            db, "process_refund",
            order_id="ORD_E1",
            restocking_fee_percent=15,
        )
        assert result["restocking_fee_amount"] == 150.0
        assert result["amount_refunded"] == 850.0

    # -- unlock_account --

    def test_unlock_account_security_flagged(self):
        """Account with security_flag lockout → should indicate escalation needed."""
        db = {
            "accounts": {
                "EMP_99": {
                    "account_type": "standard",
                    "lockout_status": "locked",
                    "lockout_reason": "security_flag",
                },
            },
        }
        result = generic_tool(db, "unlock_account", employee_id="EMP_99")
        # Security-flagged accounts should NOT just unlock — they need IT Security
        assert result.get("status") != "unlocked" or result.get("requires_escalation") is True


# ── Test Group D: Runner API Path ────────────────────────


class TestRunnerAPIPath:
    """Verify that retail and helpdesk domains export get_environment()."""

    def test_retail_has_get_environment(self):
        from domains.retail import get_environment
        assert callable(get_environment)

    def test_helpdesk_has_get_environment(self):
        from domains.helpdesk import get_environment
        assert callable(get_environment)

    def test_retail_get_environment_returns_env(self):
        from domains.retail import get_environment
        env = get_environment()
        assert env["domain_name"] == "retail"
        assert env["policy"]
        assert env["tools"]
        assert env["tool_schemas"]

    def test_helpdesk_get_environment_returns_env(self):
        from domains.helpdesk import get_environment
        env = get_environment()
        assert env["domain_name"] == "helpdesk"
        assert env["policy"]
        assert env["tools"]
        assert env["tool_schemas"]

    def test_retail_get_environment_with_scenario(self):
        """get_environment(scenario) should seed DB from scenario."""
        from domains.retail import get_environment
        path = SCENARIOS_DIR / "retail" / "scen_044_fraud_flag_cash_refund.json"
        with open(path) as f:
            scenario = json.load(f)
        env = get_environment(scenario=scenario)
        assert env["db"].get("orders"), "DB should have orders from scenario"

    def test_helpdesk_get_environment_with_scenario(self):
        """get_environment(scenario) should seed DB from scenario."""
        from domains.helpdesk import get_environment
        path = SCENARIOS_DIR / "helpdesk" / "scen_046_cross_employee_disclosure.json"
        with open(path) as f:
            scenario = json.load(f)
        env = get_environment(scenario=scenario)
        assert env["db"].get("accounts"), "DB should have accounts from scenario"

    def test_retail_exports_tool_schemas(self):
        from domains.retail import TOOL_SCHEMAS
        assert isinstance(TOOL_SCHEMAS, list)
        assert len(TOOL_SCHEMAS) > 0
        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "lookup_order" in names
        assert "process_refund" in names
        assert "record_decision" in names

    def test_helpdesk_exports_tool_schemas(self):
        from domains.helpdesk import TOOL_SCHEMAS
        assert isinstance(TOOL_SCHEMAS, list)
        assert len(TOOL_SCHEMAS) > 0
        names = {s["name"] for s in TOOL_SCHEMAS}
        assert "verify_identity" in names
        assert "reset_password" in names
        assert "record_decision" in names

    def test_retail_exports_agent_tools(self):
        from domains.retail import AGENT_TOOLS
        assert isinstance(AGENT_TOOLS, dict)
        assert callable(AGENT_TOOLS.get("lookup_order"))

    def test_helpdesk_exports_agent_tools(self):
        from domains.helpdesk import AGENT_TOOLS
        assert isinstance(AGENT_TOOLS, dict)
        assert callable(AGENT_TOOLS.get("verify_identity"))
