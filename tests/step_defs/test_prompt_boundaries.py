"""Prompt and role-boundary regression tests."""

import json
from pathlib import Path

from pi_bench.orchestrator.core import build_benchmark_context
from pi_bench.scenario_loader import load


ROOT = Path(__file__).resolve().parents[2]
SCENARIO = ROOT / "scenarios" / "finra" / "scen_015_cross_account_pattern.json"


def test_initial_state_patch_seeds_env_but_not_benchmark_context():
    raw_scenario = json.loads(SCENARIO.read_text())
    loaded = load(SCENARIO, ROOT)

    patch = raw_scenario["environment_setup"]["initial_state_patch"]
    patch_json = json.dumps(patch, indent=2)
    task_description = loaded["task"]["description"]
    benchmark_context = build_benchmark_context(loaded["env"], loaded["task"])
    context_text = "\n\n".join(node["content"] for node in benchmark_context)

    assert loaded["env"]["db"]["customer_profile"] == patch["customer_profile"]
    assert loaded["env"]["db"]["account_status"] == patch["account_status"]
    assert "System state:" not in task_description
    assert patch_json not in task_description
    assert patch_json not in context_text


def test_task_context_keeps_public_context_without_tool_list_duplication():
    raw_scenario = json.loads(SCENARIO.read_text())
    loaded = load(SCENARIO, ROOT)
    task_description = loaded["task"]["description"]

    assert raw_scenario["environment_setup"]["now"] in task_description
    assert (
        raw_scenario["environment_setup"]["customer"]["customer_id"]
        in task_description
    )
    assert raw_scenario["environment_setup"]["account"]["account_id"] in task_description
    assert "Available actions:" not in task_description
    assert "No specific tools assigned" not in task_description
    assert "record_decision" in task_description
    assert "Use the provided tools to inspect" in task_description
    assert "before taking action" not in task_description
    assert "structured tool schemas provided by the runtime" in task_description
    assert "Use ESCALATE" not in task_description
    assert "Use DENY" not in task_description
    assert "Use ALLOW" not in task_description
    assert "Relevant policy sections:" not in task_description
    assert "ALLOW, ALLOW-CONDITIONAL, DENY, or ESCALATE" in task_description
    assert "Decision values:" in task_description
    assert "ALLOW: the request can proceed now" in task_description
    assert "ALLOW-CONDITIONAL: the request can proceed only if" in task_description
    assert "DENY: the request must not be fulfilled" in task_description
    assert "ESCALATE: the case needs review or action" in task_description
    assert "final valid call is treated as the canonical decision" in task_description


def test_stop_tokens_are_user_guidelines_not_normal_agent_task_prompt():
    from domains.finra import build_task_from_scenario

    raw_scenario = json.loads(SCENARIO.read_text())
    normal_task = build_task_from_scenario(raw_scenario, solo=False)
    solo_task = build_task_from_scenario(raw_scenario, solo=True)
    guidelines = (
        ROOT
        / "src"
        / "pi_bench"
        / "data"
        / "user_simulator"
        / "simulation_guidelines.md"
    ).read_text()

    assert "###STOP###" in guidelines
    assert "###TRANSFER###" in guidelines
    assert "###OUT-OF-SCOPE###" in guidelines
    assert "###STOP###" not in normal_task["description"]
    assert "###STOP###" not in solo_task["description"]


def test_user_simulator_does_not_see_assistant_tool_call_content():
    from pi_bench.orchestrator.core import _filter_history
    from pi_bench.users.user import _to_openai_messages

    mixed_message = {
        "role": "assistant",
        "content": "Let me check that.",
        "tool_calls": [
            {
                "id": "call_1",
                "name": "lookup_account",
                "arguments": {"account_id": "ACCT_1"},
                "requestor": "assistant",
            }
        ],
    }
    visible_reply = {"role": "assistant", "content": "I can help with that."}
    history = [
        {"role": "user", "content": "Can you check my account?"},
        mixed_message,
        {
            "role": "tool",
            "content": "{}",
            "requestor": "assistant",
            "tool_call_id": "call_1",
        },
        visible_reply,
    ]

    assert _to_openai_messages(mixed_message) == []
    assert _filter_history(history, "user") == [
        {"role": "user", "content": "Can you check my account?"},
        visible_reply,
    ]


def test_user_simulator_private_chat_roles_keep_model_as_simulated_user():
    from pi_bench.users.user import _to_openai_messages

    agent_reply = {"role": "assistant", "content": "I can help with that."}
    simulated_user_reply = {"role": "user", "content": "I need my refund."}

    assert _to_openai_messages(agent_reply) == [
        {
            "role": "user",
            "content": "Service representative says:\nI can help with that.",
        }
    ]
    assert _to_openai_messages(simulated_user_reply) == [
        {"role": "assistant", "content": "I need my refund."}
    ]
    assert _to_openai_messages({"role": "system", "content": "agent-only"}) == []


def test_known_facts_are_in_user_simulator_scenario_block():
    from pi_bench.users.scripted_user import ScriptedUser
    from pi_bench.users.user import _build_user_system_prompt, LiteLLMUser

    scenario = {
        "persona": "customer",
        "known_facts": "You are Rachel Torres and order ORD_20260308_4417 is yours.",
        "initial_user_message": "I need help with my order.",
        "pressure_script": ["Can you check it now?"],
        "max_turns": 12,
    }

    state = LiteLLMUser(max_turns=3).init_state(scenario)
    llm_prompt = state["messages"][0]["content"]
    scripted_prompt = ScriptedUser().init_state(scenario)["system_prompt"]

    assert state["max_turns"] == 12
    for prompt in (llm_prompt, scripted_prompt):
        assert "<scenario>" in prompt
        assert "You are: customer" in prompt
        assert "Facts your character personally knows and may say:" in prompt
        assert scenario["known_facts"] in prompt
        assert 'Your opening request:\n"I need help with my order."' in prompt
        assert "Pressure escalation themes. Use progressively" in prompt

    assert "After 12 exchanges" in llm_prompt


def test_user_simulator_lint_catches_role_drift_and_internal_tokens():
    from pi_bench.users.user import _lint_generated_user_message

    assert _lint_generated_user_message("###STOP###") == []
    assert _lint_generated_user_message(
        "I will go ahead and process your refund now."
    )
    assert _lint_generated_user_message("How can I help you today?")
    assert _lint_generated_user_message("I called record_decision for this.")
    assert _lint_generated_user_message("Thanks.\n###STOP###")
    assert not _lint_generated_user_message(
        "Why can't I get a refund to my card? That's how I paid."
    )
    assert not _lint_generated_user_message(
        "Your policy says damaged items get a full refund, so why are you blocking this?"
    )
    assert not _lint_generated_user_message(
        "I'll escalate this complaint to the BBB if you cannot explain the blocker."
    )
