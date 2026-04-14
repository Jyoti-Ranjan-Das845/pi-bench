"""Public runtime contract tests for participant integrations."""

import json
from types import SimpleNamespace

import pytest


def test_protocol_import_paths_are_available():
    from pi_bench.local import AgentProtocol as LocalAgentProtocol
    from pi_bench.local import UserProtocol as LocalUserProtocol
    from pi_bench.protocols import AgentProtocol, UserProtocol
    from pi_bench.protocols.local import AgentProtocol as NestedAgentProtocol
    from pi_bench.protocols.local import UserProtocol as NestedUserProtocol

    assert AgentProtocol is LocalAgentProtocol is NestedAgentProtocol
    assert UserProtocol is LocalUserProtocol is NestedUserProtocol


def test_package_version_is_exposed():
    import pi_bench

    assert isinstance(pi_bench.__version__, str)
    assert pi_bench.__version__


def test_build_tool_call_normalizes_and_validates():
    from pi_bench.types import build_tool_call

    tool_call = build_tool_call("lookup_account", call_id="call_1")

    assert tool_call == {
        "id": "call_1",
        "name": "lookup_account",
        "arguments": {},
        "requestor": "assistant",
    }

    with pytest.raises(ValueError, match="name"):
        build_tool_call("")
    with pytest.raises(ValueError, match="arguments"):
        build_tool_call("lookup_account", arguments="not-json")
    with pytest.raises(ValueError, match="requestor"):
        build_tool_call("lookup_account", requestor="environment")
    with pytest.raises(ValueError, match="id"):
        build_tool_call("lookup_account", call_id="")


def test_validate_message_accepts_content_tools_or_both():
    from pi_bench.types import validate_message

    tool_call = {
        "id": "call_1",
        "name": "lookup_account",
        "arguments": {"account_id": "A123"},
    }

    assert validate_message({"role": "assistant", "content": "Hello"})
    assert validate_message({"role": "assistant", "tool_calls": [tool_call]})
    assert validate_message(
        {
            "role": "assistant",
            "content": "Let me check.",
            "tool_calls": [tool_call],
        }
    )


def test_validate_message_rejects_bad_shapes():
    from pi_bench.types import validate_message

    assert not validate_message({"role": "assistant"})
    assert not validate_message({"role": "assistant", "content": ""})
    assert not validate_message({"role": "assistant", "tool_calls": []})
    assert not validate_message(
        {
            "role": "assistant",
            "tool_calls": [
                {"name": "lookup_account", "arguments": {}},
            ],
        }
    )
    assert not validate_message(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "lookup_account",
                    "arguments": "not-a-dict",
                },
            ],
        }
    )
    assert not validate_message(
        {
            "role": "assistant",
            "tool_calls": [
                {
                    "id": "call_1",
                    "name": "lookup_account",
                    "arguments": {},
                    "requestor": "environment",
                },
            ],
        }
    )
    assert not validate_message({"role": "unexpected", "content": "Hello"})


def test_pydantic_tool_call_contract_is_strict():
    from pydantic import ValidationError

    from pi_bench.types import ToolCallModel, validate_tool_call

    valid = {
        "id": "call_1",
        "name": "lookup_account",
        "arguments": {"account_id": "A123"},
    }
    assert ToolCallModel.model_validate(valid).name == "lookup_account"

    with pytest.raises(ValidationError):
        ToolCallModel.model_validate({**valid, "unexpected": True})

    assert not validate_tool_call({**valid, "unexpected": True})
    assert not validate_tool_call({**valid, "arguments": []})


def test_normal_runtime_requires_user_unless_solo():
    from pi_bench.orchestrator import run

    with pytest.raises(ValueError, match="user is required unless solo=True"):
        run(agent=object(), user=None, env={}, task={}, solo=False)


def test_a2a_bootstrap_sends_benchmark_context_once():
    from pi_bench.a2a.bootstrap import BenchmarkBootstrap, build_bootstrap_request
    from pi_bench.a2a.purple_adapter import (
        _build_a2a_request,
        _build_a2a_request_bootstrapped,
    )

    benchmark_context = [
        {"kind": "policy", "content": "POLICY", "metadata": {"scenario_id": "s1"}},
        {"kind": "task", "content": "TASK", "metadata": {"scenario_id": "s1"}},
    ]
    bootstrap = build_bootstrap_request(
        BenchmarkBootstrap(
            benchmark_context=benchmark_context,
            tools=[{"type": "function", "function": {"name": "lookup"}}],
            run_id="run_1",
            domain="demo",
        ),
        task_id="task_1",
    )
    bootstrap_data = bootstrap["params"]["message"]["parts"][0]["data"]

    assert bootstrap_data["benchmark_context"] == benchmark_context
    assert bootstrap_data["tools"] == [{"type": "function", "function": {"name": "lookup"}}]
    assert bootstrap_data["run_id"] == "run_1"
    assert bootstrap_data["domain"] == "demo"
    assert "policy_text" not in bootstrap_data
    assert "task_description" not in bootstrap_data

    request = _build_a2a_request_bootstrapped(
        messages=[
            {"role": "user", "content": "hello"},
        ],
        context_id="ctx_1",
        task_id="task_1",
    )
    data = request["params"]["message"]["parts"][0]["data"]

    assert data["context_id"] == "ctx_1"
    assert data["messages"] == [{"role": "user", "content": "hello"}]
    assert "tools" not in data
    assert "benchmark_context" not in data

    fallback = _build_a2a_request(
        messages=[{"role": "user", "content": "hello"}],
        benchmark_context=benchmark_context,
        tools=[],
        task_id="task_1",
    )
    fallback_data = fallback["params"]["message"]["parts"][0]["data"]
    assert fallback_data["benchmark_context"] == benchmark_context


def test_litellm_agent_conversion_preserves_content_with_tool_calls():
    from pi_bench.agents.litellm_agent import _from_openai_response

    choice_message = SimpleNamespace(
        content="Let me check.",
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="lookup_account",
                    arguments=json.dumps({"account_id": "A123"}),
                ),
            ),
        ],
    )

    msg = _from_openai_response(choice_message)

    assert msg["role"] == "assistant"
    assert msg["content"] == "Let me check."
    assert msg["tool_calls"] == [
        {
            "id": "call_1",
            "name": "lookup_account",
            "arguments": {"account_id": "A123"},
            "requestor": "assistant",
        }
    ]


def test_litellm_agent_conversion_rejects_invalid_tool_arguments():
    from pi_bench.agents.litellm_agent import _from_openai_response

    choice_message = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id="call_1",
                function=SimpleNamespace(
                    name="lookup_account",
                    arguments="{not-json",
                ),
            ),
        ],
    )

    with pytest.raises(json.JSONDecodeError):
        _from_openai_response(choice_message)


def test_a2a_data_part_preserves_content_with_tool_calls():
    from pi_bench.a2a.purple_adapter import _part_to_pi_msg

    msg = _part_to_pi_msg(
        {
            "kind": "data",
            "data": {
                "content": "Let me check.",
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "lookup_account",
                            "arguments": json.dumps({"account_id": "A123"}),
                        },
                    }
                ],
            },
        }
    )

    assert msg["content"] == "Let me check."
    assert msg["tool_calls"][0]["name"] == "lookup_account"
    assert msg["tool_calls"][0]["arguments"] == {"account_id": "A123"}
