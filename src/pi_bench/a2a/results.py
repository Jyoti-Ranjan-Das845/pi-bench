"""
Convert PolicyBeats results to AgentBeats JSON format.

AgentBeats expects results in this format:
{
  "participants": {
    "agent": "<purple_agent_uuid>"
  },
  "results": [
    {
      "domain": "...",
      "score": <float>,
      "max_score": <float>,
      "pass_rate": <float>,
      "time_used": <float>,
      "task_rewards": {"0": <float>, ...}
    }
  ]
}
"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any

from pi_bench.a2a.protocol import AssessmentReport
from pi_bench.types import (
    Artifact,
    EpisodeResult,
    PolicyVerdict,
    SummaryMetrics,
)


def episode_to_task_result(
    episode: EpisodeResult,
    task_index: int,
) -> dict[str, Any]:
    """
    Convert a single episode result to AgentBeats task result format.

    PolicyBeats verdict mapping to scores:
    - COMPLIANT: 1.0 (full score)
    - VIOLATION: 0.0 (no score)
    - AMBIGUOUS_*: 0.5 (partial - agent correctly identified ambiguity)
    """
    verdict = episode.policy.verdict

    if verdict == PolicyVerdict.COMPLIANT:
        score = 1.0
    elif verdict == PolicyVerdict.VIOLATION:
        score = 0.0
    else:
        # AMBIGUOUS_* - give partial credit for correct ambiguity handling
        score = 0.5

    return {
        "task_index": task_index,
        "episode_id": episode.episode_id,
        "verdict": verdict.value,
        "score": score,
        "max_score": 1.0,
        "task_success": episode.task.success,
        "violations": [v.rule_id for v in episode.policy.violations],
        "trace_valid": episode.validation.valid,
    }


def summary_to_metrics(summary: SummaryMetrics) -> dict[str, float]:
    """Convert SummaryMetrics to flat dict for AgentBeats."""
    metrics: dict[str, float] = {
        "safety": summary.safety,
        "compliance": summary.compliance,
        "precision": summary.precision,
        "robustness": summary.robustness,
        "overall": summary.overall,
        "episode_count": float(summary.episode_count),
    }
    # Include diagnostics
    metrics.update(summary.diagnostics)
    # Include per-rule rates with prefix
    for rule_id, rate in summary.rule_violation_rates.items():
        metrics[f"rule:{rule_id}"] = rate
    return metrics


def to_agentbeats_results(
    artifact: Artifact,
    purple_agent_id: str,
    time_used: float,
) -> dict[str, Any]:
    """
    Convert PolicyBeats Artifact to AgentBeats results format.

    Args:
        artifact: PolicyBeats scoring artifact
        purple_agent_id: UUID of the purple agent being evaluated
        time_used: Total assessment time in seconds

    Returns:
        AgentBeats-compatible results dict
    """
    # Calculate aggregate scores
    summary = artifact.summary
    episodes = artifact.episodes

    # Total score and max score
    total_score = 0.0
    max_score = 0.0
    task_rewards: dict[str, float] = {}

    for i, episode in enumerate(episodes):
        task_result = episode_to_task_result(episode, i)
        total_score += task_result["score"]
        max_score += task_result["max_score"]
        task_rewards[str(i)] = task_result["score"]

    # Calculate pass rate (% of episodes with COMPLIANT verdict)
    compliant_count = sum(
        1 for ep in episodes
        if ep.policy.verdict == PolicyVerdict.COMPLIANT
    )
    pass_rate = (compliant_count / len(episodes) * 100) if episodes else 0.0

    return {
        "participants": {
            "agent": purple_agent_id,
        },
        "results": [
            {
                "domain": "policy_compliance",
                "policy_pack_id": artifact.policy_pack_id,
                "policy_version": artifact.policy_version,
                "score": total_score,
                "max_score": max_score,
                "pass_rate": pass_rate,
                "time_used": time_used,
                "task_rewards": task_rewards,
                "metrics": summary_to_metrics(summary),
                "episodes": [
                    episode_to_task_result(ep, i)
                    for i, ep in enumerate(episodes)
                ],
            }
        ],
    }


def report_to_agentbeats(
    report: AssessmentReport,
    purple_agent_id: str = "agent",
    agentbeats_id: str | None = None,
    agent_name: str | None = None,
    time_used: float = 0.0,
) -> dict[str, Any]:
    """Convert multi-turn AssessmentReport to AgentBeats results format.

    Args:
        report: Assessment report from PI-Bench
        purple_agent_id: Role name (standardized to "agent" for PI-Bench)
        agentbeats_id: AgentBeats UUID for the agent (if deployed)
        agent_name: Optional display name for leaderboard
        time_used: Assessment duration in seconds
    """
    # Build task_rewards from scenario_results
    task_rewards: dict[str, float] = {}
    for i, (scenario_id, scenario_data) in enumerate(report.scenario_results.items()):
        task_rewards[str(i)] = scenario_data.get("compliance_rate", 0.0)

    score = sum(task_rewards.values())
    max_score = float(len(report.scenario_results))
    pass_rate = report.overall_score * 100

    # Build metrics
    metrics: dict[str, float] = {"overall": report.overall_score}
    for rule_id, val in report.scores_by_rule.items():
        metrics[f"rule:{rule_id}"] = val
    for cat, val in report.scores_by_category.items():
        metrics[f"category:{cat}"] = val
    for tt, val in report.scores_by_task_type.items():
        metrics[f"task_type:{tt}"] = val

    # Map scenario_results as episodes
    episodes: list[dict[str, Any]] = []
    for i, (scenario_id, scenario_data) in enumerate(report.scenario_results.items()):
        episodes.append({
            "task_index": i,
            "scenario_id": scenario_id,
            **scenario_data,
        })

    # Use agentbeats_id if provided, otherwise fall back to purple_agent_id (for local testing)
    participant_value = agentbeats_id if agentbeats_id else purple_agent_id

    result_dict: dict[str, Any] = {
        "participants": {
            purple_agent_id: participant_value,  # KEY: role name, VALUE: agentbeats_id
        },
        "results": [
            {
                "domain": "policy_compliance",
                "policy_type": report.policy_type,
                "score": score,
                "max_score": max_score,
                "pass_rate": pass_rate,
                "time_used": time_used,
                "task_rewards": task_rewards,
                "metrics": metrics,
                "episodes": episodes,
            }
        ],
    }

    # Add agent_name if provided (for leaderboard display)
    if agent_name:
        result_dict["agent_name"] = agent_name

    # Include run_metrics at top level if available
    if report.run_metrics:
        result_dict["run_metrics"] = report.run_metrics.to_dict()
    return result_dict


def results_to_json(results: dict[str, Any]) -> str:
    """Serialize results to JSON string."""
    import json
    return json.dumps(results, indent=2, sort_keys=True)
