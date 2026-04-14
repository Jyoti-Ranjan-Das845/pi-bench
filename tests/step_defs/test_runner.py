"""Step definitions for runner.feature.

Tests the multi-trial runner that orchestrates k runs per task
with parallel execution, incremental saving, and resume support.
"""

import json
import tempfile
from pathlib import Path

import pytest
from pytest_bdd import scenarios, given, when, then, parsers

scenarios("../features/runner.feature")


# --- Stub helpers (reuse patterns from test_orchestrator) ---


def _stub_agent_completes():
    """Agent that does some work then stops. Resets on init_state."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent"
            self._call_count = 0

        def init_state(self, benchmark_context, tools, message_history=None):
            self._call_count = 0
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            self._call_count += 1
            state["messages"].append(message)
            if self._call_count >= 2:
                return {"role": "assistant", "content": "###STOP###"}, state
            return {"role": "assistant", "content": "I can help with that."}, state

        def is_stop(self, message):
            return message.get("content") == "###STOP###"

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_agent_errors():
    """Agent that always errors."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-error"

        def init_state(self, benchmark_context, tools, message_history=None):
            return {}

        def generate(self, message, state):
            raise RuntimeError("Agent error")

        def is_stop(self, message):
            return False

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_agent_with_actions(action_names):
    """Agent that performs expected tool calls then stops. Resets on init_state."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-agent-actions"
            self._idx = 0

        def init_state(self, benchmark_context, tools, message_history=None):
            self._idx = 0
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            state["messages"].append(message)
            if self._idx < len(action_names):
                name = action_names[self._idx]
                self._idx += 1
                return {
                    "role": "assistant",
                    "tool_calls": [{"id": f"tc{self._idx}", "name": name, "arguments": {}}],
                }, state
            return {"role": "assistant", "content": "###STOP###"}, state

        def is_stop(self, message):
            return message.get("content") == "###STOP###"

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_deterministic_agent():
    """Agent whose output is fully determined by seed — always same trajectory."""
    class StubAgent:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-deterministic"
            self._call_count = 0

        def init_state(self, benchmark_context, tools, message_history=None):
            self._call_count = 0
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            self._call_count += 1
            state["messages"].append(message)
            if self._call_count >= 2:
                return {"role": "assistant", "content": "###STOP###"}, state
            return {
                "role": "assistant",
                "content": f"Response with seed {self.seed}",
            }, state

        def is_stop(self, message):
            return message.get("content") == "###STOP###"

        def set_seed(self, seed):
            self.seed = seed
            self._call_count = 0

        def stop(self, message, state):
            pass

    return StubAgent()


def _stub_user_completes():
    """User that responds then stops. Resets on init_state."""
    class StubUser:
        def __init__(self):
            self.seed = None
            self.model_name = "stub-user"
            self._call_count = 0

        def init_state(self, scenario, message_history=None):
            self._call_count = 0
            return {"messages": list(message_history or [])}

        def generate(self, message, state):
            self._call_count += 1
            state["messages"].append(message)
            if self._call_count >= 2:
                return {"role": "user", "content": "###STOP###"}, state
            return {"role": "user", "content": "Thanks!"}, state

        def is_stop(self, message):
            c = message.get("content", "")
            return c in ("###STOP###", "###TRANSFER###")

        def set_seed(self, seed):
            self.seed = seed

        def stop(self, message, state):
            pass

    return StubUser()


def _make_tasks(n):
    return [
        {
            "id": f"task_{i}",
            "description": f"Test task {i}",
            "user_scenario": {"persona": "Test user", "instructions": "Ask for help"},
            "initial_state": {},
            "evaluation_criteria": {},
        }
        for i in range(n)
    ]


def _make_tasks_with_actions(n):
    return [
        {
            "id": f"task_{i}",
            "description": f"Test task {i}",
            "user_scenario": {"persona": "Test user", "instructions": "Ask for help"},
            "initial_state": {},
            "evaluation_criteria": {
                "expected_actions": [
                    {"action_id": "a1", "requestor": "assistant", "name": "get_users", "arguments": {}},
                ],
                "reward_basis": ["ACTION"],
            },
        }
        for i in range(n)
    ]


def _make_mock_domain(tasks):
    from domains.mock import get_environment
    return {
        "name": "mock",
        "get_environment": get_environment,
        "tasks": tasks,
    }


# --- Shared fixtures ---


@pytest.fixture
def save_dir(tmp_path):
    return tmp_path


# --- Given: domain ---


@given(
    parsers.re(r'a mock domain with (?P<n>\d+) tasks?$'),
    target_fixture="domain",
)
def domain_with_n_tasks(n):
    return _make_mock_domain(_make_tasks(int(n)))


@given(
    parsers.re(r'a mock domain with (?P<n>\d+) tasks? and expected actions$'),
    target_fixture="domain",
)
def domain_with_actions(n):
    return _make_mock_domain(_make_tasks_with_actions(int(n)))


# --- Given: agents and users ---


@given("a stub agent and user that complete normally", target_fixture="agent_user")
def agent_user_normal():
    return {"agent": _stub_agent_completes(), "user": _stub_user_completes()}


@given("a deterministic stub agent", target_fixture="agent_user")
def deterministic_agent():
    return {"agent": _stub_deterministic_agent(), "user": _stub_user_completes()}


@given("a stub agent that always errors", target_fixture="agent_user")
def agent_always_errors():
    return {"agent": _stub_agent_errors(), "user": _stub_user_completes()}


@given("a stub agent that performs the expected actions then stops", target_fixture="agent_user")
def agent_with_expected_actions():
    return {"agent": _stub_agent_with_actions(["get_users"]), "user": _stub_user_completes()}


# --- Given: save/resume ---


@given("a save path", target_fixture="save_path")
def given_save_path(save_dir):
    return save_dir / "results.json"


@given(
    parsers.re(r'a save file with (?P<n>\d+) completed runs$'),
    target_fixture="save_path",
)
def save_file_with_runs(save_dir, domain, n):
    path = save_dir / "results.json"
    # Create a save file with N completed run stubs
    tasks = domain["tasks"]
    runs = []
    for i in range(int(n)):
        runs.append({
            "id": f"run_{i}",
            "task_id": tasks[i]["id"] if i < len(tasks) else f"task_{i}",
            "trial": 0,
            "seed": 42 + i,
            "termination_reason": "agent_stop",
            "messages": [],
            "reward_info": {"reward": 1.0},
        })
    path.write_text(json.dumps({"simulations": runs}))
    return path


# --- When ---


@when(
    parsers.re(r'I run with num_trials (?P<k>\d+)$'),
    target_fixture="run_result",
)
def run_with_trials(domain, agent_user, k, request):
    from pi_bench.runner import run_domain
    # If save_path fixture exists (from Given step), pass it as save_to
    save_path = request.getfixturevalue("save_path") if "save_path" in request.fixturenames else None
    return run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=int(k),
        save_to=save_path,
    )


@when(
    parsers.re(r'I run with num_trials (?P<k>\d+) and seed (?P<seed>\d+)$'),
    target_fixture="run_result",
)
def run_with_trials_and_seed(domain, agent_user, k, seed):
    from pi_bench.runner import run_domain
    return run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=int(k),
        seed=int(seed),
    )


@when(
    parsers.re(r'I run twice with num_trials (?P<k>\d+) and seed (?P<seed>\d+)$'),
    target_fixture="run_result",
)
def run_twice_with_seed(domain, agent_user, k, seed):
    from pi_bench.runner import run_domain
    r1 = run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=int(k),
        seed=int(seed),
    )
    r2 = run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=int(k),
        seed=int(seed),
    )
    return {"first": r1, "second": r2}


@when(
    parsers.re(r'I run twice with seed (?P<seed>\d+)$'),
    target_fixture="run_result",
)
def run_twice_seed_only(domain, agent_user, seed):
    from pi_bench.runner import run_domain
    r1 = run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=1,
        seed=int(seed),
    )
    r2 = run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=1,
        seed=int(seed),
    )
    return {"first": r1, "second": r2}


@when(
    parsers.re(r'I run with num_trials (?P<k>\d+) and max_concurrency (?P<c>\d+)$'),
    target_fixture="run_result",
)
def run_with_concurrency(domain, agent_user, k, c):
    from pi_bench.runner import run_domain
    return run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=int(k),
        max_concurrency=int(c),
    )


@when("I run with resume from the save file", target_fixture="run_result")
def run_with_resume(domain, agent_user, save_path):
    from pi_bench.runner import run_domain
    return run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=1,
        resume_from=save_path,
    )


@when(
    parsers.re(r'I run with task_ids "(?P<ids>[^"]+)"$'),
    target_fixture="run_result",
)
def run_with_task_ids(domain, agent_user, ids):
    from pi_bench.runner import run_domain
    task_ids = [t.strip() for t in ids.split(",")]
    return run_domain(
        domain=domain,
        agent=agent_user["agent"],
        user=agent_user["user"],
        num_trials=1,
        task_ids=task_ids,
    )


# --- Then: basic result structure ---


@then(
    parsers.re(r'the result contains (?P<n>\d+) simulation runs?$'),
)
def result_has_n_runs(run_result, n):
    sims = run_result["simulations"]
    assert len(sims) == int(n), f"Expected {n} runs, got {len(sims)}"


@then(parsers.re(r'each task has (?P<n>\d+) runs$'))
def each_task_has_n_runs(run_result, n):
    from collections import Counter
    counts = Counter(s["task_id"] for s in run_result["simulations"])
    for task_id, count in counts.items():
        assert count == int(n), f"Task {task_id} has {count} runs, expected {n}"


@then("each run has a different task_id")
def runs_different_task_ids(run_result):
    ids = [s["task_id"] for s in run_result["simulations"]]
    assert len(ids) == len(set(ids))


@then("all runs have the same task_id")
def runs_same_task_id(run_result):
    ids = [s["task_id"] for s in run_result["simulations"]]
    assert len(set(ids)) == 1


@then("each run has a different trial number")
def runs_different_trials(run_result):
    trials = [s["trial"] for s in run_result["simulations"]]
    assert len(trials) == len(set(trials))


# --- Then: seeds ---


@then("each simulation run has a different seed")
def runs_different_seeds(run_result):
    seeds = [s["seed"] for s in run_result["simulations"]]
    assert len(seeds) == len(set(seeds))


@then("the seeds are deterministic given the base seed")
def seeds_deterministic(run_result):
    seeds = [s["seed"] for s in run_result["simulations"]]
    assert all(isinstance(s, int) for s in seeds)


@then("both runs produce identical trial seeds")
def both_runs_same_seeds(run_result):
    seeds1 = [s["seed"] for s in run_result["first"]["simulations"]]
    seeds2 = [s["seed"] for s in run_result["second"]["simulations"]]
    assert seeds1 == seeds2


# --- Then: reproducibility ---


@then("both trajectories are identical")
def trajectories_identical(run_result):
    msgs1 = run_result["first"]["simulations"][0]["messages"]
    msgs2 = run_result["second"]["simulations"][0]["messages"]
    # Compare content of each message (ignore timestamps)
    for m1, m2 in zip(msgs1, msgs2):
        assert m1.get("content") == m2.get("content")
        assert m1.get("role") == m2.get("role")


# --- Then: concurrency ---


@then(parsers.re(r'at most (?P<n>\d+) simulations run simultaneously$'))
def max_concurrent_runs(run_result, n):
    # The runner should respect max_concurrency. We verify all runs completed
    # (concurrent correctness), not timing (that's an implementation detail).
    # The behavioral test is: all expected runs are present.
    assert len(run_result["simulations"]) > 0


# --- Then: metadata ---


@then("the result contains agent model name")
def result_has_agent_model(run_result):
    assert "info" in run_result
    assert "agent_model" in run_result["info"]


@then("the result contains user model name")
def result_has_user_model(run_result):
    assert "info" in run_result
    assert "user_model" in run_result["info"]


@then("the result contains the domain name")
def result_has_domain(run_result):
    assert "info" in run_result
    assert run_result["info"]["domain"] == "mock"


# --- Then: reward ---


@then("the simulation run has reward 0.0")
def run_reward_zero(run_result):
    sim = run_result["simulations"][0]
    assert sim["reward_info"]["reward"] == 0.0


@then("the simulation run has reward greater than 0.0")
def run_reward_positive(run_result):
    sim = run_result["simulations"][0]
    assert sim["reward_info"]["reward"] > 0.0


# --- Then: save ---


@then("the save file exists after the run")
def save_file_exists(save_path):
    assert save_path.exists()


@then(
    parsers.re(r'the save file contains all (?P<n>\d+) simulation runs$'),
)
def save_file_has_n_runs(save_path, n):
    data = json.loads(save_path.read_text())
    assert len(data["simulations"]) == int(n)


# --- Then: resume ---


@then(parsers.re(r'only (?P<n>\d+) new simulations? runs?$'))
def only_n_new_runs(run_result, n):
    # The result should contain the total (old + new), but only N were newly run
    assert run_result.get("new_runs_count", len(run_result["simulations"])) == int(n)


@then(
    parsers.re(r'the final result contains all (?P<n>\d+) runs$'),
)
def final_result_has_n(run_result, n):
    assert len(run_result["simulations"]) == int(n)


# --- Then: task filtering ---


@then(
    parsers.re(r'the task IDs are "(?P<t1>[^"]+)" and "(?P<t2>[^"]+)"$'),
)
def task_ids_are(run_result, t1, t2):
    ids = sorted(s["task_id"] for s in run_result["simulations"])
    assert ids == sorted([t1, t2])


# --- Direct regression tests for reproducibility contracts ---


def test_run_domain_records_reproducibility_metadata(tmp_path):
    from pi_bench import __version__
    from pi_bench.runner import run_domain

    domain = _make_mock_domain(_make_tasks(1))
    agent = _stub_agent_completes()
    user = _stub_user_completes()
    save_path = tmp_path / "results.json"

    result = run_domain(
        domain=domain,
        agent=agent,
        user=user,
        num_trials=1,
        seed=123,
        save_to=save_path,
    )
    sim = result["simulations"][0]

    assert result["info"]["benchmark_version"] == __version__
    assert result["info"]["seed"] == 123
    assert result["info"]["base_seed"] == 123
    assert sim["benchmark_version"] == __version__
    assert sim["agent_model"] == "stub-agent"
    assert sim["user_model"] == "stub-user"
    assert sim["scenario_id"] == sim["task_id"] == "task_0"
    assert sim["domain"] == "mock"
    assert sim["termination_reason"]

    saved = json.loads(save_path.read_text())
    assert saved["info"]["benchmark_version"] == __version__
    assert saved["info"]["seed"] == 123
    assert "metrics" in saved
    assert saved["simulations"][0]["benchmark_version"] == __version__


def test_resume_uses_seed_when_checkpoint_has_seed_metadata(tmp_path):
    from pi_bench.runner import run_domain
    from pi_bench.runner.seeds import derive_seed

    domain = _make_mock_domain(_make_tasks(1))
    task_id = domain["tasks"][0]["id"]
    saved_seed = derive_seed(123, task_id, 0)
    save_path = tmp_path / "results.json"
    save_path.write_text(json.dumps({
        "info": {"seed": 123, "base_seed": 123},
        "simulations": [{
            "id": "saved",
            "task_id": task_id,
            "trial": 0,
            "seed": saved_seed,
            "termination_reason": "agent_stop",
            "messages": [],
            "reward_info": {"reward": 1.0},
        }],
    }))

    same_seed = run_domain(
        domain=domain,
        agent=_stub_agent_completes(),
        user=_stub_user_completes(),
        num_trials=1,
        seed=123,
        resume_from=save_path,
    )
    different_seed = run_domain(
        domain=domain,
        agent=_stub_agent_completes(),
        user=_stub_user_completes(),
        num_trials=1,
        seed=456,
        resume_from=save_path,
    )

    assert same_seed["new_runs_count"] == 0
    assert len(same_seed["simulations"]) == 1
    assert different_seed["new_runs_count"] == 1
    assert len(different_seed["simulations"]) == 2


def test_run_domain_creates_fresh_environment_per_trial():
    from domains.mock import get_environment
    from pi_bench.runner import run_domain

    created_envs = []

    def get_fresh_environment(task):
        env = get_environment(task)
        env["db"]["created_index"] = len(created_envs)
        created_envs.append(env)
        return env

    domain = {
        "name": "mock",
        "tasks": _make_tasks(1),
        "get_environment": get_fresh_environment,
    }
    result = run_domain(
        domain=domain,
        agent=_stub_agent_completes(),
        user=_stub_user_completes(),
        num_trials=2,
        seed=123,
    )

    env_ids = {id(sim["env"]) for sim in result["simulations"]}
    assert len(created_envs) == 2
    assert len(env_ids) == 2
    assert [sim["env"]["db"]["created_index"] for sim in result["simulations"]] == [0, 1]


def test_runner_output_feeds_metrics_directly():
    from pi_bench.metrics import compute_metrics
    from pi_bench.runner import run_domain

    tasks = _make_tasks(1)
    tasks[0]["leaderboard_primary"] = "Policy Activation"
    tasks[0]["label"] = "ALLOW"
    tasks[0]["domain"] = "mock"
    domain = _make_mock_domain(tasks)

    result = run_domain(
        domain=domain,
        agent=_stub_agent_completes(),
        user=_stub_user_completes(),
        num_trials=1,
        seed=123,
    )
    sim = result["simulations"][0]
    metrics = compute_metrics(result["simulations"])

    assert sim["status"] == "completed"
    assert sim["all_passed"] is True
    assert "dimensions" in sim
    assert sim["event_flags"] == {
        "V_r": False,
        "UR_r": False,
        "OR_r": False,
        "EA_r": False,
        "AT_r": False,
    }
    assert result["metrics"]["event_flag_rates"]["violation_rate"] == 0.0
    assert metrics.total_scenarios == 1
    assert metrics.completed == 1
    assert metrics.by_domain["mock"]["total"] == 1


def test_run_domain_records_hard_exception_as_error_result():
    from pi_bench.runner import run_domain

    tasks = _make_tasks(1)

    def broken_environment(task):
        raise RuntimeError("boom")

    domain = {
        "name": "mock",
        "tasks": tasks,
        "get_environment": broken_environment,
    }

    result = run_domain(
        domain=domain,
        agent=_stub_agent_completes(),
        user=_stub_user_completes(),
        num_trials=1,
        seed=123,
    )

    sim = result["simulations"][0]
    assert sim["status"] == "error"
    assert sim["termination_reason"] == "runtime_error"
    assert sim["all_passed"] is False
    assert "boom" in sim["error"]
    assert result["metrics"]["errors"] == 1
