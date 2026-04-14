"""A2A public entrypoint contract tests."""

import json

import pytest


def test_a2a_url_helpers_accept_base_and_explicit_endpoint():
    from pi_bench.a2a.bootstrap import agent_card_urls
    from pi_bench.a2a.purple_adapter import (
        _agent_card_base_url,
        _normalize_message_url,
    )

    assert _normalize_message_url("http://agent.example:9000/") == (
        "http://agent.example:9000"
    )
    assert _normalize_message_url(
        "http://agent.example:9000/a2a/message/send"
    ) == "http://agent.example:9000/a2a/message/send"
    assert _agent_card_base_url(
        "http://agent.example:9000/a2a/message/send"
    ) == "http://agent.example:9000"
    assert agent_card_urls("http://agent.example:9000/a2a/message/send") == [
        "http://agent.example:9000/.well-known/agent.json",
        "http://agent.example:9000/.well-known/agent-card.json",
    ]


def test_a2a_response_errors_are_clear():
    from pi_bench.a2a.purple_adapter import A2AProtocolError, _parse_a2a_response

    with pytest.raises(A2AProtocolError, match="JSON-RPC error"):
        _parse_a2a_response({"error": {"message": "bad request"}})

    with pytest.raises(A2AProtocolError, match="missing result"):
        _parse_a2a_response({"jsonrpc": "2.0"})


def test_a2a_tool_call_argument_errors_are_clear():
    from pi_bench.a2a.purple_adapter import A2AProtocolError, _part_to_pi_msg

    with pytest.raises(A2AProtocolError, match="invalid JSON arguments"):
        _part_to_pi_msg(
            {
                "kind": "data",
                "data": {
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "lookup_account",
                                "arguments": "{not-json",
                            },
                        }
                    ],
                },
            }
        )


def test_agentbeats_results_include_stable_public_fields():
    from pi_bench.a2a.results import to_agentbeats_results

    payload = to_agentbeats_results(
        agent_id="agent_1",
        domain="policy_compliance",
        time_used=1.25,
        scenario_results=[
            {
                "benchmark_version": "0.1.0",
                "scenario_id": "scen_1",
                "domain": "retail_refund_sop_v1",
                "domain_name": "retail",
                "leaderboard_primary": "Safety Boundary Enforcement",
                "label": "DENY",
                "status": "completed",
                "reward": 0.0,
                "all_passed": False,
                "semantic_score": 1.0,
                "canonical_decision": "ALLOW",
                "decision_channel": "tool",
                "decision_valid": True,
                "decision_error": None,
                "event_flags": {"V_r": True},
                "seed": 123,
                "duration": 0.5,
                "tool_calls": ["lookup_order"],
                "dimensions": {"action": {"passed": 0, "total": 1}},
                "outcome_results": [
                    {
                        "outcome_id": "a1",
                        "type": "ACTION",
                        "passed": False,
                        "detail": "missing call",
                        "dimension": "action",
                    }
                ],
            }
        ],
    )

    result = payload["results"][0]
    detail = result["scenario_details"][0]

    assert result["score"] == 0.0
    assert result["task_rewards_by_scenario_id"] == {"scen_1": 0.0}
    assert result["metrics"]["by_column"]["Safety Boundary Enforcement"]["total"] == 1
    assert result["flag_summary"]["violation_rate"] == 1.0
    assert detail["status"] == "completed"
    assert detail["leaderboard_primary"] == "Safety Boundary Enforcement"
    assert detail["reward"] == 0.0
    assert detail["all_passed"] is False
    assert detail["semantic_score"] == 1.0
    assert detail["decision_channel"] == "tool"
    assert detail["seed"] == 123
    assert detail["outcome_checks"][0]["dimension"] == "action"


def test_agentbeats_results_do_not_publish_raw_audit_records():
    from pi_bench.a2a.results import to_agentbeats_results

    payload = to_agentbeats_results(
        agent_id="agent_1",
        domain="policy_compliance",
        scenario_results=[
            {
                "scenario_id": "scen_1",
                "status": "completed",
                "reward": 0.0,
                "all_passed": False,
                "event_flags": {},
                "messages": [{"role": "assistant", "content": "hello"}],
                "trace": "TraceRecorder(...)",
                "env": {"db": {"secret": "audit-only"}},
            }
        ],
    )

    detail = payload["results"][0]["scenario_details"][0]

    assert "messages" not in detail
    assert "trace" not in detail
    assert "env" not in detail


def test_a2a_server_card_and_routes_use_public_contract(tmp_path):
    from pi_bench import __version__
    from pi_bench.a2a.server import build_agent_card, create_app

    card = build_agent_card("127.0.0.1", 9009)
    app = create_app("127.0.0.1", 9009, scenarios_dir=tmp_path)
    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert card.version == __version__
    assert "/a2a/message/send" in route_paths
    assert "/" in route_paths
    assert "/.well-known/agent.json" in route_paths
    assert "/.well-known/agent-card.json" in route_paths
    assert app.state.scenarios_dir == tmp_path
    assert app.state.concurrency == 1


def test_a2a_server_accepts_concurrency_cap(tmp_path):
    from pi_bench.a2a.server import create_app

    app = create_app("127.0.0.1", 9009, scenarios_dir=tmp_path, concurrency=4)

    assert app.state.concurrency == 4


def test_agentbeats_envelope_accepts_official_participant_url_shape():
    from pi_bench.a2a.executor import _parse_agentbeats_envelope

    envelope = _parse_agentbeats_envelope(
        {
            "participants": {"agent": "http://purple.example:9009/"},
            "agentbeats_ids": {"agent": "agent-uuid-1"},
            "config": {"scenario_scope": "domain", "scenario_domain": "finra", "concurrency": 5},
        },
        server_concurrency=3,
    )

    assert envelope.purple_url == "http://purple.example:9009"
    assert envelope.agent_id == "agent-uuid-1"
    assert envelope.domain == "policy_compliance"
    assert envelope.config["scenario_scope"] == "domain"
    assert envelope.config["scenario_domain"] == "finra"
    assert envelope.config["user_model"] == "gpt-5.4"
    assert envelope.config["max_steps"] == 40
    assert envelope.config["concurrency"] == 3


def test_agentbeats_envelope_accepts_local_rich_participant_shape():
    from pi_bench.a2a.executor import _parse_agentbeats_envelope

    envelope = _parse_agentbeats_envelope(
        {
            "participants": {
                "agent": {"url": "http://purple.example/a2a/message/send", "id": "local-agent"}
            },
            "config": {"domain": "policy_compliance_test", "scenario_scope": "all"},
        },
        server_concurrency=5,
    )

    assert envelope.purple_url == "http://purple.example/a2a/message/send"
    assert envelope.agent_id == "local-agent"
    assert envelope.domain == "policy_compliance_test"
    assert envelope.config["scenario_scope"] == "all"
    assert envelope.config["user_model"] == "gpt-5.4"


def test_agentbeats_envelope_rejects_single_scenario_scope():
    from pi_bench.a2a.executor import _parse_agentbeats_envelope

    with pytest.raises(ValueError, match="scenario_scope"):
        _parse_agentbeats_envelope(
            {
                "participants": {"agent": "http://purple.example"},
                "config": {"scenario_scope": "scenario"},
            },
            server_concurrency=1,
        )


def test_run_assessment_default_scenarios_path_uses_workspace(monkeypatch, tmp_path):
    from pi_bench.a2a import assessment

    observed = []
    (tmp_path / "scenarios").mkdir()
    monkeypatch.setattr(assessment, "default_workspace_root", lambda: tmp_path)
    monkeypatch.setattr(
        assessment,
        "discover_scenarios",
        lambda path: observed.append(path) or [],
    )

    with pytest.raises(FileNotFoundError):
        assessment.run_assessment("http://purple.example")

    assert observed == [tmp_path / "scenarios"]


def test_run_assessment_filters_to_domain_scope(monkeypatch, tmp_path):
    from pi_bench.a2a import assessment

    scenarios = tmp_path / "scenarios"
    retail = scenarios / "retail"
    retail.mkdir(parents=True)
    observed = []
    monkeypatch.setattr(
        assessment,
        "discover_scenarios",
        lambda path: observed.append(path) or [],
    )

    with pytest.raises(FileNotFoundError):
        assessment.run_assessment(
            "http://purple.example",
            {
                "scenarios_dir": scenarios,
                "scenario_scope": "domain",
                "scenario_domain": "retail",
            },
        )

    assert observed == [retail]


def test_run_assessment_rejects_single_scenario_style_scope(tmp_path):
    from pi_bench.a2a import assessment

    scenarios = tmp_path / "scenarios"
    scenarios.mkdir()

    with pytest.raises(ValueError, match="scenario_scope"):
        assessment.run_assessment(
            "http://purple.example",
            {"scenarios_dir": scenarios, "scenario_scope": "scenario"},
        )


def test_a2a_assessment_uses_interactive_user_without_ticket(monkeypatch, tmp_path):
    from pi_bench.a2a import assessment

    scenario_path = tmp_path / "scen_interactive.json"
    scenario_path.write_text(json.dumps({
        "meta": {"scenario_id": "scen_interactive", "domain": "retail"},
        "user_simulation": {"initial_user_message": "I need help."},
    }))

    task = {
        "id": "scen_interactive",
        "scenario_id": "scen_interactive",
        "description": "Task context",
        "domain": "retail",
        "domain_name": "retail",
        "leaderboard_primary": "test",
        "evaluation_criteria": {},
        "user_scenario": {"initial_user_message": "I need help."},
    }
    loaded = {
        "task": task,
        "env": {"db": {}, "tools": [], "policy": "policy"},
        "label": "DENY",
        "scenario_id": "scen_interactive",
        "forbidden_tools": [],
    }
    observed = {}

    class StubAgent:
        model_name = "stub-agent"

        def __init__(self, url):
            self.url = url

    class StubUser:
        model_name = "stub-user"

        def __init__(self, url):
            self.url = url

    def fake_run(**kwargs):
        observed.update(kwargs)
        return {
            "messages": [
                {"role": "assistant", "content": "Hi! How can I help you today?"},
                {"role": "user", "content": "I need help."},
                {"role": "assistant", "content": "I can help."},
                {"role": "user", "content": "###STOP###"},
            ],
            "termination_reason": "user_stop",
            "step_count": 3,
        }

    monkeypatch.setattr(assessment, "load", lambda *_args, **_kwargs: loaded)
    monkeypatch.setattr(assessment, "validate_scenario", lambda _data: [])
    monkeypatch.setattr(assessment, "_validate_referenced_tools_exist", lambda **_kwargs: [])
    monkeypatch.setattr(assessment, "A2APurpleAgent", StubAgent)
    monkeypatch.setattr(assessment, "A2AUserAgent", StubUser)
    monkeypatch.setattr(assessment, "orchestrator_run", fake_run)
    monkeypatch.setattr(
        assessment,
        "evaluate",
        lambda *_args, **_kwargs: {
            "all_passed": True,
            "reward": 1.0,
            "outcome_results": [],
            "semantic_score": 1.0,
            "dimensions": {},
            "canonical_decision": "DENY",
            "decision_channel": "tool",
            "decision_valid": True,
            "decision_error": None,
        },
    )
    monkeypatch.setattr(
        assessment,
        "compute_flags",
        lambda **_kwargs: type("Flags", (), {
            "V_r": False,
            "UR_r": False,
            "OR_r": False,
            "EA_r": False,
            "AT_r": False,
        })(),
    )

    result = assessment._run_single_scenario(
        scenario_path=scenario_path,
        purple_url="http://purple.example",
        workspace_root=tmp_path,
        user_url="http://user.example",
    )

    assert observed["solo"] is False
    assert isinstance(observed["agent"], StubAgent)
    assert isinstance(observed["user"], StubUser)
    assert observed["user"].url == "http://user.example"
    assert "ticket" not in observed["task"]
    assert result["status"] == "completed"
    assert result["user_model"] == "stub-user"


def test_a2a_data_part_content_and_tool_call_round_trips():
    from pi_bench.a2a.purple_adapter import _part_to_pi_msg

    msg = _part_to_pi_msg(
        {
            "kind": "data",
            "data": {
                "content": "I will check that.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "lookup_order",
                            "arguments": json.dumps({"order_id": "O-1"}),
                        },
                    }
                ],
            },
        }
    )

    assert msg["content"] == "I will check that."
    assert msg["tool_calls"][0]["name"] == "lookup_order"
    assert msg["tool_calls"][0]["arguments"] == {"order_id": "O-1"}
