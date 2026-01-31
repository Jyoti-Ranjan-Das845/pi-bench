"""
PurpleBench runner — thin facade over the pure scoring core.

Takes pre-built traces (scenarios) and runs them through score_episode + aggregate.
This is the imperative shell; all logic lives in score.py and policy.py.
"""

from __future__ import annotations

from dataclasses import dataclass

from pi_bench.score import aggregate, score_episode
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    ExposedState,
    PolicyPack,
    SummaryMetrics,
    Trace,
)


@dataclass(frozen=True, slots=True)
class BenchScenario:
    """One pre-built scenario for bench evaluation."""

    scenario_id: str
    trace: Trace
    exposed_state: ExposedState
    policy_pack: PolicyPack
    task_type: str = "compliance"
    domain: str = "bench"


def run_bench(scenarios: tuple[BenchScenario, ...] | list[BenchScenario]) -> SummaryMetrics:
    """
    Run scenarios through the scoring pipeline and aggregate.

    Pure function over pre-built traces. No I/O, no LLM calls.
    """
    results = tuple(
        score_episode(
            EpisodeBundle(
                episode_id=s.scenario_id,
                trace=s.trace,
                exposed_state=s.exposed_state,
                metadata=EpisodeMetadata(
                    domain=s.domain,
                    task_type=s.task_type,
                ),
            ),
            s.policy_pack,
        )
        for s in scenarios
    )
    return aggregate(results)
