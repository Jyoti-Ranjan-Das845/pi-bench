"""Assessment engine -- runs pi-bench scenarios against a purple agent via A2A.

Unlike the Archive 9 version that only supported the finance domain, this
engine uses scenario_loader.load() to support all domains (finra, retail,
helpdesk) and uses the unified evaluate() dispatcher for the richer
outcome-type evaluation pipeline including LLM judge NL assertions.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pi_bench import __version__
from pi_bench.a2a.purple_adapter import A2APurpleAgent
from pi_bench.a2a.user_adapter import A2AUserAgent
from pi_bench.evaluator import evaluate
from pi_bench.evaluator.scenario_validator import validate_scenario
from pi_bench.event_flags import compute_flags
from pi_bench.observer import create_observer
from pi_bench.orchestrator.core import run as orchestrator_run
from pi_bench.runner.seeds import derive_seed
from pi_bench.scenario_loader import (
    default_workspace_root,
    discover_scenarios,
    domain_tool_names,
    load,
)
from pi_bench.trace import TraceRecorder
from pi_bench.users.user import LiteLLMUser

logger = logging.getLogger(__name__)

_EMPTY_FLAGS = {"V_r": False, "UR_r": False, "OR_r": False, "EA_r": False, "AT_r": False}
_RETRYABLE_TERMINATIONS = {"agent_error", "user_error", "too_many_errors"}
_SCENARIO_DOMAIN_ALIASES = {
    "finra": "finra",
    "retail": "retail",
    "retail_refund_sop_v1": "retail",
    "helpdesk": "helpdesk",
    "helpdesk_access_control_v1": "helpdesk",
}


def _error_result(
    scenario_id: str,
    label: str,
    error: str,
    duration: float = 0,
    *,
    domain: str = "",
    domain_name: str = "",
    leaderboard_primary: str = "",
    trial: int = 0,
    seed: int | None = None,
) -> dict:
    """Build a standardized error result dict."""
    return {
        "benchmark_version": __version__,
        "scenario_id": scenario_id,
        "domain": domain,
        "domain_name": domain_name or domain,
        "leaderboard_primary": leaderboard_primary,
        "label": label,
        "status": "error",
        "error": error,
        "reward": 0.0,
        "all_passed": False,
        "semantic_score": 0.0,
        "outcome_results": [],
        "dimensions": {},
        "canonical_decision": None,
        "decision_channel": None,
        "decision_valid": False,
        "decision_error": "ASSESSMENT_ERROR",
        "event_flags": dict(_EMPTY_FLAGS),
        "duration": duration,
        "trial": trial,
        "seed": seed,
    }


def _resolve_scenarios_dir(
    scenarios_dir: str | Path | None,
    workspace_root: Path,
) -> Path:
    """Resolve scenario paths from cwd first, then the workspace root."""
    if scenarios_dir is None:
        return workspace_root / "scenarios"

    path = Path(scenarios_dir)
    if path.is_absolute() or path.is_dir():
        return path

    candidate = workspace_root / path
    return candidate if candidate.exists() else path


def run_assessment(
    purple_url: str,
    config: dict[str, Any] | None = None,
) -> list[dict]:
    """Run all scenarios against a purple agent and return per-scenario results.

    This is the main entry point called by the executor. It discovers all
    pibench_scenario_v1 JSON files, loads each one via scenario_loader (which
    handles domain resolution for finra/retail/helpdesk), and runs them through
    the normal multi-turn orchestrator with an A2APurpleAgent and a user
    simulator.

    Args:
        purple_url: HTTP endpoint of the purple agent.
        config: Optional configuration:
            - scenarios_dir: path to scenarios directory (default: ./scenarios)
            - workspace_root: root for resolving policy/tools (default: inferred)
            - scenario_scope: "all" or "domain" (default: "all")
            - scenario_domain: finra, retail, or helpdesk when scope="domain"
            - max_steps: max orchestrator steps per scenario (default: 50)
            - seed: random seed (default: 42)
            - observer_mode: "audit_only" or "hard_gate" (default: "audit_only")
            - num_trials: number of trials per scenario (default: 1)
            - concurrency: parallel scenario/trial workers (default: 1)
            - retry_failed: retry runtime/protocol failures N times (default: 0)
            - user_url: optional A2A URL for a remote user simulator
            - user_model: local LiteLLM user model when user_url is not provided

    Returns:
        List of per-scenario result dicts with scenario_id, label, reward,
        all_passed, outcome_results, canonical_decision, event_flags, etc.
    """
    config = config or {}
    workspace_root = Path(config.get("workspace_root") or default_workspace_root())
    scenarios_dir = _resolve_scenarios_dir(config.get("scenarios_dir"), workspace_root)
    scenarios_dir = _resolve_scenario_scope(
        scenarios_dir=scenarios_dir,
        scenario_scope=config.get("scenario_scope", "all"),
        scenario_domain=config.get("scenario_domain"),
    )
    max_steps = config.get("max_steps", 50)
    seed = config.get("seed", 42)
    observer_mode = config.get("observer_mode", "audit_only")
    num_trials = _positive_int(config.get("num_trials", 1), name="num_trials")
    concurrency = _positive_int(config.get("concurrency", 1), name="concurrency")
    retry_failed = _nonnegative_int(config.get("retry_failed", 0), name="retry_failed")
    user_url = config.get("user_url")
    user_model = config.get("user_model", "gpt-4.1-mini")

    # Discover all valid scenario files
    scenario_files = discover_scenarios(scenarios_dir)
    if not scenario_files:
        raise FileNotFoundError(f"No pibench_scenario_v1 files found in {scenarios_dir}")

    logger.info("Found %d scenarios in %s", len(scenario_files), scenarios_dir)

    work = [
        (
            scenario_path,
            trial,
            derive_seed(seed, scenario_path.stem, trial) if seed is not None else None,
        )
        for scenario_path in scenario_files
        for trial in range(num_trials)
    ]

    results = _run_work_items(
        work=work,
        purple_url=purple_url,
        workspace_root=workspace_root,
        max_steps=max_steps,
        observer_mode=observer_mode,
        concurrency=concurrency,
        user_url=user_url,
        user_model=user_model,
    )

    for _ in range(retry_failed):
        failed = [
            (Path(r.get("_scenario_path", "")), int(r.get("trial", 0)), r.get("seed"))
            for r in results
            if _is_retryable_result(r) and r.get("_scenario_path")
        ]
        if not failed:
            break
        failed_keys = {(str(path), trial) for path, trial, _seed in failed}
        results = [
            r for r in results
            if (str(r.get("_scenario_path", "")), int(r.get("trial", 0))) not in failed_keys
        ]
        results.extend(
            _run_work_items(
                work=failed,
                purple_url=purple_url,
                workspace_root=workspace_root,
                max_steps=max_steps,
                observer_mode=observer_mode,
                concurrency=concurrency,
                user_url=user_url,
                user_model=user_model,
            )
        )

    results = sorted(
        (_public_result(r) for r in results),
        key=lambda r: (
            str(r.get("scenario_id", "")),
            int(r.get("trial", 0)) if isinstance(r.get("trial", 0), int) else 0,
        ),
    )

    return results


def _run_work_items(
    *,
    work: list[tuple[Path, int, int | None]],
    purple_url: str,
    workspace_root: Path,
    max_steps: int,
    observer_mode: str,
    concurrency: int,
    user_url: str | None,
    user_model: str,
) -> list[dict]:
    if concurrency <= 1 or len(work) <= 1:
        return [
            _run_work_item(
                scenario_path=scenario_path,
                trial=trial,
                scenario_seed=scenario_seed,
                purple_url=purple_url,
                workspace_root=workspace_root,
                max_steps=max_steps,
                observer_mode=observer_mode,
                user_url=user_url,
                user_model=user_model,
            )
            for scenario_path, trial, scenario_seed in work
        ]

    results: list[dict] = []
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(
                _run_work_item,
                scenario_path=scenario_path,
                trial=trial,
                scenario_seed=scenario_seed,
                purple_url=purple_url,
                workspace_root=workspace_root,
                max_steps=max_steps,
                observer_mode=observer_mode,
                user_url=user_url,
                user_model=user_model,
            ): (scenario_path, trial, scenario_seed)
            for scenario_path, trial, scenario_seed in work
        }
        for future in as_completed(futures):
            # _run_work_item catches per-scenario errors, but keep this guard so
            # an unexpected wrapper failure still becomes one failed row.
            scenario_path, trial, scenario_seed = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                logger.exception("Scenario %s trial %d failed", scenario_path.stem, trial)
                results.append(
                    _error_result(
                        scenario_path.stem,
                        "",
                        str(exc),
                        trial=trial,
                        seed=scenario_seed,
                    )
                    | {"_scenario_path": str(scenario_path)}
                )
    return results


def _run_work_item(
    *,
    scenario_path: Path,
    trial: int,
    scenario_seed: int | None,
    purple_url: str,
    workspace_root: Path,
    max_steps: int,
    observer_mode: str,
    user_url: str | None,
    user_model: str,
) -> dict:
    try:
        result = _run_single_scenario(
            scenario_path=scenario_path,
            purple_url=purple_url,
            workspace_root=workspace_root,
            max_steps=max_steps,
            seed=scenario_seed,
            trial=trial,
            observer_mode=observer_mode,
            user_url=user_url,
            user_model=user_model,
        )
    except Exception as exc:
        logger.exception("Scenario %s trial %d failed", scenario_path.stem, trial)
        result = _error_result(
            scenario_path.stem,
            "",
            str(exc),
            trial=trial,
            seed=scenario_seed,
        )
    result["_scenario_path"] = str(scenario_path)
    return result


def _resolve_scenario_scope(
    *,
    scenarios_dir: Path,
    scenario_scope: str,
    scenario_domain: str | None,
) -> Path:
    scope = str(scenario_scope or "all").strip().lower()
    if scope == "all":
        return scenarios_dir
    if scope != "domain":
        raise ValueError("scenario_scope must be 'all' or 'domain'")
    if not scenario_domain:
        raise ValueError("scenario_domain is required when scenario_scope='domain'")
    canonical = _SCENARIO_DOMAIN_ALIASES.get(str(scenario_domain).strip().lower())
    if canonical is None:
        allowed = ", ".join(sorted(set(_SCENARIO_DOMAIN_ALIASES.values())))
        raise ValueError(f"scenario_domain must be one of: {allowed}")
    path = scenarios_dir / canonical
    if not path.is_dir():
        raise FileNotFoundError(f"Scenario domain directory not found: {path}")
    return path


def _positive_int(value: Any, *, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be >= 1")
    return parsed


def _nonnegative_int(value: Any, *, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{name} must be >= 0")
    return parsed


def _is_retryable_result(result: dict) -> bool:
    return (
        result.get("status") == "error"
        or result.get("termination_reason") in _RETRYABLE_TERMINATIONS
    )


def _public_result(result: dict) -> dict:
    return {k: v for k, v in result.items() if not k.startswith("_")}


def _run_single_scenario(
    scenario_path: Path,
    purple_url: str,
    workspace_root: str | Path | None = None,
    max_steps: int = 50,
    seed: int | None = 42,
    trial: int = 0,
    observer_mode: str = "audit_only",
    user_url: str | None = None,
    user_model: str = "gpt-4.1-mini",
) -> dict:
    """Run a single scenario against a purple agent via A2A.

    Uses scenario_loader.load() for multi-domain support, then runs the normal
    multi-turn orchestrator. The tested agent is reached through A2A. The user
    simulator is either an A2A user server or a local LiteLLMUser fallback.
    """
    import time

    start = time.time()

    # Load scenario via the standard loader (handles finra/retail/helpdesk)
    loaded = load(scenario_path, workspace_root=workspace_root)
    task = loaded["task"]
    env = loaded["env"]
    label = loaded["label"]
    scenario_id = loaded["scenario_id"]
    forbidden_tools = loaded["forbidden_tools"]
    domain = task.get("domain", "")
    domain_name = task.get("domain_name", domain)
    leaderboard_primary = task.get("leaderboard_primary", "")

    # Validate scenario before running
    scenario_data = json.loads(Path(scenario_path).read_text())
    validation_errors = validate_scenario(scenario_data)
    validation_errors.extend(
        _validate_referenced_tools_exist(
            scenario_data=scenario_data,
            workspace_root=Path(workspace_root) if workspace_root else default_workspace_root(),
        )
    )
    if validation_errors:
        for err in validation_errors:
            logger.error("Validation error in %s: %s", scenario_id, err)
        return _error_result(
            scenario_id, label,
            f"Validation failed: {'; '.join(validation_errors)}",
            time.time() - start,
            domain=domain,
            domain_name=domain_name,
            leaderboard_primary=leaderboard_primary,
            trial=trial,
            seed=seed,
        )
    # Create the purple agent adapter
    agent = A2APurpleAgent(purple_url)
    user = A2AUserAgent(user_url) if user_url else LiteLLMUser(model_name=user_model)

    # Create trace and observer
    trace = TraceRecorder()
    observer = create_observer(
        env, trace,
        forbidden_tools=set(forbidden_tools) if forbidden_tools else None,
        mode=observer_mode,
    )

    # Run the real multi-turn benchmark loop: user simulator <-> tested agent.
    try:
        sim = orchestrator_run(
            agent=agent,
            user=user,
            env=env,
            task=task,
            max_steps=max_steps,
            seed=seed,
            solo=False,
            observer=observer,
        )
    except Exception as exc:
        return _error_result(
            scenario_id,
            label,
            str(exc),
            time.time() - start,
            domain=domain,
            domain_name=domain_name,
            leaderboard_primary=leaderboard_primary,
            trial=trial,
            seed=seed,
        )

    # Record messages to trace for NL assertions
    for msg in sim.get("messages", []):
        if msg.get("role") == "assistant" and msg.get("content"):
            trace.add_message("assistant", msg["content"])
        elif msg.get("role") == "user" and msg.get("content"):
            trace.add_message("user", msg["content"])

    # Attach trace and env to simulation for evaluate()
    sim["trace"] = trace
    sim["env"] = env

    # Evaluate outcomes using the unified evaluate() dispatcher
    # get_environment must return a FRESH env (not the mutated live one)
    # so that evaluate_db() can replay tool calls from a clean baseline.
    def _fresh_env(task=None):
        return load(scenario_path, workspace_root=workspace_root)["env"]

    eval_result = evaluate(task, sim, domain={"get_environment": _fresh_env})
    all_passed = eval_result["all_passed"]
    reward = eval_result.get("reward", 1.0 if all_passed else 0.0)
    outcome_results = eval_result["outcome_results"]
    semantic_score = eval_result["semantic_score"]
    dimensions = eval_result.get("dimensions", {})

    canonical_decision = eval_result.get("canonical_decision") or "NONE"

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
        "benchmark_version": __version__,
        "task_id": task.get("id", scenario_id),
        "scenario_id": scenario_id,
        "domain": domain,
        "domain_name": domain_name,
        "leaderboard_primary": leaderboard_primary,
        "label": label,
        "status": "completed",
        "termination_reason": sim.get("termination_reason", "unknown"),
        "step_count": sim.get("step_count", 0),
        "canonical_decision": canonical_decision,
        "decision_channel": eval_result.get("decision_channel"),
        "decision_valid": eval_result.get("decision_valid", False),
        "decision_error": eval_result.get("decision_error"),
        "reward": reward,
        "all_passed": all_passed,
        "semantic_score": semantic_score,
        "outcome_results": outcome_results,
        "dimensions": dimensions,
        "event_flags": {
            "V_r": flags.V_r,
            "UR_r": flags.UR_r,
            "OR_r": flags.OR_r,
            "EA_r": flags.EA_r,
            "AT_r": flags.AT_r,
        },
        "duration": duration,
        "trial": trial,
        "seed": seed,
        "user_model": getattr(user, "model_name", "unknown"),
        "tool_calls": trace.tool_names(),
        "messages": _make_jsonable(sim.get("messages", [])),
        "trace": _make_jsonable(trace),
        "env": _make_jsonable(env),
    }


def _make_jsonable(value: Any) -> Any:
    """Convert audit records into JSON-safe values for saved A2A reports."""
    if isinstance(value, dict):
        return {str(k): _make_jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_make_jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [_make_jsonable(v) for v in value]
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(value)


def _validate_referenced_tools_exist(
    *,
    scenario_data: dict,
    workspace_root: Path,
) -> list[str]:
    """Validate A2A-facing scenario tool references against domain tools."""
    errors: list[str] = []
    meta = scenario_data.get("meta", {})
    scenario_id = meta.get("scenario_id", "<unknown>")
    domain = meta.get("domain", "")
    if not domain:
        return [f"{scenario_id}: meta.domain is required"]
    try:
        known_tools = domain_tool_names(domain, workspace_root)
    except Exception as exc:
        return [f"{scenario_id}: cannot load domain tools for {domain!r}: {exc}"]

    available = scenario_data.get("available_tools")
    if available is not None:
        if not isinstance(available, list):
            errors.append(f"{scenario_id}: available_tools must be a list")
        else:
            unknown_available = sorted(
                {t for t in available if isinstance(t, str)} - known_tools
            )
            if unknown_available:
                errors.append(
                    f"{scenario_id}: unknown available_tools: {unknown_available}"
                )

    referenced = _referenced_policy_tools(
        scenario_data.get("evaluation_criteria", {}).get("policy_checks", [])
    )
    unknown_referenced = sorted(referenced - known_tools)
    if unknown_referenced:
        errors.append(
            f"{scenario_id}: policy_checks reference unknown tools: {unknown_referenced}"
        )

    return errors


def _referenced_policy_tools(policy_checks: list[dict]) -> set[str]:
    tools: set[str] = set()
    for check in policy_checks:
        for key in ("tool_name", "first_tool", "second_tool"):
            value = check.get(key)
            if isinstance(value, str) and value:
                tools.add(value)
        for key in ("tool_names", "first_tools"):
            values = check.get(key, [])
            if isinstance(values, list):
                tools.update(v for v in values if isinstance(v, str) and v)
    return tools
