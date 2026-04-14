"""Pi-bench CLI — run scenarios from the command line.

Usage:
    pi run scenarios/retail/scen_040_final_sale_restocking_tradeoff.json --agent-llm gpt-4o
    pi run-domain finra --agent-llm gpt-4o --num-trials 4 --concurrency 4
    pi list
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path


def _default_workspace_root() -> Path:
    from pi_bench.scenario_loader import default_workspace_root

    return default_workspace_root()


def _resolve_cli_path(path: str | Path) -> Path:
    """Resolve CLI paths from cwd first, then the project workspace."""
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p
    candidate = _default_workspace_root() / p
    return candidate if candidate.exists() else p


def _parse_kv_args(kv_list: list[str] | None) -> dict:
    """Parse key=value argument pairs into a dict."""
    if not kv_list:
        return {}
    result = {}
    for item in kv_list:
        if "=" not in item:
            raise ValueError(f"Invalid key=value arg: {item!r}")
        key, value = item.split("=", 1)
        # Auto-convert numeric and boolean values
        if value.lower() in ("true", "false"):
            result[key] = value.lower() == "true"
        else:
            try:
                result[key] = int(value)
            except ValueError:
                try:
                    result[key] = float(value)
                except ValueError:
                    result[key] = value
    return result


def _load_agent_class(agent_spec: str):
    """Dynamically load an agent class from 'module:ClassName' spec."""
    if ":" not in agent_spec:
        raise ValueError(
            f"Agent spec must be 'module:ClassName', got: {agent_spec!r}"
        )
    module_path, class_name = agent_spec.rsplit(":", 1)
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _build_agent(args: argparse.Namespace):
    """Build an agent from CLI args."""
    llm_args = _parse_kv_args(getattr(args, "agent_llm_args", None))

    if args.agent:
        # Dynamic agent class
        agent_cls = _load_agent_class(args.agent)
        return agent_cls(model_name=args.agent_llm, **llm_args)

    # Default: LiteLLMAgent
    from pi_bench.agents.litellm_agent import LiteLLMAgent
    return LiteLLMAgent(model_name=args.agent_llm, **llm_args)


def _build_user(args: argparse.Namespace):
    """Build a user simulator from CLI args. Returns None for solo mode."""
    if getattr(args, "solo", True):
        return None

    user_llm = getattr(args, "user_llm", None)
    if not user_llm:
        from pi_bench.users.scripted_user import ScriptedUser
        return ScriptedUser()

    from pi_bench.users.user import LiteLLMUser
    user_args = _parse_kv_args(getattr(args, "user_llm_args", None))
    return LiteLLMUser(model_name=user_llm, **user_args)


def cmd_run(args: argparse.Namespace) -> None:
    """Run a single scenario."""
    from pi_bench.evaluator import evaluate
    from pi_bench.observer import create_observer
    from pi_bench.orchestrator import run as orchestrator_run
    from pi_bench.scenario_loader import load
    from pi_bench.trace import TraceRecorder

    scenario_path = _resolve_cli_path(args.scenario)
    loaded = load(scenario_path)
    task = loaded["task"]
    env = loaded["env"]
    label = loaded["label"]
    scenario_id = loaded["scenario_id"]
    forbidden_tools = loaded["forbidden_tools"]

    agent = _build_agent(args)
    user = _build_user(args)
    solo = user is None
    trace = TraceRecorder()
    observer = create_observer(
        env, trace,
        forbidden_tools=set(forbidden_tools) if forbidden_tools else None,
        mode=args.observer_mode,
    )

    print(f"Running {scenario_id} (label={label}) with {args.agent_llm}...")
    sim = orchestrator_run(
        agent=agent, user=user, env=env, task=task,
        max_steps=args.agent_max_steps, seed=args.seed,
        solo=solo, observer=observer,
    )
    sim["trace"] = trace
    sim["env"] = env

    eval_result = evaluate(task, sim, domain={
        "get_environment": lambda task=None: load(scenario_path)["env"]
    })
    from pi_bench.event_flags import compute_flags

    flags = compute_flags(
        scenario_label=label,
        trace=trace,
        canonical_decision=eval_result.get("canonical_decision") or "NONE",
        policy_checks=task.get("evaluation_criteria", {}).get("policy_checks", []),
        forbidden_tools=forbidden_tools,
        messages=sim.get("messages", []),
    )
    event_flags = {
        "V_r": flags.V_r,
        "UR_r": flags.UR_r,
        "OR_r": flags.OR_r,
        "EA_r": flags.EA_r,
        "AT_r": flags.AT_r,
    }

    # Build and print detailed failure report
    from pi_bench.evaluator.report import build_report, format_report
    report = build_report(
        scenario_id=scenario_id,
        label=label,
        leaderboard_primary=task.get("leaderboard_primary", ""),
        eval_result=eval_result,
        termination_reason=sim.get("termination_reason", ""),
        step_count=sim.get("step_count", 0),
        tool_calls=trace.tool_names() if trace else [],
    )
    report["event_flags"] = event_flags
    print()
    print(format_report(report))

    # Save results if requested
    if args.save_to:
        from pi_bench.metrics import compute_metrics, metrics_to_dict

        scenario_result = {
            "scenario_id": scenario_id,
            "domain": task.get("domain", ""),
            "domain_name": task.get("domain_name", ""),
            "label": label,
            "leaderboard_primary": task.get("leaderboard_primary", ""),
            "status": "completed",
            "reward": eval_result.get("reward"),
            "all_passed": eval_result.get("all_passed", False),
            "semantic_score": eval_result.get("semantic_score", 0.0),
            "canonical_decision": eval_result.get("canonical_decision"),
            "decision_channel": eval_result.get("decision_channel"),
            "decision_valid": eval_result.get("decision_valid", False),
            "decision_error": eval_result.get("decision_error"),
            "event_flags": event_flags,
            "dimensions": eval_result.get("dimensions", {}),
        }
        metrics = compute_metrics([scenario_result])
        report["outcome_results"] = eval_result["outcome_results"]
        report["metrics"] = metrics_to_dict(metrics)
        report["messages"] = sim.get("messages", [])
        Path(args.save_to).write_text(json.dumps(report, indent=2, default=str))
        print(f"\n  Saved to {args.save_to}")

    sys.exit(0 if eval_result["all_passed"] else 1)


def cmd_run_domain(args: argparse.Namespace) -> None:
    """Run all scenarios in a domain."""
    from pi_bench.metrics import compute_metrics, format_metrics_summary, compute_repeatability
    from pi_bench.runner import run_domain
    from pi_bench.scenario_loader import load_domain

    workspace_root = _default_workspace_root()
    domain = load_domain(args.domain, workspace_root=workspace_root)
    agent = _build_agent(args)
    user = _build_user(args)
    solo = user is None

    # Emitter hook — external observability can inject via emitter kwarg
    emitter = None

    def agent_factory():
        return _build_agent(args)

    def user_factory():
        return _build_user(args)

    # Parse task IDs
    task_ids = None
    if args.task_ids:
        task_ids = [t.strip() for t in args.task_ids.split(",")]

    print(f"Running domain={args.domain} agent-llm={args.agent_llm} trials={args.num_trials}")
    result = run_domain(
        domain=domain,
        agent=agent,
        user=user,
        num_trials=args.num_trials,
        max_concurrency=args.concurrency,
        agent_factory=agent_factory if args.concurrency > 1 else None,
        user_factory=user_factory if args.concurrency > 1 and user else None,
        solo=solo,
        seed=args.seed,
        max_steps=args.agent_max_steps,
        save_to=args.save_to,
        task_ids=task_ids,
        num_tasks=args.num_tasks,
        retry_failed=args.retry_failed,
        emitter=emitter,
    )

    # Build per-scenario results and failure reports in one pass
    from pi_bench.evaluator.report import build_report, format_report, format_batch_summary
    scenario_results = []
    reports = []
    for sim in result["simulations"]:
        reward = sim.get("reward_info", {})
        term = sim.get("termination_reason", "")

        scenario_results.append({
            "scenario_id": sim.get("task_id", "?"),
            "domain": sim.get("domain", ""),
            "domain_name": sim.get("domain_name", ""),
            "label": sim.get("label", ""),
            "leaderboard_primary": sim.get("leaderboard_primary", ""),
            "status": "completed" if term in ("agent_stop", "user_stop", "max_steps", "agent_error") else "error",
            "reward": reward.get("reward"),
            "all_passed": reward.get("all_passed", False),
            "semantic_score": reward.get("semantic_score", 0.0),
            "canonical_decision": reward.get("canonical_decision"),
            "decision_channel": reward.get("decision_channel"),
            "decision_valid": reward.get("decision_valid", False),
            "decision_error": reward.get("decision_error"),
            "event_flags": sim.get("event_flags", {}),
            "dimensions": reward.get("dimensions", {}),
        })

        report = build_report(
            scenario_id=sim.get("task_id", "?"),
            label=sim.get("label", ""),
            leaderboard_primary=sim.get("leaderboard_primary", ""),
            eval_result=reward,
            termination_reason=term,
            step_count=sim.get("step_count", 0),
            tool_calls=sim.get("trace").tool_names() if sim.get("trace") else [],
        )
        reports.append(report)

    # Emit episode complete (runner already emits per-scenario)
    if emitter:
        emitter.on_episode_complete({
            "total": len(scenario_results),
            "passed": sum(1 for r in scenario_results if r.get("all_passed")),
            "compliance": sum(1 for r in scenario_results if r.get("all_passed")) / max(len(scenario_results), 1),
        })
        emitter.close()

    # Print leaderboard + dimension failure analysis
    m = compute_metrics(scenario_results)
    rep = compute_repeatability(scenario_results)
    print(format_metrics_summary(m, rep, reports=reports))

    # Print batch failure summary
    print(format_batch_summary(reports))

    # Print individual failure details for failed scenarios
    failed_reports = [r for r in reports if not r["all_passed"]]
    if failed_reports:
        print(f"\n{'='*70}")
        print(f"DETAILED FAILURE REPORTS ({len(failed_reports)} scenarios)")
        print(f"{'='*70}")
        for r in failed_reports:
            print()
            print(format_report(r))

    all_passed = all(r.get("all_passed", False) for r in scenario_results)
    sys.exit(0 if all_passed else 1)


def cmd_list(args: argparse.Namespace) -> None:
    """List available scenarios."""
    from pi_bench.scenario_loader import discover_scenarios

    scenarios_dir = _resolve_cli_path(args.scenarios_dir)
    paths = discover_scenarios(scenarios_dir)

    print(f"{'SCENARIO':<50} {'LABEL':<10} {'COLUMN'}")
    print("-" * 90)
    for p in paths:
        data = json.loads(p.read_text())
        sid = data.get("meta", {}).get("scenario_id", p.stem)
        label = data.get("label", "?")
        column = data.get("leaderboard", {}).get("primary", "")
        print(f"  {sid:<48} {label:<10} {column}")

    print(f"\n{len(paths)} scenarios")


def main() -> None:
    from pi_bench.env import load_env

    load_env()
    parser = argparse.ArgumentParser(prog="pi", description="pi-bench CLI")
    sub = parser.add_subparsers(dest="command")

    # ── Shared argument groups ──

    def add_agent_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--agent", default=None,
                        help="Agent class as module:ClassName (default: LiteLLMAgent)")
        p.add_argument("--agent-llm", default="gpt-4o-mini",
                        help="LLM model name in litellm format (default: gpt-4o-mini)")
        p.add_argument("--agent-llm-args", action="append", metavar="KEY=VALUE",
                        help="Extra args passed to agent constructor (repeatable)")
        p.add_argument("--agent-max-steps", type=int, default=40,
                        help="Max simulation steps (default: 40)")

    def add_user_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--user-llm", default=None,
                        help="LLM model for user simulator (default: scripted, no LLM)")
        p.add_argument("--user-llm-args", action="append", metavar="KEY=VALUE",
                        help="Extra args passed to user simulator (repeatable)")
        p.add_argument("--solo", action="store_true", default=True,
                        help="Run without user simulator (default: true)")
        p.add_argument("--no-solo", action="store_false", dest="solo",
                        help="Enable user simulator")

    # ── run ──

    p_run = sub.add_parser("run", help="Run a single scenario")
    p_run.add_argument("scenario", help="Path to scenario JSON")
    add_agent_args(p_run)
    add_user_args(p_run)
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument("--observer-mode", default="audit_only",
                        choices=["audit_only", "hard_gate"])
    p_run.add_argument("--save-to", default=None,
                        help="Save result JSON to file")

    # ── run-domain ──

    p_domain = sub.add_parser("run-domain", help="Run all scenarios in a domain")
    p_domain.add_argument("domain", help="Domain name (finra, retail, helpdesk)")
    add_agent_args(p_domain)
    add_user_args(p_domain)
    p_domain.add_argument("--task-ids", default=None,
                          help="Comma-separated scenario IDs to run (default: all)")
    p_domain.add_argument("--num-tasks", type=int, default=None,
                          help="Limit to first N scenarios")
    p_domain.add_argument("--num-trials", type=int, default=1,
                          help="Number of trials per scenario (default: 1)")
    p_domain.add_argument("--concurrency", type=int, default=1,
                          help="Max parallel workers (default: 1)")
    p_domain.add_argument("--seed", type=int, default=42)
    p_domain.add_argument("--retry-failed", type=int, default=0,
                          help="Retry failed scenarios N times (default: 0)")
    p_domain.add_argument("--save-to", default=None,
                          help="Save results JSON to file")

    # ── list ──

    p_list = sub.add_parser("list", help="List available scenarios")
    p_list.add_argument(
        "--scenarios-dir",
        default=str(_default_workspace_root() / "scenarios"),
    )

    args = parser.parse_args()
    if args.command == "run":
        cmd_run(args)
    elif args.command == "run-domain":
        cmd_run_domain(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
