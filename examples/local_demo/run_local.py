#!/usr/bin/env python3
"""Local demo — run pi-bench scenarios with LiteLLMAgent directly (no A2A).

Usage:
    # Single scenario
    python examples/local_demo/run_local.py \
        --scenario scenarios/retail/scen_020_standard_refund.json

    # All scenarios in a directory
    python examples/local_demo/run_local.py \
        --scenarios-dir scenarios/ --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

from pi_bench.agents import LiteLLMAgent
from pi_bench.decision import CanonicalDecision, resolve
from pi_bench.env import load_env
from pi_bench.evaluator import evaluate
from pi_bench.evaluator.llm_judge import clear_judge_cache
from pi_bench.evaluator.scenario_validator import validate_scenario
from pi_bench.event_flags import compute_flags
from pi_bench.observer import create_observer
from pi_bench.orchestrator.core import run as orchestrator_run
from pi_bench.scenario_loader import discover_scenarios, load
from pi_bench.trace import TraceRecorder

logger = logging.getLogger(__name__)

_EMPTY_FLAGS = {"V_r": False, "UR_r": False, "OR_r": False, "EA_r": False, "AT_r": False}


def _error_result(scenario_id: str, label: str, error: str, duration: float = 0) -> dict:
    return {
        "scenario_id": scenario_id,
        "label": label,
        "status": "error",
        "error": error,
        "all_passed": False,
        "outcome_results": [],
        "canonical_decision": "",
        "event_flags": dict(_EMPTY_FLAGS),
        "duration": duration,
    }


def run_single_scenario(
    scenario_path: Path,
    model: str = "gpt-4o-mini",
    workspace_root: str | Path | None = None,
    max_steps: int = 50,
    seed: int = 42,
    observer_mode: str = "audit_only",
) -> dict:
    """Run a single scenario using LiteLLMAgent locally."""
    start = time.time()

    loaded = load(scenario_path, workspace_root=workspace_root)
    task = loaded["task"]
    env = loaded["env"]
    label = loaded["label"]
    scenario_id = loaded["scenario_id"]
    forbidden_tools = loaded["forbidden_tools"]

    # Validate scenario
    scenario_data = json.loads(Path(scenario_path).read_text())
    validation_errors = validate_scenario(scenario_data)
    if validation_errors:
        for err in validation_errors:
            logger.error("Validation error in %s: %s", scenario_id, err)
        return _error_result(
            scenario_id, label,
            f"Validation failed: {'; '.join(validation_errors)}",
            time.time() - start,
        )

    user_sim = scenario_data.get("user_simulation", {})
    initial_message = user_sim.get("initial_user_message", "")
    env_setup = scenario_data.get("environment_setup", {})

    # Construct ticket
    ticket_parts = [task["description"]]
    if initial_message:
        ticket_parts.append(f"\nCustomer request:\n{initial_message}")
    if env_setup.get("now"):
        ticket_parts.append(f"\nCurrent time: {env_setup['now']}")
    task["ticket"] = "\n".join(ticket_parts)

    clear_judge_cache()

    # Create agent
    agent = LiteLLMAgent(model_name=model)

    # Create trace and observer
    trace = TraceRecorder()
    observer = create_observer(
        env, trace,
        forbidden_tools=set(forbidden_tools) if forbidden_tools else None,
        mode=observer_mode,
    )

    # Run simulation in solo mode
    try:
        sim = orchestrator_run(
            agent=agent,
            user=None,
            env=env,
            task=task,
            max_steps=max_steps,
            seed=seed,
            solo=True,
            observer=observer,
        )
    except Exception as exc:
        return _error_result(scenario_id, label, str(exc), time.time() - start)

    # Record messages to trace
    for msg in sim.get("messages", []):
        if msg.get("role") == "assistant" and msg.get("content"):
            trace.add_message("assistant", msg["content"])
        elif msg.get("role") == "user" and msg.get("content"):
            trace.add_message("user", msg["content"])

    sim["trace"] = trace
    sim["env"] = env

    # Evaluate
    eval_result = evaluate(task, sim, domain={"get_environment": lambda: env})
    all_passed = eval_result["all_passed"]
    outcome_results = eval_result["outcome_results"]
    semantic_score = eval_result["semantic_score"]

    # Resolve canonical decision
    decision_result = resolve(trace)
    canonical_decision = (
        decision_result.decision
        if isinstance(decision_result, CanonicalDecision)
        else "NONE"
    )

    # Compute event flags
    evaluation_criteria = task["evaluation_criteria"]
    policy_checks = evaluation_criteria.get("policy_checks", [])
    flags = compute_flags(
        scenario_label=label,
        trace=trace,
        canonical_decision=canonical_decision,
        policy_checks=policy_checks,
        forbidden_tools=forbidden_tools,
        messages=sim.get("messages", []),
    )

    duration = time.time() - start

    return {
        "scenario_id": scenario_id,
        "label": label,
        "status": "completed",
        "termination_reason": sim.get("termination_reason", "unknown"),
        "step_count": sim.get("step_count", 0),
        "canonical_decision": canonical_decision,
        "all_passed": all_passed,
        "semantic_score": semantic_score,
        "outcome_results": outcome_results,
        "event_flags": {
            "V_r": flags.V_r,
            "UR_r": flags.UR_r,
            "OR_r": flags.OR_r,
            "EA_r": flags.EA_r,
            "AT_r": flags.AT_r,
        },
        "duration": duration,
        "tool_calls": trace.tool_names(),
    }


def main() -> None:
    load_env()
    parser = argparse.ArgumentParser(description="Run pi-bench scenarios locally with LiteLLMAgent")
    parser.add_argument("--scenario", type=str, help="Path to a single scenario JSON file")
    parser.add_argument("--scenarios-dir", type=str, help="Directory of scenario files")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LiteLLM model name")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-steps", type=int, default=50, help="Max orchestrator steps per scenario")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if not args.scenario and not args.scenarios_dir:
        parser.error("Provide --scenario or --scenarios-dir")

    # Collect scenario paths
    if args.scenario:
        scenario_paths = [Path(args.scenario)]
    else:
        scenario_paths = discover_scenarios(Path(args.scenarios_dir))
        if not scenario_paths:
            print(f"No scenarios found in {args.scenarios_dir}")
            sys.exit(1)

    print(f"Running {len(scenario_paths)} scenario(s) with model={args.model}")

    results = []
    for path in scenario_paths:
        print(f"\n{'='*60}")
        print(f"Scenario: {path.stem}")
        print(f"{'='*60}")

        result = run_single_scenario(
            scenario_path=path,
            model=args.model,
            max_steps=args.max_steps,
            seed=args.seed,
        )
        results.append(result)

        status = result["status"]
        if status == "error":
            print(f"  Status: ERROR - {result.get('error', 'unknown')}")
        else:
            print(f"  Status: {status}")
            print(f"  Label: {result['label']}")
            print(f"  Decision: {result['canonical_decision']}")
            print(f"  All passed: {result['all_passed']}")
            print(f"  Steps: {result.get('step_count', '?')}")
            print(f"  Duration: {result['duration']:.1f}s")
            if result.get("outcome_results"):
                for o in result["outcome_results"]:
                    icon = "PASS" if o.get("passed") else "FAIL"
                    print(f"    [{icon}] {o.get('type', '?')}: {o.get('detail', '')}")

    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    passed = sum(1 for r in results if r.get("all_passed"))
    errors = sum(1 for r in results if r["status"] == "error")
    total = len(results)
    print(f"  Total: {total}  Passed: {passed}  Failed: {total - passed - errors}  Errors: {errors}")


if __name__ == "__main__":
    main()
