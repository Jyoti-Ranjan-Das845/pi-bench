"""Evaluator reward-info dimension tests."""

from pi_bench.evaluator import evaluate
from pi_bench.trace import TraceRecorder


def test_evaluate_returns_dimension_breakdown():
    trace = TraceRecorder()
    trace.record(
        tool_name="lookup_order",
        arguments={"order_id": "ORD1"},
        result_content="ok",
        result_error=False,
        pre_state_hash="a",
        post_state_hash="a",
    )
    trace.record(
        tool_name="record_decision",
        arguments={"decision": "DENY"},
        result_content="ok",
        result_error=False,
        pre_state_hash="a",
        post_state_hash="a",
    )

    task = {
        "evaluation_criteria": {
            "reward_basis": ["POLICY", "STATE_FIELD"],
            "policy_checks": [
                {"outcome_id": "D1", "type": "decision_equals", "equals": "DENY"},
                {"outcome_id": "T1", "type": "tool_called", "tool_name": "lookup_order"},
            ],
            "state_field_checks": [
                {
                    "outcome_id": "S1",
                    "type": "state_field",
                    "field_path": "activity.pending_requests[request_id=REQ1].status",
                    "equals": "held",
                }
            ],
        }
    }
    sim = {
        "termination_reason": "agent_stop",
        "messages": [],
        "trace": trace,
        "env": {
            "db": {
                "activity": {
                    "pending_requests": [{"request_id": "REQ1", "status": "pending"}],
                }
            }
        },
    }

    result = evaluate(task, sim, domain={})

    assert result["all_passed"] is False
    assert "dimensions" in result
    assert result["dimensions"]["decision"]["passed"] is True
    assert result["dimensions"]["outcomes"]["passed"] is True
    assert result["dimensions"]["state"]["passed"] is False


def test_evaluate_exposes_canonical_decision_fields():
    trace = TraceRecorder()
    trace.record(
        tool_name="record_decision",
        arguments={"decision": "ESCALATE"},
        result_content="ok",
        result_error=False,
        pre_state_hash="a",
        post_state_hash="a",
    )
    task = {
        "evaluation_criteria": {
            "reward_basis": ["POLICY"],
            "policy_checks": [
                {"outcome_id": "D1", "type": "decision_equals", "equals": "ESCALATE"},
            ],
        }
    }
    sim = {"termination_reason": "agent_stop", "messages": [], "trace": trace}

    result = evaluate(task, sim, domain={})

    assert result["canonical_decision"] == "ESCALATE"
    assert result["decision_channel"] == "tool"
    assert result["decision_valid"] is True
    assert result["decision_error"] is None


def test_invalid_record_decision_is_reported_clearly():
    trace = TraceRecorder()
    trace.record(
        tool_name="record_decision",
        arguments={"decision": "MAYBE"},
        result_content="ok",
        result_error=False,
        pre_state_hash="a",
        post_state_hash="a",
    )
    task = {
        "evaluation_criteria": {
            "reward_basis": ["POLICY"],
            "policy_checks": [
                {"outcome_id": "D1", "type": "decision_equals", "equals": "DENY"},
            ],
        }
    }
    sim = {"termination_reason": "agent_stop", "messages": [], "trace": trace}

    result = evaluate(task, sim, domain={})

    assert result["all_passed"] is False
    assert result["canonical_decision"] is None
    assert result["decision_error"] == "INVALID_DECISION"
    assert result["outcome_results"][0]["detail"] == (
        "decision: expected=DENY, actual=INVALID:INVALID_DECISION"
    )


def test_action_and_communicate_results_are_per_check():
    task = {
        "evaluation_criteria": {
            "reward_basis": ["ACTION", "COMMUNICATE"],
            "expected_actions": [
                {
                    "action_id": "A1",
                    "name": "lookup_order",
                    "arguments": {"order_id": "ORD1"},
                    "compare_args": ["order_id"],
                },
                {"action_id": "A2", "name": "record_decision", "compare_args": []},
            ],
            "communicate_info": ["IT Security approval required"],
        }
    }
    sim = {
        "termination_reason": "agent_stop",
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "name": "lookup_order",
                        "arguments": {"order_id": "ORD1"},
                    }
                ],
            },
            {"role": "assistant", "content": "IT Security approval required."},
        ],
    }

    result = evaluate(task, sim, domain={})
    by_id = {r["outcome_id"]: r for r in result["outcome_results"]}

    assert by_id["A1"]["passed"] is True
    assert by_id["A2"]["passed"] is False
    assert by_id["COMMUNICATE_0"]["passed"] is True
    assert result["all_passed"] is False
