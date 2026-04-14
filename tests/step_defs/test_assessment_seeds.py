"""Seed derivation tests for runner and A2A assessment."""

from pathlib import Path

from pi_bench.a2a import assessment
from pi_bench.runner.seeds import derive_seed, derive_trial_seeds


def test_derive_trial_seeds_is_order_independent():
    tasks_a = [{"id": "task_b"}, {"id": "task_a"}]
    tasks_b = [{"id": "task_x"}, {"id": "task_b"}, {"id": "task_a"}]

    seeds_a = {
        task["id"]: seed
        for task, _trial, seed in derive_trial_seeds(1234, tasks_a, 1)
    }
    seeds_b = {
        task["id"]: seed
        for task, _trial, seed in derive_trial_seeds(1234, tasks_b, 1)
    }

    assert seeds_a["task_a"] == seeds_b["task_a"]
    assert seeds_a["task_b"] == seeds_b["task_b"]


def test_run_assessment_uses_stable_scenario_seed(monkeypatch, tmp_path):
    scenario_a = tmp_path / "scen_a.json"
    scenario_b = tmp_path / "scen_b.json"
    scenario_x = tmp_path / "scen_x.json"
    for path in (scenario_a, scenario_b, scenario_x):
        path.write_text("{}")

    observed: dict[str, int] = {}

    def fake_run_single_scenario(**kwargs):
        observed[Path(kwargs["scenario_path"]).stem] = kwargs["seed"]
        return {
            "scenario_id": Path(kwargs["scenario_path"]).stem,
            "label": "DENY",
            "status": "completed",
            "all_passed": True,
            "outcome_results": [],
            "dimensions": {},
            "canonical_decision": "DENY",
            "event_flags": {},
            "duration": 0.0,
        }

    monkeypatch.setattr(assessment, "_run_single_scenario", fake_run_single_scenario)

    monkeypatch.setattr(
        assessment,
        "discover_scenarios",
        lambda _path: [scenario_a, scenario_b],
    )
    assessment.run_assessment("http://example.com", {"scenarios_dir": tmp_path, "seed": 777})
    seed_a_without_prefix = observed["scen_a"]
    seed_b_without_prefix = observed["scen_b"]

    observed.clear()
    monkeypatch.setattr(
        assessment,
        "discover_scenarios",
        lambda _path: [scenario_x, scenario_a, scenario_b],
    )
    assessment.run_assessment("http://example.com", {"scenarios_dir": tmp_path, "seed": 777})

    assert observed["scen_a"] == seed_a_without_prefix == derive_seed(777, "scen_a")
    assert observed["scen_b"] == seed_b_without_prefix == derive_seed(777, "scen_b")


def test_run_assessment_builds_trial_work(monkeypatch, tmp_path):
    scenario_a = tmp_path / "scen_a.json"
    scenario_a.write_text("{}")

    observed: list[tuple[int, int]] = []

    def fake_run_single_scenario(**kwargs):
        observed.append((kwargs["trial"], kwargs["seed"]))
        return {
            "scenario_id": Path(kwargs["scenario_path"]).stem,
            "trial": kwargs["trial"],
            "label": "DENY",
            "status": "completed",
            "all_passed": True,
            "outcome_results": [],
            "dimensions": {},
            "canonical_decision": "DENY",
            "event_flags": {},
            "duration": 0.0,
        }

    monkeypatch.setattr(assessment, "_run_single_scenario", fake_run_single_scenario)
    monkeypatch.setattr(assessment, "discover_scenarios", lambda _path: [scenario_a])

    results = assessment.run_assessment(
        "http://example.com",
        {"scenarios_dir": tmp_path, "seed": 777, "num_trials": 2, "concurrency": 2},
    )

    assert sorted(observed) == [
        (0, derive_seed(777, "scen_a", 0)),
        (1, derive_seed(777, "scen_a", 1)),
    ]
    assert [r["trial"] for r in results] == [0, 1]
