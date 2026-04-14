#!/usr/bin/env python3
"""Run all active scenarios locally through the shared runner.

This is a convenience entrypoint for end-to-end verification. It keeps the
public CLI surface focused while still allowing a full-set local smoke run.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from pi_bench.agents import LiteLLMAgent
from pi_bench.env import load_env
from pi_bench.metrics import compute_metrics, compute_repeatability, format_metrics_summary
from pi_bench.runner import run_domain
from pi_bench.scenario_loader import default_workspace_root, discover_scenarios, load
from pi_bench.users.user import LiteLLMUser


def _load_full_set(scenarios_dir: Path, workspace_root: Path) -> dict:
    tasks = []
    for scenario_path in discover_scenarios(scenarios_dir):
        loaded = load(scenario_path, workspace_root=workspace_root)
        task = loaded["task"]
        task["_scenario_path"] = str(scenario_path)
        tasks.append(task)

    if not tasks:
        raise FileNotFoundError(f"No pibench_scenario_v1 files found in {scenarios_dir}")

    def get_environment(task: dict | None = None) -> dict:
        if task is None or "_scenario_path" not in task:
            raise ValueError("Full-set runner requires a scenario task")
        return load(task["_scenario_path"], workspace_root=workspace_root)["env"]

    return {"name": "full_set", "tasks": tasks, "get_environment": get_environment}


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Run all active pi-bench scenarios locally")
    parser.add_argument("--scenarios-dir", default=None)
    parser.add_argument("--agent-llm", default="gpt-4o-mini")
    parser.add_argument("--user-llm", default="gpt-4.1-mini")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--save-to", required=True)
    args = parser.parse_args()
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Put it in .env or export it first.")
    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")

    workspace_root = default_workspace_root()
    scenarios_dir = Path(args.scenarios_dir) if args.scenarios_dir else workspace_root / "scenarios"
    domain = _load_full_set(scenarios_dir, workspace_root)

    def agent_factory():
        return LiteLLMAgent(model_name=args.agent_llm)

    def user_factory():
        return LiteLLMUser(model_name=args.user_llm)

    agent = agent_factory()
    user = user_factory()
    result = run_domain(
        domain=domain,
        agent=agent,
        user=user,
        num_trials=1,
        seed=args.seed,
        max_concurrency=args.concurrency,
        save_to=args.save_to,
        max_steps=args.max_steps,
        solo=False,
        agent_factory=agent_factory if args.concurrency > 1 else None,
        user_factory=user_factory if args.concurrency > 1 else None,
    )

    metrics = compute_metrics(result["simulations"])
    repeatability = compute_repeatability(result["simulations"])
    print(format_metrics_summary(metrics, repeatability))
    print(json.dumps({"saved_to": args.save_to, "metrics": result.get("metrics", {})}, indent=2))

    if not all(sim.get("all_passed", False) for sim in result["simulations"]):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
