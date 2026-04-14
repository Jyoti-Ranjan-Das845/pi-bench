"""Step definitions for orchestrator.feature.

Uses stub agents and users that implement the AgentProtocol / UserProtocol
interfaces. The stubs are deterministic — no LLM calls.
"""

import pytest
from pytest_bdd import scenarios, given, when, then, parsers

scenarios("../features/orchestrator.feature")


# --- Stub factories ---


def _stub_agent_text(text, stop_after=None):
    """Agent that always responds with text. Optionally stops after N exchanges."""
    call_count = {"n": 0}

    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-text"

        def init_state(self, benchmark_context, tools, message_history=None):
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            call_count["n"] += 1
            state["messages"].append(message)
            if stop_after and call_count["n"] >= stop_after:
                return _make_assistant_msg(content="###STOP###"), state
            return _make_assistant_msg(content=text), state

        def is_stop(self, message):
            return message.get("content") == "###STOP###"

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_agent_tool_calls(tool_calls, then_text="Done", then_stop=False):
    """Agent that makes tool calls first, then responds with text."""
    phase = {"done_tools": False}

    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-tools"

        def init_state(self, benchmark_context, tools, message_history=None):
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            state["messages"].append(message)
            if not phase["done_tools"]:
                phase["done_tools"] = True
                return _make_assistant_msg(tool_calls=tool_calls), state
            if then_stop:
                return _make_assistant_msg(content="###STOP###"), state
            return _make_assistant_msg(content=then_text), state

        def is_stop(self, message):
            return message.get("content") == "###STOP###"

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_agent_error():
    """Agent that raises on generate."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-error"

        def init_state(self, benchmark_context, tools, message_history=None):
            return {}

        def generate(self, message, state):
            raise RuntimeError("Agent generation failed")

        def is_stop(self, message):
            return False

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_agent_always_bad_tool():
    """Agent that always calls a nonexistent tool."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-bad-tool"

        def init_state(self, benchmark_context, tools, message_history=None):
            return {"messages": []}

        def generate(self, message, state):
            state["messages"].append(message)
            return _make_assistant_msg(
                tool_calls=[{"id": "bad", "name": "fake_tool", "arguments": {}}]
            ), state

        def is_stop(self, message):
            return False

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_user_text(text, stop_after=None):
    """User that always responds with text. Optionally stops after N exchanges."""
    call_count = {"n": 0}

    class StubUser:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-user-text"

        def init_state(self, scenario, message_history=None):
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            call_count["n"] += 1
            state["messages"].append(message)
            if stop_after and call_count["n"] >= stop_after:
                return _make_user_msg(content="###STOP###"), state
            return _make_user_msg(content=text), state

        def is_stop(self, message):
            c = message.get("content", "")
            return c in ("###STOP###", "###TRANSFER###")

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubUser()


def _stub_user_tool_calls(tool_calls, then_stop=True):
    """User that makes tool calls first, then stops."""
    phase = {"done_tools": False}

    class StubUser:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-user-tools"

        def init_state(self, scenario, message_history=None):
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            state["messages"].append(message)
            if not phase["done_tools"]:
                phase["done_tools"] = True
                return _make_user_msg(tool_calls=tool_calls), state
            return _make_user_msg(content="###STOP###"), state

        def is_stop(self, message):
            c = message.get("content", "")
            return c in ("###STOP###", "###TRANSFER###")

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubUser()


def _stub_user_error():
    """User that raises on generate."""
    class StubUser:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-user-error"

        def init_state(self, scenario, message_history=None):
            return {}

        def generate(self, message, state):
            raise RuntimeError("User generation failed")

        def is_stop(self, message):
            return False

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubUser()


def _stub_user_transfer():
    """User that sends transfer signal."""
    class StubUser:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-user-transfer"

        def init_state(self, scenario, message_history=None):
            return {"messages": []}

        def generate(self, message, state):
            state["messages"].append(message)
            return _make_user_msg(content="###TRANSFER###"), state

        def is_stop(self, message):
            c = message.get("content", "")
            return c in ("###STOP###", "###TRANSFER###")

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubUser()


# --- Message helpers ---


def _make_assistant_msg(content=None, tool_calls=None):
    msg = {"role": "assistant"}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def _make_user_msg(content=None, tool_calls=None):
    msg = {"role": "user"}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def _make_task():
    return {
        "id": "test_task_1",
        "description": "Test task",
        "user_scenario": {"persona": "A test user", "instructions": "Ask for help"},
        "initial_state": {},
        "evaluation_criteria": {},
    }


def _make_mock_env():
    from domains.mock import get_environment
    return get_environment()


def _make_mock_env_with_user_tools():
    from domains.mock import get_environment_with_user_tools
    return get_environment_with_user_tools()


def test_solo_trigger_prefers_ticket_over_initial_user_message():
    from pi_bench.orchestrator.core import init

    agent = _stub_agent_text("ok")
    env = {
        "domain_name": "mock",
        "policy": "Policy text",
        "tool_schemas": [],
        "tools": {},
        "db": {},
        "solo_mode": True,
    }
    task = {
        "id": "task_1",
        "description": "Task description",
        "ticket": "Prepared ticket",
        "user_scenario": {"initial_user_message": "Initial customer request"},
    }

    state = init(agent=agent, user=None, env=env, task=task, solo=True)

    assert state.current_message == {"role": "user", "content": "Prepared ticket"}
    assert state.trajectory == [state.current_message]


def test_solo_trigger_falls_back_to_initial_user_message():
    from pi_bench.orchestrator.core import init

    agent = _stub_agent_text("ok")
    env = {
        "domain_name": "mock",
        "policy": "Policy text",
        "tool_schemas": [],
        "tools": {},
        "db": {},
        "solo_mode": True,
    }
    task = {
        "id": "task_1",
        "description": "Task description",
        "user_scenario": {"initial_user_message": "Initial customer request"},
    }

    state = init(agent=agent, user=None, env=env, task=task, solo=True)

    assert state.current_message == {
        "role": "user",
        "content": "Initial customer request",
    }


# --- Given: agents ---


@given(
    parsers.re(r'a stub agent that always responds with text "(?P<text>[^"]+)"$'),
    target_fixture="agent",
)
def agent_always_text(text):
    return _stub_agent_text(text)


@given("a stub agent that records its seed", target_fixture="agent")
def agent_records_seed():
    return _stub_agent_text("hello")


@given("a stub agent that responds with text then stops", target_fixture="agent")
def agent_text_then_stops():
    return _stub_agent_text("I'm done", stop_after=2)


@given(
    parsers.re(
        r'a stub agent that calls tool "(?P<tool>[^"]+)" then responds with text$'
    ),
    target_fixture="agent",
)
def agent_calls_tool_then_text(tool):
    return _stub_agent_tool_calls(
        [{"id": "tc1", "name": tool, "arguments": {}}],
        then_text="Here are the results",
    )


@given(
    parsers.re(
        r'a stub agent that calls tool "(?P<tool>[^"]+)" then responds with text then stops$'
    ),
    target_fixture="agent",
)
def agent_calls_tool_then_text_then_stops(tool):
    return _stub_agent_tool_calls(
        [{"id": "tc1", "name": tool, "arguments": {}}],
        then_text="Done",
        then_stop=True,
    )


@given(
    parsers.re(
        r'a stub agent that calls tools "(?P<t1>[^"]+)" and "(?P<t2>[^"]+)" simultaneously$'
    ),
    target_fixture="agent",
)
def agent_calls_two_tools(t1, t2):
    return _stub_agent_tool_calls(
        [
            {"id": "tc1", "name": t1, "arguments": {}},
            {"id": "tc2", "name": t2, "arguments": {}},
        ],
        then_text="Done",
        then_stop=True,
    )


@given(
    parsers.re(
        r'a stub agent that sends stop signal after (?P<n>\d+) exchanges$'
    ),
    target_fixture="agent",
)
def agent_stops_after_n(n):
    return _stub_agent_text("working...", stop_after=int(n))


@given("a stub agent that raises an error on generate", target_fixture="agent")
def agent_errors():
    return _stub_agent_error()


@given('a stub agent that always calls nonexistent tool "fake_tool"', target_fixture="agent")
def agent_bad_tool():
    return _stub_agent_always_bad_tool()


@given(
    parsers.re(
        r'a stub agent that calls tool "(?P<tool>[^"]+)" then responds with stop$'
    ),
    target_fixture="agent",
)
def agent_calls_tool_then_stops(tool):
    return _stub_agent_tool_calls(
        [{"id": "tc1", "name": tool, "arguments": {}}],
        then_stop=True,
    )


# --- Given: users ---


@given(
    parsers.re(r'a stub user that always responds with text "(?P<text>[^"]+)"$'),
    target_fixture="user",
)
def user_always_text(text):
    return _stub_user_text(text)


@given("a stub user that records its seed", target_fixture="user")
def user_records_seed():
    return _stub_user_text("hello")


@given("a stub user that responds with text then stops", target_fixture="user")
def user_text_then_stops():
    return _stub_user_text("thanks", stop_after=2)


@given(
    parsers.re(
        r'a stub user that sends stop signal after (?P<n>\d+) exchange$'
    ),
    target_fixture="user",
)
def user_stops_after_n(n):
    return _stub_user_text("ok", stop_after=int(n))


@given("a stub user that sends transfer signal", target_fixture="user")
def user_transfers():
    return _stub_user_transfer()


@given(
    parsers.re(
        r'a stub user that calls tool "(?P<tool>[^"]+)" then stops$'
    ),
    target_fixture="user",
)
def user_calls_tool_then_stops(tool):
    return _stub_user_tool_calls(
        [{"id": "utc1", "name": tool, "arguments": {}, "requestor": "user"}],
    )


@given("a stub user that raises an error on generate", target_fixture="user")
def user_errors():
    return _stub_user_error()


# --- Given: environment ---


@given("a mock environment", target_fixture="env")
def mock_env():
    return _make_mock_env()


@given("a mock environment with user tools", target_fixture="env")
def mock_env_user_tools():
    return _make_mock_env_with_user_tools()


@given("a mock environment in solo mode", target_fixture="env")
def mock_env_solo():
    from pi_bench.environment import set_solo_mode
    env = _make_mock_env()
    set_solo_mode(env, True)
    return env


@given("a mock environment with observer in audit-only mode", target_fixture="env")
def mock_env_with_observer():
    from pi_bench.observer import create_observer
    from pi_bench.trace import TraceRecorder
    env = _make_mock_env()
    trace = TraceRecorder()
    observer = create_observer(env=env, trace=trace, mode="audit_only")
    return {"env": env, "observer": observer, "trace": trace}


# --- When ---


@when(
    parsers.re(r'I run the orchestrator for (?P<n>\d+) step$'),
    target_fixture="result",
)
def run_for_n_steps(agent, user, env, n):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=user, env=env, task=task, max_steps=int(n))


@when("I run the orchestrator to completion", target_fixture="result")
def run_to_completion(agent, user, env):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=user, env=env, task=task, max_steps=50)


@when(
    parsers.re(r'I initialize the orchestrator with seed (?P<seed>\d+)$'),
    target_fixture="result",
)
def init_with_seed(agent, user, env, seed):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=user, env=env, task=task, seed=int(seed), max_steps=2)


@when(
    parsers.re(r'I run the orchestrator with max_steps (?P<n>\d+)$'),
    target_fixture="result",
)
def run_with_max_steps(agent, user, env, n):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=user, env=env, task=task, max_steps=int(n))


@when(
    parsers.re(r'I run the orchestrator with max_errors (?P<n>\d+)$'),
    target_fixture="result",
)
def run_with_max_errors(agent, user, env, n):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=user, env=env, task=task, max_steps=50, max_errors=int(n))


@when("I run the orchestrator in solo mode", target_fixture="result")
def run_solo(agent, env):
    from pi_bench.orchestrator import run
    task = _make_task()
    return run(agent=agent, user=None, env=env, task=task, max_steps=50, solo=True)


# --- Then: initialization ---


@then('the first message is from agent to user')
def first_msg_from_agent(result):
    msgs = result["messages"]
    assert len(msgs) > 0
    assert msgs[0]["role"] == "assistant"


@then(parsers.re(r'the first message content is "(?P<text>[^"]+)"$'))
def first_msg_content(result, text):
    assert result["messages"][0]["content"] == text


@then(parsers.re(r'the agent seed is (?P<seed>\d+)$'))
def agent_seed_is(agent, seed):
    assert agent.seed == int(seed)


@then(parsers.re(r'the user seed is (?P<seed>\d+)$'))
def user_seed_is(user, seed):
    assert user.seed == int(seed)


# --- Then: routing ---


@then("the trajectory alternates between agent and user messages")
def trajectory_alternates(result):
    msgs = [m for m in result["messages"] if m["role"] in ("assistant", "user")]
    for i in range(1, len(msgs)):
        assert msgs[i]["role"] != msgs[i - 1]["role"], (
            f"Messages {i-1} and {i} both have role {msgs[i]['role']}"
        )


@then("at least one user message follows an agent text message")
def user_follows_agent_text(result):
    msgs = result["messages"]
    for i in range(1, len(msgs)):
        if msgs[i]["role"] == "user" and msgs[i - 1]["role"] == "assistant":
            if "content" in msgs[i - 1]:
                return
    pytest.fail("No user message follows an agent text message")


@then(parsers.re(r'the trajectory contains a tool result for "(?P<tool>[^"]+)"$'))
def trajectory_has_tool_result(result, tool):
    msgs = result["messages"]
    for m in msgs:
        if m["role"] == "tool" and m.get("name") == tool:
            return
        if m["role"] == "multi_tool":
            for sub in m.get("tool_messages", []):
                if sub.get("name") == tool:
                    return
    pytest.fail(f"No tool result for {tool} in trajectory")


@then(parsers.re(r'the tool result requestor is "(?P<requestor>[^"]+)"$'))
def tool_result_requestor(result, requestor):
    msgs = result["messages"]
    for m in msgs:
        if m["role"] == "tool":
            assert m["requestor"] == requestor
            return
    pytest.fail("No tool result in trajectory")


@then("the message after the tool result goes to agent not user")
def after_tool_result_goes_to_agent(result):
    msgs = result["messages"]
    for i, m in enumerate(msgs):
        if m["role"] == "tool" and m.get("requestor") == "assistant":
            # Next non-tool message should be from agent (it received the result)
            for j in range(i + 1, len(msgs)):
                if msgs[j]["role"] in ("assistant", "user"):
                    assert msgs[j]["role"] == "assistant"
                    return
    pytest.fail("Could not verify tool result routing")


@then(
    parsers.re(
        r'the trajectory contains tool results for both "(?P<t1>[^"]+)" and "(?P<t2>[^"]+)"$'
    ),
)
def trajectory_has_both_tools(result, t1, t2):
    found = set()
    for m in result["messages"]:
        if m["role"] == "tool":
            found.add(m.get("name"))
        if m["role"] == "multi_tool":
            for sub in m.get("tool_messages", []):
                found.add(sub.get("name"))
    assert t1 in found, f"{t1} not in {found}"
    assert t2 in found, f"{t2} not in {found}"


# --- Then: termination ---


@then(parsers.re(r'the termination reason is "(?P<reason>[^"]+)"$'))
def termination_reason(result, reason):
    assert result["termination_reason"] == reason


# --- Then: step counting ---


@then("the simulation completes normally despite environment steps counting toward total")
def limit_checks_skip_env(result):
    # The simulation should complete with agent_stop (not max_steps),
    # proving that env steps didn't trigger the step limit prematurely.
    # The agent does: tool call → env step → text → stop.
    # All steps count toward step_count, but limits only check on non-env steps.
    assert result["termination_reason"] == "agent_stop"
    # Verify there were tool results (env steps happened)
    tool_msgs = [m for m in result["messages"] if m["role"] in ("tool", "multi_tool")]
    assert len(tool_msgs) > 0


# --- Then: trajectory ---


@then(parsers.re(r'the trajectory has at least (?P<n>\d+) messages$'))
def trajectory_min_messages(result, n):
    assert len(result["messages"]) >= int(n)


@then("messages are ordered by turn index")
def messages_ordered(result):
    indices = [m.get("turn_index", i) for i, m in enumerate(result["messages"])]
    assert indices == sorted(indices)


# --- Then: metadata ---


@then("the result has a task_id")
def result_has_task_id(result):
    assert "task_id" in result and result["task_id"]


@then("the result has start and end timestamps")
def result_has_timestamps(result):
    assert "start_time" in result
    assert "end_time" in result
    assert result["end_time"] >= result["start_time"]


@then("the result has a termination reason")
def result_has_termination(result):
    assert "termination_reason" in result


@then("the result has the full message trajectory")
def result_has_messages(result):
    assert "messages" in result
    assert len(result["messages"]) > 0


# --- Then: solo mode ---


@then("no user messages appear in the trajectory")
def no_user_messages(result):
    for m in result["messages"]:
        assert m["role"] != "user", f"Found user message: {m}"


@then("tool calls still execute normally")
def tool_calls_execute(result):
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert len(tool_msgs) > 0


# --- Then: observer ---


@then("the observer trace has entries for all tool calls")
def observer_has_entries(env):
    trace = env["trace"]
    assert len(trace.entries) > 0


@then("the observer trace entry count matches the trajectory tool call count")
def observer_count_matches(result, env):
    trace = env["trace"]
    tool_msgs = [m for m in result["messages"] if m["role"] == "tool"]
    assert len(trace.entries) == len(tool_msgs)


# --- Then: composite orchestrator checks ---


@then("the trajectory contains agent text, user text, and tool results")
def trajectory_has_all_roles(result):
    roles = {m["role"] for m in result["messages"]}
    assert "assistant" in roles, f"No agent messages. Roles found: {roles}"
    assert "user" in roles, f"No user messages. Roles found: {roles}"
    tool_roles = roles & {"tool", "multi_tool"}
    assert tool_roles, f"No tool results. Roles found: {roles}"


@then("tool results were routed back to the agent who called them")
def tool_results_routed_to_caller(result):
    msgs = result["messages"]
    for i, m in enumerate(msgs):
        if m["role"] in ("tool", "multi_tool"):
            # Find next non-tool message — should be from agent (the caller)
            for j in range(i + 1, len(msgs)):
                if msgs[j]["role"] in ("assistant", "user"):
                    assert msgs[j]["role"] == "assistant", (
                        f"Tool result at {i} followed by {msgs[j]['role']} at {j}, expected assistant"
                    )
                    break


@then(parsers.re(r'the simulation ends with termination reason "(?P<reason>[^"]+)"$'))
def simulation_ends_with_reason(result, reason):
    assert result["termination_reason"] == reason


@then(parsers.re(r'running with agent stop produces "(?P<reason>[^"]+)"$'))
def running_agent_stop(env, reason):
    from pi_bench.orchestrator import run
    agent = _stub_agent_text("hello", stop_after=1)
    user = _stub_user_text("hi")
    task = _make_task()
    result = run(agent=agent, user=user, env=env, task=task, max_steps=50)
    assert result["termination_reason"] == reason


@then(parsers.re(r'running with user stop produces "(?P<reason>[^"]+)"$'))
def running_user_stop(env, reason):
    from pi_bench.orchestrator import run
    agent = _stub_agent_text("hello")
    user = _stub_user_text("bye", stop_after=1)
    task = _make_task()
    result = run(agent=agent, user=user, env=env, task=task, max_steps=50)
    assert result["termination_reason"] == reason


@then(parsers.re(r'running with agent error produces "(?P<reason>[^"]+)"$'))
def running_agent_error(env, reason):
    from pi_bench.orchestrator import run
    agent = _stub_agent_error()
    user = _stub_user_text("hi")
    task = _make_task()
    result = run(agent=agent, user=user, env=env, task=task, max_steps=50)
    assert result["termination_reason"] == reason


@then(parsers.re(r'running with max errors produces "(?P<reason>[^"]+)"$'))
def running_max_errors(env, reason):
    from pi_bench.orchestrator import run
    agent = _stub_agent_always_bad_tool()
    user = _stub_user_text("hi")
    task = _make_task()
    result = run(agent=agent, user=user, env=env, task=task, max_steps=50, max_errors=2)
    assert result["termination_reason"] == reason


@then(parsers.re(r'solo mode agent sending text produces "(?P<reason>[^"]+)"$'))
def solo_text_produces(env, reason):
    from pi_bench.orchestrator import run
    # Agent that only sends text (no tool calls, no stop) keeps looping in solo mode.
    agent = _stub_agent_text("just chatting")
    task = _make_task()
    result = run(agent=agent, user=None, env=env, task=task, max_steps=50, solo=True)
    assert result["termination_reason"] == reason


@then("the result contains ordered messages with turn indices")
def result_has_ordered_turn_indices(result):
    msgs = result["messages"]
    assert len(msgs) > 0, "No messages in result"
    indices = [m.get("turn_index") for m in msgs]
    assert all(idx is not None for idx in indices), f"Some messages missing turn_index: {indices}"
    assert indices == list(range(len(msgs))), f"Turn indices not sequential: {indices}"


@then("the result has task_id, timestamps, termination reason, and costs")
def result_has_metadata(result):
    assert "task_id" in result and result["task_id"], "Missing task_id"
    assert "start_time" in result, "Missing start_time"
    assert "end_time" in result, "Missing end_time"
    assert result["end_time"] >= result["start_time"], "end_time before start_time"
    assert "termination_reason" in result, "Missing termination_reason"
    assert "duration" in result, "Missing duration"
