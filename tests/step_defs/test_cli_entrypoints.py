"""CLI public entrypoint tests."""

from types import SimpleNamespace

import pytest


def _domain_args(**overrides):
    base = {
        "domain": "retail",
        "agent": None,
        "agent_llm": "stub",
        "agent_llm_args": None,
        "user_llm": None,
        "user_llm_args": None,
        "solo": True,
        "task_ids": None,
        "num_tasks": None,
        "num_trials": 1,
        "concurrency": 1,
        "seed": 42,
        "retry_failed": 0,
        "save_to": None,
        "agent_max_steps": 5,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cli_resolves_paths_from_workspace_when_cwd_differs(monkeypatch, tmp_path):
    from pi_bench import cli

    workspace = tmp_path / "workspace"
    scenarios = workspace / "scenarios"
    other = tmp_path / "other"
    scenarios.mkdir(parents=True)
    other.mkdir()

    monkeypatch.chdir(other)
    monkeypatch.setattr(cli, "_default_workspace_root", lambda: workspace)

    assert cli._resolve_cli_path("scenarios") == scenarios


def test_run_domain_exits_nonzero_when_any_scenario_fails(monkeypatch):
    from pi_bench import cli
    from pi_bench import metrics
    from pi_bench import runner
    from pi_bench.evaluator import report as report_mod
    from pi_bench import scenario_loader

    monkeypatch.setattr(cli, "_build_agent", lambda args: object())
    monkeypatch.setattr(cli, "_build_user", lambda args: None)
    monkeypatch.setattr(cli, "_default_workspace_root", lambda: ".")
    monkeypatch.setattr(
        scenario_loader,
        "load_domain",
        lambda domain, workspace_root=None: {"name": domain, "tasks": []},
    )
    monkeypatch.setattr(
        runner,
        "run_domain",
        lambda **kwargs: {
            "simulations": [
                {
                    "task_id": "scen_fail",
                    "label": "DENY",
                    "leaderboard_primary": "policy_interpretation",
                    "termination_reason": "agent_stop",
                    "step_count": 1,
                    "reward_info": {
                        "all_passed": False,
                        "dimensions": {},
                        "outcome_results": [],
                    },
                    "trace": None,
                }
            ]
        },
    )
    monkeypatch.setattr(metrics, "compute_metrics", lambda results: {})
    monkeypatch.setattr(metrics, "compute_repeatability", lambda results: {})
    monkeypatch.setattr(metrics, "format_metrics_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        report_mod,
        "build_report",
        lambda **kwargs: {
            "scenario_id": kwargs["scenario_id"],
            "all_passed": kwargs["eval_result"].get("all_passed", False),
        },
    )
    monkeypatch.setattr(report_mod, "format_report", lambda report: "failure")
    monkeypatch.setattr(report_mod, "format_batch_summary", lambda reports: "")

    with pytest.raises(SystemExit) as exc:
        cli.cmd_run_domain(_domain_args())

    assert exc.value.code == 1


def test_run_domain_exits_zero_when_all_scenarios_pass(monkeypatch):
    from pi_bench import cli
    from pi_bench import metrics
    from pi_bench import runner
    from pi_bench.evaluator import report as report_mod
    from pi_bench import scenario_loader

    monkeypatch.setattr(cli, "_build_agent", lambda args: object())
    monkeypatch.setattr(cli, "_build_user", lambda args: None)
    monkeypatch.setattr(cli, "_default_workspace_root", lambda: ".")
    monkeypatch.setattr(
        scenario_loader,
        "load_domain",
        lambda domain, workspace_root=None: {"name": domain, "tasks": []},
    )
    monkeypatch.setattr(
        runner,
        "run_domain",
        lambda **kwargs: {
            "simulations": [
                {
                    "task_id": "scen_pass",
                    "label": "ALLOW",
                    "leaderboard_primary": "policy_interpretation",
                    "termination_reason": "agent_stop",
                    "step_count": 1,
                    "reward_info": {
                        "all_passed": True,
                        "dimensions": {},
                        "outcome_results": [],
                    },
                    "trace": None,
                }
            ]
        },
    )
    monkeypatch.setattr(metrics, "compute_metrics", lambda results: {})
    monkeypatch.setattr(metrics, "compute_repeatability", lambda results: {})
    monkeypatch.setattr(metrics, "format_metrics_summary", lambda *args, **kwargs: "")
    monkeypatch.setattr(
        report_mod,
        "build_report",
        lambda **kwargs: {
            "scenario_id": kwargs["scenario_id"],
            "all_passed": kwargs["eval_result"].get("all_passed", False),
        },
    )
    monkeypatch.setattr(report_mod, "format_report", lambda report: "ok")
    monkeypatch.setattr(report_mod, "format_batch_summary", lambda reports: "")

    with pytest.raises(SystemExit) as exc:
        cli.cmd_run_domain(_domain_args())

    assert exc.value.code == 0
