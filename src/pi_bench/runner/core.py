"""Runner core — multi-trial execution with ThreadPoolExecutor."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pi_bench import __version__
from pi_bench.evaluator import evaluate
from pi_bench.local import AgentProtocol, UserProtocol
from pi_bench.observer import create_observer
from pi_bench.orchestrator import run as orchestrator_run
from pi_bench.runner.seeds import build_work_queue
from pi_bench.runner.checkpoint import save_incremental, load_checkpoint, make_info
from pi_bench.trace import TraceRecorder


def run_domain(
    domain: dict,
    agent: AgentProtocol,
    user: UserProtocol | None,
    num_trials: int = 1,
    seed: int | None = None,
    max_concurrency: int = 1,
    save_to: Path | str | None = None,
    resume_from: Path | str | None = None,
    task_ids: list[str] | None = None,
    num_tasks: int | None = None,
    max_steps: int = 50,
    max_errors: int = 10,
    solo: bool = False,
    observer_factory: Callable[[dict], dict] | None = None,
    observer_mode: str = "audit_only",
    retry_failed: int = 0,
    agent_factory: Callable[[], AgentProtocol] | None = None,
    user_factory: Callable[[], UserProtocol] | None = None,
    emitter: Any | None = None,
) -> dict:
    """Run all tasks x trials. Returns Results dict.

    Args:
        agent: Agent instance (used for sequential runs or as template).
        user: User simulator instance; ignored when solo=True.
        solo: If True, agent works alone (no user simulator), user param is ignored.
        agent_factory: If provided, called per-trial to create a fresh agent.
            Required for max_concurrency > 1 to avoid shared mutable state.
        user_factory: If provided, called per-trial to create a fresh user.
            Required for max_concurrency > 1 to avoid shared mutable state.
    """
    tasks = domain["tasks"]

    # Filter tasks by ID if requested
    if task_ids is not None:
        tasks = [t for t in tasks if t["id"] in task_ids]

    # Limit number of tasks
    if num_tasks is not None:
        tasks = tasks[:num_tasks]

    # Load checkpoint for resume
    completed = set()
    existing_sims = []
    checkpoint_info: dict[str, Any] = {}
    if resume_from is not None:
        checkpoint = load_checkpoint(resume_from)
        if checkpoint is not None:
            checkpoint_info = checkpoint.get("info", {})
            existing_sims = checkpoint.get("simulations", [])

    # Default observer factory when none provided
    if observer_factory is None and observer_mode != "none":
        def observer_factory(env, forbidden_tools=None):
            trace = TraceRecorder()
            return create_observer(
                env, trace,
                forbidden_tools=forbidden_tools,
                mode=observer_mode,
            )

    # Build work queue. When a checkpoint or explicit seed gives enough data,
    # include seed in the resume key so a different reproducibility config reruns.
    checkpoint_seed = _checkpoint_seed(checkpoint_info)
    base_seed = seed if seed is not None else checkpoint_seed if checkpoint_seed is not None else int(time.time())
    strict_resume_key = seed is not None or checkpoint_seed is not None
    completed = _completed_resume_keys(existing_sims, include_seed=strict_resume_key)
    work = build_work_queue(
        tasks,
        num_trials,
        base_seed,
        completed,
        include_seed_in_key=strict_resume_key,
    )

    info = make_info(
        domain=domain,
        agent=agent,
        user=user,
        num_trials=num_trials,
        seed=base_seed,
        max_steps=max_steps,
        max_errors=max_errors,
        max_concurrency=max_concurrency,
        solo=solo,
        observer_mode=observer_mode,
    )

    # Execute
    save_path = Path(save_to) if save_to else None
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            save_path.touch()
        except OSError as exc:
            raise ValueError(f"Cannot write to save path {save_path}: {exc}") from exc
    save_lock = threading.Lock() if save_path else None
    simulations = list(existing_sims)
    new_count = 0

    if max_concurrency <= 1 or len(work) <= 1:
        # Sequential execution — safe to reuse agent/user instances
        for task, trial, trial_seed in work:
            if emitter:
                emitter.on_scenario_start(
                    task["id"],
                    task.get("leaderboard_primary", ""),
                    task.get("label", ""),
                )
            sim = _run_one_safe(
                task=task,
                trial=trial,
                seed=trial_seed,
                agent=agent,
                user=user,
                domain=domain,
                max_steps=max_steps,
                max_errors=max_errors,
                solo=solo,
                observer_factory=observer_factory,
            )
            simulations.append(sim)
            new_count += 1
            if emitter:
                _emit_scenario_result(emitter, sim)
            if save_path and save_lock:
                save_incremental(simulations, save_path, save_lock, info=info)
    else:
        # Parallel execution — create fresh agent/user per trial
        if agent_factory is None:
            raise ValueError(
                "agent_factory is required for max_concurrency > 1 "
                "to avoid shared mutable state across threads"
            )
        if not solo and user is not None and user_factory is None:
            raise ValueError(
                "user_factory is required for max_concurrency > 1 in non-solo mode "
                "to avoid shared mutable state across threads"
            )
        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(
                    _run_one_safe,
                    task=task,
                    trial=trial,
                    seed=trial_seed,
                    agent=agent_factory(),
                    user=user_factory() if user_factory else None,
                    domain=domain,
                    max_steps=max_steps,
                    max_errors=max_errors,
                    solo=solo,
                    observer_factory=observer_factory,
                ): (task, trial, trial_seed)
                for task, trial, trial_seed in work
            }
            for future in as_completed(futures):
                sim = future.result()
                simulations.append(sim)
                new_count += 1
                if emitter:
                    _emit_scenario_result(emitter, sim)
                if save_path and save_lock:
                    save_incremental(simulations, save_path, save_lock, info=info)

    # Retry failed simulations
    if retry_failed > 0:
        for retry_round in range(retry_failed):
            failed = [
                (sim["task_id"], sim["trial"], sim["seed"])
                for sim in simulations
                if _is_retryable_sim(sim)
            ]
            if not failed:
                break
            failed_keys = {(t, tr) for t, tr, _ in failed}
            simulations = [s for s in simulations if (s["task_id"], s["trial"]) not in failed_keys]
            for task_id, trial, trial_seed in failed:
                task = next((t for t in tasks if t["id"] == task_id), None)
                if task is None:
                    continue  # task was filtered out, skip retry
                sim = _run_one_safe(
                    task=task, trial=trial, seed=trial_seed,
                    agent=agent_factory() if agent_factory else agent,
                    user=user_factory() if user_factory else user,
                    domain=domain,
                    max_steps=max_steps, max_errors=max_errors,
                    solo=solo, observer_factory=observer_factory,
                )
                simulations.append(sim)
                if save_path and save_lock:
                    save_incremental(simulations, save_path, save_lock, info=info)

    simulations = sorted(simulations, key=_simulation_sort_key)
    if save_path and save_lock:
        save_incremental(simulations, save_path, save_lock, info=info)

    result = {
        "info": info,
        "tasks": tasks,
        "simulations": simulations,
    }

    from pi_bench.metrics import compute_metrics, compute_repeatability, metrics_to_dict

    metrics = compute_metrics(simulations)
    result["metrics"] = metrics_to_dict(
        metrics,
        repeatability=compute_repeatability(simulations),
    )
    if save_path and save_lock:
        save_incremental(
            simulations,
            save_path,
            save_lock,
            info=info,
            metrics=result["metrics"],
        )

    if resume_from is not None:
        result["new_runs_count"] = new_count

    return result


def _run_one(
    task: dict,
    trial: int,
    seed: int,
    agent: AgentProtocol,
    user: UserProtocol | None,
    domain: dict,
    max_steps: int,
    max_errors: int,
    solo: bool,
    observer_factory: Callable[[dict], dict] | None = None,
) -> dict:
    """Run a single simulation: orchestrate + evaluate."""
    from pi_bench.evaluator.llm_judge import clear_judge_cache
    clear_judge_cache()

    get_env = domain["get_environment"]
    env = get_env(task)

    # Extract forbidden tools from evaluation criteria
    criteria = task.get("evaluation_criteria", {})
    forbidden_tools = {
        c["tool_name"] for c in criteria.get("policy_checks", [])
        if c.get("type") == "tool_not_called"
    } or None

    # Create observer if factory provided
    if observer_factory is not None:
        try:
            observer = observer_factory(env, forbidden_tools=forbidden_tools)
        except TypeError:
            # Backward compat: old factories don't accept forbidden_tools
            observer = observer_factory(env)
    else:
        observer = None

    sim = orchestrator_run(
        agent=agent,
        user=user,
        env=env,
        task=task,
        max_steps=max_steps,
        max_errors=max_errors,
        seed=seed,
        solo=solo,
        observer=observer,
    )
    sim["trial"] = trial
    sim["seed"] = seed
    sim["env"] = env
    sim["benchmark_version"] = __version__
    sim["agent_model"] = getattr(agent, "model_name", "unknown")
    sim["user_model"] = getattr(user, "model_name", "unknown") if user else "none"

    # Carry scenario metadata for metrics aggregation
    sim["task_id"] = task["id"]
    sim["scenario_id"] = task.get("scenario_id", task["id"])
    sim["domain"] = task.get("domain", domain.get("name", ""))
    sim["domain_name"] = task.get("domain_name", domain.get("name", ""))
    sim["leaderboard_primary"] = task.get("leaderboard_primary", "")
    sim["label"] = task.get("label", "")

    # Attach trace for POLICY evaluator and populate messages for decision fallback
    if observer is not None and "trace" in observer:
        trace = observer["trace"]
        sim["trace"] = trace
        # Populate trace messages so JSON decision fallback works
        for msg in sim.get("messages", []):
            role = msg.get("role", "")
            content = msg.get("content")
            if role == "assistant" and content:
                trace.add_message("assistant", content)
            elif role == "user" and content:
                trace.add_message("user", content)

    # Evaluate
    reward_info = evaluate(task, sim, domain)
    sim["reward_info"] = reward_info
    sim["status"] = "completed"
    sim["reward"] = reward_info.get("reward")
    sim["all_passed"] = reward_info.get("all_passed")
    sim["semantic_score"] = reward_info.get("semantic_score")
    sim["outcome_results"] = reward_info.get("outcome_results", [])
    sim["dimensions"] = reward_info.get("dimensions", {})
    sim["canonical_decision"] = reward_info.get("canonical_decision")
    sim["decision_channel"] = reward_info.get("decision_channel")
    sim["decision_valid"] = reward_info.get("decision_valid", False)
    sim["decision_error"] = reward_info.get("decision_error")

    trace = sim.get("trace")
    if trace is not None:
        from pi_bench.event_flags import compute_flags

        flags = compute_flags(
            scenario_label=sim.get("label", ""),
            trace=trace,
            canonical_decision=sim.get("canonical_decision") or "NONE",
            policy_checks=criteria.get("policy_checks", []),
            forbidden_tools=list(forbidden_tools or []),
            messages=sim.get("messages", []),
        )
        sim["event_flags"] = {
            "V_r": flags.V_r,
            "UR_r": flags.UR_r,
            "OR_r": flags.OR_r,
            "EA_r": flags.EA_r,
            "AT_r": flags.AT_r,
        }
    else:
        sim["event_flags"] = {
            "V_r": False,
            "UR_r": False,
            "OR_r": False,
            "EA_r": False,
            "AT_r": False,
        }

    return sim


def _run_one_safe(
    task: dict,
    trial: int,
    seed: int,
    agent: AgentProtocol,
    user: UserProtocol | None,
    domain: dict,
    max_steps: int,
    max_errors: int,
    solo: bool,
    observer_factory: Callable[[dict], dict] | None = None,
) -> dict:
    """Run one work item and convert hard runtime exceptions to error rows."""
    try:
        return _run_one(
            task=task,
            trial=trial,
            seed=seed,
            agent=agent,
            user=user,
            domain=domain,
            max_steps=max_steps,
            max_errors=max_errors,
            solo=solo,
            observer_factory=observer_factory,
        )
    except Exception as exc:
        import logging

        logging.getLogger(__name__).exception(
            "scenario %s trial %s failed hard", task.get("id", "?"), trial
        )
        return _error_sim(task, trial, seed, domain, exc)


def _error_sim(
    task: dict,
    trial: int,
    seed: int,
    domain: dict,
    exc: Exception,
) -> dict:
    """Build a simulation-shaped error row for metrics and reports."""
    error = f"{type(exc).__name__}: {exc}"
    return {
        "id": "",
        "task_id": task.get("id", "?"),
        "scenario_id": task.get("scenario_id", task.get("id", "?")),
        "domain": task.get("domain", domain.get("name", "")),
        "domain_name": task.get("domain_name", domain.get("name", "")),
        "leaderboard_primary": task.get("leaderboard_primary", ""),
        "label": task.get("label", ""),
        "status": "error",
        "error": error,
        "termination_reason": "runtime_error",
        "trial": trial,
        "seed": seed,
        "benchmark_version": __version__,
        "reward": 0.0,
        "all_passed": False,
        "semantic_score": 0.0,
        "outcome_results": [],
        "dimensions": {},
        "canonical_decision": None,
        "decision_channel": None,
        "decision_valid": False,
        "decision_error": "RUNTIME_ERROR",
        "event_flags": {
            "V_r": False,
            "UR_r": False,
            "OR_r": False,
            "EA_r": False,
            "AT_r": False,
        },
        "reward_info": {
            "reward": 0.0,
            "all_passed": False,
            "semantic_score": 0.0,
            "outcome_results": [],
            "dimensions": {},
            "canonical_decision": None,
            "decision_channel": None,
            "decision_valid": False,
            "decision_error": "RUNTIME_ERROR",
            "reward_breakdown": {"reason": error},
        },
        "messages": [],
        "step_count": 0,
    }


def _is_retryable_sim(sim: dict) -> bool:
    return (
        sim.get("status") == "error"
        or sim.get("termination_reason") in ("agent_error", "user_error", "too_many_errors")
    )


def _emit_scenario_result(emitter: Any, sim: dict) -> None:
    """Emit a scenario result to the observability emitter.

    Builds a lightweight report dict from the simulation result
    and pushes it via emitter.on_scenario_end().
    """
    reward = sim.get("reward_info", {})
    trace = sim.get("trace")

    emitter.on_scenario_end(sim.get("task_id", "?"), {
        "all_passed": reward.get("all_passed", False),
        "leaderboard_primary": sim.get("leaderboard_primary", ""),
        "label": sim.get("label", ""),
        "termination_reason": sim.get("termination_reason", ""),
        "step_count": sim.get("step_count", 0),
        "passed_checks": sum(1 for r in reward.get("outcome_results", []) if r.get("passed")),
        "total_checks": len(reward.get("outcome_results", [])),
        "tool_calls": trace.tool_names() if trace else [],
        "dimensions": reward.get("dimensions", {}),
        "event_flags": sim.get("event_flags", {}),
        "summary": "",
    })


def _checkpoint_seed(info: dict[str, Any]) -> int | None:
    """Return the saved base seed from checkpoint info if present."""
    value = info.get("base_seed", info.get("seed"))
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _completed_resume_keys(
    simulations: list[dict],
    *,
    include_seed: bool,
) -> set[tuple]:
    """Build completed-work keys from checkpoint simulations."""
    keys: set[tuple] = set()
    for sim in simulations:
        key = _simulation_resume_key(sim, include_seed=include_seed)
        if key is not None:
            keys.add(key)
    return keys


def _simulation_resume_key(sim: dict, *, include_seed: bool) -> tuple | None:
    """Return the resume key for a saved simulation."""
    task_id = sim.get("task_id")
    trial = sim.get("trial")
    if task_id is None or trial is None:
        return None
    if include_seed:
        seed = sim.get("seed")
        if seed is None:
            return None
        return (task_id, trial, seed)
    return (task_id, trial)


def _simulation_sort_key(sim: dict) -> tuple:
    """Stable output ordering for sequential, resumed, and parallel runs."""
    return (
        str(sim.get("task_id", "")),
        int(sim.get("trial", 0)),
        int(sim.get("seed", 0)) if isinstance(sim.get("seed"), int) else 0,
    )
