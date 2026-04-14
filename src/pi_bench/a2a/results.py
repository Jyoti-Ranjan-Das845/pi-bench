"""Results converter — transforms assessment results into AgentBeats JSON format.

AgentBeats expects results as a DataPart artifact with this structure:
{
    "participants": {"agent": "<purple_agent_id>"},
    "results": [{
        "domain": "policy_compliance",
        "score": <float>,
        "max_score": <float>,
        "pass_rate": <float>,
        "time_used": <float>,
        "task_rewards": {"0": <float>, ...},
        "flag_summary": {...},
        "scenario_details": [...]
    }]
}
"""

from __future__ import annotations

from typing import Any

from pi_bench.metrics import compute_metrics, compute_repeatability, metrics_to_dict


def to_agentbeats_results(
    agent_id: str,
    domain: str,
    scenario_results: list[dict],
    time_used: float = 0.0,
) -> dict[str, Any]:
    """Convert per-scenario results to AgentBeats leaderboard format.

    This includes the unified evaluator output, per-run event flags, and the
    shared benchmark metrics payload used by local runs.

    Args:
        agent_id: The purple agent's AgentBeats identifier.
        domain: The evaluation domain (e.g. "policy_compliance").
        scenario_results: List of dicts from assessment.run_assessment().
        time_used: Total assessment duration in seconds.

    Returns:
        AgentBeats-compliant results dict.
    """
    task_rewards: dict[str, float] = {}
    total_score = 0.0
    scenario_details: list[dict[str, Any]] = []
    metrics = compute_metrics(scenario_results)
    repeatability = compute_repeatability(scenario_results)
    metrics_payload = metrics_to_dict(metrics, repeatability=repeatability)
    scenario_id_counts: dict[str, int] = {}
    for sr in scenario_results:
        sid = str(sr.get("scenario_id", ""))
        scenario_id_counts[sid] = scenario_id_counts.get(sid, 0) + 1

    for i, sr in enumerate(scenario_results):
        reward = float(sr.get("reward", 1.0 if sr.get("all_passed") else 0.0))
        task_rewards[str(i)] = reward
        total_score += reward

        detail: dict[str, Any] = {
            "scenario_id": sr.get("scenario_id", str(i)),
            "trial": sr.get("trial", 0),
            "domain": sr.get("domain", ""),
            "domain_name": sr.get("domain_name", sr.get("domain", "")),
            "leaderboard_primary": sr.get("leaderboard_primary", ""),
            "label": sr.get("label", ""),
            "status": sr.get("status", "unknown"),
            "reward": reward,
            "all_passed": sr.get("all_passed", False),
            "semantic_score": sr.get("semantic_score", 0.0),
            "canonical_decision": sr.get("canonical_decision", ""),
            "decision_channel": sr.get("decision_channel"),
            "decision_valid": sr.get("decision_valid", False),
            "decision_error": sr.get("decision_error"),
            "event_flags": sr.get("event_flags", {}),
        }
        if sr.get("benchmark_version"):
            detail["benchmark_version"] = sr["benchmark_version"]
        if sr.get("error"):
            detail["error"] = sr["error"]
        if sr.get("seed") is not None:
            detail["seed"] = sr["seed"]
        if sr.get("duration") is not None:
            detail["duration"] = sr["duration"]
        if sr.get("tool_calls") is not None:
            detail["tool_calls"] = sr["tool_calls"]
        if sr.get("dimensions"):
            detail["dimensions"] = sr["dimensions"]

        # Include per-outcome check results for transparency
        outcome_results = sr.get("outcome_results", [])
        if outcome_results:
            detail["outcome_checks"] = [
                {
                    "outcome_id": oc.get("outcome_id", ""),
                    "type": oc.get("type", ""),
                    "passed": oc.get("passed", False),
                    "detail": oc.get("detail", ""),
                    "dimension": oc.get("dimension", ""),
                }
                for oc in outcome_results
            ]

        scenario_details.append(detail)

    max_score = float(len(scenario_results))
    pass_rate = (total_score / max_score * 100) if max_score > 0 else 0.0

    # Aggregate event flags through the shared metrics layer so local and A2A
    # use the same denominator rules.
    flag_summary = metrics_payload["event_flag_rates"]

    # Per-label breakdown
    label_breakdown: dict[str, dict[str, Any]] = {}
    for sr in scenario_results:
        lbl = sr.get("label", "OTHER")
        if lbl not in label_breakdown:
            label_breakdown[lbl] = {"total": 0, "passed": 0}
        label_breakdown[lbl]["total"] += 1
        if sr.get("all_passed"):
            label_breakdown[lbl]["passed"] += 1

    return {
        "participants": {"agent": agent_id},
        "results": [
            {
                "domain": domain,
                "score": total_score,
                "max_score": max_score,
                "pass_rate": pass_rate,
                "time_used": time_used,
                "task_rewards": task_rewards,
                "task_rewards_by_scenario_id": {
                    _scenario_reward_key(sr, i, scenario_id_counts): float(
                        sr.get("reward", 1.0 if sr.get("all_passed") else 0.0)
                    )
                    for i, sr in enumerate(scenario_results)
                },
                "metrics": metrics_payload,
                "flag_summary": flag_summary,
                "label_breakdown": label_breakdown,
                "scenario_details": scenario_details,
            }
        ],
    }


def _scenario_reward_key(
    scenario_result: dict,
    index: int,
    scenario_id_counts: dict[str, int],
) -> str:
    scenario_id = str(scenario_result.get("scenario_id", index))
    if scenario_id_counts.get(scenario_id, 0) <= 1:
        return scenario_id
    return f"{scenario_id}#trial_{scenario_result.get('trial', 0)}"
