"""Step definitions for hooks.feature."""

import importlib
import pathlib

import pytest
from pytest_bdd import scenarios, given, when, then, parsers

pytestmark = pytest.mark.skip(reason="pi_plugins package not yet implemented")

scenarios("../features/hooks.feature")


# --- Helpers ---


def _make_domain():
    """Create a minimal domain for hook testing."""
    from pi_bench.environment import create_environment

    def _get_env():
        return create_environment(
            domain_name="hook_test",
            policy="Be helpful.",
            tools={"noop": lambda db: "ok"},
            db={"items": []},
            tool_schemas=[{"name": "noop", "parameters": {}}],
        )

    return {
        "name": "hook_test",
        "get_environment": _get_env,
        "tasks": [
            {
                "id": "t1",
                "description": "Test task",
                "evaluation_criteria": {"reward_basis": []},
            }
        ],
    }


class StubAgent:
    """Minimal agent that sends one tool call then stops."""

    def __init__(self):
        self._step = 0

    def set_seed(self, seed):
        pass

    def init_state(self, benchmark_context, tools, message_history=None):
        return {}

    def generate(self, message, state):
        self._step += 1
        if self._step == 1:
            return {
                "role": "assistant",
                "tool_calls": [{"name": "noop", "id": "c1", "arguments": {}}],
            }, state
        return {"role": "assistant", "content": "Done. [STOP]"}, state

    def is_stop(self, msg):
        return "[STOP]" in msg.get("content", "")

    def stop(self, message, state):
        pass


class StubUser:
    """Minimal user that says one thing then stops on second call."""

    def __init__(self):
        self._step = 0

    def set_seed(self, seed):
        pass

    def init_state(self, scenario, message_history=None):
        self._step = 0
        return {}

    def generate(self, message, state):
        self._step += 1
        if self._step >= 2:
            return {"role": "user", "content": "Thanks [STOP]"}, state
        return {"role": "user", "content": "Please help me."}, state

    def is_stop(self, msg):
        return "[STOP]" in msg.get("content", "")

    def stop(self, message, state):
        pass


# --- Hook Registration ---


@given("a hook registry with valid hook points", target_fixture="registry")
def hook_registry():
    from pi_plugins.registry import HookRegistry

    return HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])


@when(
    'a plugin registers callables for "on_init" and "after_tool_call"',
    target_fixture="registry_after_register",
)
def register_two_hooks(registry):
    registry.register("on_init", lambda ctx: None)
    registry.register("after_tool_call", lambda ctx: None)
    return registry


@then("the registry contains both hooks")
def registry_has_both(registry_after_register):
    hooks = registry_after_register.to_dict()
    assert len(hooks.get("on_init", [])) == 1
    assert len(hooks.get("after_tool_call", [])) == 1


# --- No plugins = identical ---


@given("a task and domain with no plugins registered", target_fixture="no_plugin_setup")
def no_plugin_setup():
    return {"domain": _make_domain(), "agent": StubAgent(), "user": StubUser()}


@when(
    "I run the simulation twice with the same seed",
    target_fixture="two_runs",
)
def run_twice(no_plugin_setup):
    from pi_bench.orchestrator import run

    domain = no_plugin_setup["domain"]
    results = []
    for _ in range(2):
        agent = StubAgent()
        user = StubUser()
        env = domain["get_environment"]()
        task = domain["tasks"][0]
        sim = run(agent=agent, user=user, env=env, task=task, seed=42)
        results.append(sim)
    return results


@then("both runs produce the same trajectory and reward")
def same_trajectory(two_runs):
    msgs_a = [(m["role"], m.get("content", "")) for m in two_runs[0]["messages"]]
    msgs_b = [(m["role"], m.get("content", "")) for m in two_runs[1]["messages"]]
    assert msgs_a == msgs_b


# --- Non-existent hook ---


@when('a plugin registers for "on_banana"', target_fixture="bad_register_error")
def register_bad_hook(registry):
    with pytest.raises(ValueError) as exc_info:
        registry.register("on_banana", lambda ctx: None)
    return exc_info


@then("a registration error is raised immediately")
def error_raised(bad_register_error):
    assert "on_banana" in str(bad_register_error.value)


# --- All callables called ---


@given(
    'two plugins registered for "after_agent_call"',
    target_fixture="multi_plugin_setup",
)
def two_plugins_registered():
    from pi_plugins.registry import HookRegistry

    call_log = []
    registry = HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])
    registry.register("after_agent_call", lambda ctx: call_log.append("A"))
    registry.register("after_agent_call", lambda ctx: call_log.append("B"))
    return {"registry": registry, "call_log": call_log}


@when(
    "the simulation runs and the agent responds",
    target_fixture="multi_plugin_result",
)
def run_with_two_plugins(multi_plugin_setup):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    hooks = multi_plugin_setup["registry"].to_dict()
    sim = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42, hooks=hooks,
    )
    return {"sim": sim, "call_log": multi_plugin_setup["call_log"]}


@then("both plugin callables have been invoked")
def both_called(multi_plugin_result):
    assert "A" in multi_plugin_result["call_log"]
    assert "B" in multi_plugin_result["call_log"]


# --- Read-only snapshot ---


@given(
    'a plugin registered for "after_tool_call" that modifies its context',
    target_fixture="mutator_setup",
)
def mutator_plugin():
    from pi_plugins.registry import HookRegistry

    def mutator(ctx):
        ctx["trajectory"] = []  # Attempt to wipe trajectory
        ctx["INJECTED"] = True

    registry = HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])
    registry.register("after_tool_call", mutator)
    return registry


@when("a tool call occurs during simulation", target_fixture="mutator_result")
def run_with_mutator(mutator_setup):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    hooks = mutator_setup.to_dict()
    sim = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42, hooks=hooks,
    )
    return sim


@then("the modification does not affect the orchestrator state")
def state_unchanged(mutator_result):
    # Trajectory should NOT be empty — mutator's change was on a copy
    assert len(mutator_result["messages"]) > 0


# --- Exception safety ---


@given(
    'a plugin registered for "after_agent_call" that raises an exception',
    target_fixture="crasher_setup",
)
def crasher_plugin():
    from pi_plugins.registry import HookRegistry

    registry = HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])
    registry.register("after_agent_call", lambda ctx: 1 / 0)
    return registry


@when("the simulation runs", target_fixture="crasher_result")
def run_with_crasher(crasher_setup):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    hooks = crasher_setup.to_dict()
    sim = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42, hooks=hooks,
    )
    return sim


@then("the simulation completes normally despite the plugin error")
def simulation_completed(crasher_result):
    assert crasher_result["termination_reason"] is not None
    assert len(crasher_result["messages"]) > 0


# --- Invocation order ---


@given(
    'three plugins registered for "on_done" in order A B C',
    target_fixture="order_setup",
)
def three_plugins_ordered():
    from pi_plugins.registry import HookRegistry

    order_log = []
    registry = HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])
    registry.register("on_done", lambda ctx: order_log.append("A"))
    registry.register("on_done", lambda ctx: order_log.append("B"))
    registry.register("on_done", lambda ctx: order_log.append("C"))
    return {"registry": registry, "order_log": order_log}


@when("the simulation completes", target_fixture="order_result")
def run_for_order(order_setup):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    hooks = order_setup["registry"].to_dict()
    sim = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42, hooks=hooks,
    )
    return {"sim": sim, "order_log": order_setup["order_log"]}


@then("the plugins were invoked in order A B C")
def order_correct(order_result):
    assert order_result["order_log"] == ["A", "B", "C"]


# --- Cannot modify trajectory ---


@given(
    'a plugin registered for "after_agent_call" that attempts to alter trajectory',
    target_fixture="trajectory_tamper_setup",
)
def trajectory_tamper_plugin():
    from pi_plugins.registry import HookRegistry

    def tamper(ctx):
        if "trajectory" in ctx:
            ctx["trajectory"].clear()

    registry = HookRegistry([
        "on_init", "before_agent_call", "after_agent_call",
        "before_user_call", "after_user_call",
        "before_tool_call", "after_tool_call", "on_done",
    ])
    registry.register("after_agent_call", tamper)
    return registry


@when("the simulation runs to completion", target_fixture="tamper_result")
def run_with_tamper(trajectory_tamper_setup):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    hooks = trajectory_tamper_setup.to_dict()
    sim = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42, hooks=hooks,
    )
    return sim


@then("the trajectory is identical to a run without the plugin")
def trajectory_matches_clean(tamper_result):
    from pi_bench.orchestrator import run

    domain = _make_domain()
    env = domain["get_environment"]()
    clean = run(
        agent=StubAgent(), user=StubUser(), env=env,
        task=domain["tasks"][0], seed=42,
    )
    tampered_msgs = [(m["role"], m.get("content", "")) for m in tamper_result["messages"]]
    clean_msgs = [(m["role"], m.get("content", "")) for m in clean["messages"]]
    assert tampered_msgs == clean_msgs


# --- No pi_plugins import in pi_bench ---


@given("the pi_bench source directory", target_fixture="pi_bench_src")
def pi_bench_source():
    return pathlib.Path(__file__).parent.parent.parent / "workspace" / "src" / "pi_bench"


@when(
    "I scan all Python files for imports of pi_plugins",
    target_fixture="import_scan",
)
def scan_imports(pi_bench_src):
    violations = []
    for py_file in pi_bench_src.rglob("*.py"):
        content = py_file.read_text()
        for i, line in enumerate(content.splitlines(), 1):
            if "pi_plugins" in line and ("import" in line or "from" in line):
                violations.append(f"{py_file}:{i}: {line.strip()}")
    return violations


@then("no imports are found")
def no_violations(import_scan):
    assert import_scan == [], f"Found pi_plugins imports in pi_bench: {import_scan}"
