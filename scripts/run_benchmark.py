#!/usr/bin/env python3
"""
Run PolicyBeats benchmark with an LLM purple agent.

Uses Ollama (local) or OpenAI to generate agent responses,
then scores them with the deterministic PolicyBeats pipeline.

Outputs the 4-dimension leaderboard (safety, compliance, precision, robustness).

Usage:
    python scripts/run_benchmark.py                          # default: ollama/qwen2.5:3b
    python scripts/run_benchmark.py --model ollama/gemma3    # gemma3
    python scripts/run_benchmark.py --model gpt-4o-mini      # OpenAI (needs OPENAI_API_KEY)
    python scripts/run_benchmark.py --runs 3                 # 3 runs per episode (average)
"""

import asyncio
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from policybeats.a2a.tool_executor import env_from_context, execute_tool
from policybeats.packs.gdpr_support import GDPR_EPISODES, get_policy_pack_for_episode
from policybeats.policy import compile_policy_pack
from policybeats.purple.llm_agent import call_llm_purple_agent
from policybeats.score import aggregate, RULE_KIND_TO_DIMENSION
from policybeats.trace import normalize_trace
from policybeats.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EpisodeResult,
    ExposedState,
    PolicyVerdict,
)


async def run_episode(episode, model: str) -> EpisodeResult:
    """Run one episode: LLM response -> trace -> score."""
    from policybeats.score import score_episode

    # Get LLM response
    response = await call_llm_purple_agent(
        user_message=episode.user_message,
        model=model,
    )

    # Build trace from response
    trace_events = [
        {"i": 0, "kind": "user_message", "actor": "user",
         "payload": {"content": episode.user_message}},
    ]
    event_i = 1

    if response.content:
        trace_events.append({
            "i": event_i, "kind": "agent_message", "actor": "agent",
            "payload": {"content": response.content},
        })
        event_i += 1

    for tc in response.tool_calls:
        call_id = tc.get("call_id", f"call_{event_i}")
        trace_events.append({
            "i": event_i, "kind": "tool_call", "actor": "agent",
            "payload": {"tool": tc["name"], "arguments": tc.get("arguments", {})},
            "call_id": call_id,
        })
        event_i += 1
        env = env_from_context({})
        tool_result = execute_tool(tc["name"], tc.get("arguments", {}), env)
        trace_events.append({
            "i": event_i, "kind": "tool_result", "actor": "tool",
            "payload": {"result": tool_result},
            "call_id": call_id,
        })
        event_i += 1

    trace = normalize_trace(trace_events)

    # Build bundle and score
    pack = get_policy_pack_for_episode(episode.episode_id)
    bundle = EpisodeBundle(
        episode_id=episode.episode_id,
        trace=trace,
        exposed_state=ExposedState(success=True, data={}),
        metadata=EpisodeMetadata(domain="gdpr"),
    )
    return score_episode(bundle, pack)


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="PolicyBeats LLM Benchmark")
    parser.add_argument("--model", default="ollama/qwen2.5:3b", help="LLM model")
    parser.add_argument("--runs", type=int, default=1, help="Runs per episode")
    args = parser.parse_args()

    print(f"\n{'='*60}")
    print(f"  PolicyBeats Benchmark")
    print(f"  Model: {args.model}")
    print(f"  Episodes: {len(GDPR_EPISODES)}")
    print(f"  Runs per episode: {args.runs}")
    print(f"{'='*60}\n")

    all_results: list[EpisodeResult] = []

    for ep in GDPR_EPISODES:
        run_results = []
        for run_i in range(args.runs):
            result = await run_episode(ep, args.model)
            run_results.append(result)

        # Pick worst result per episode (conservative)
        # If any run had a violation, count it as violation
        has_violation = any(r.policy.verdict == PolicyVerdict.VIOLATION for r in run_results)
        chosen = next(
            (r for r in run_results if r.policy.verdict == PolicyVerdict.VIOLATION),
            run_results[0],
        ) if has_violation else run_results[0]

        verdict_str = chosen.policy.verdict.value
        violations = [v.rule_id for v in chosen.policy.violations]
        status = "PASS" if verdict_str == "COMPLIANT" else "FAIL"
        print(f"  {ep.episode_id}: {status:4s}  {verdict_str}")
        if violations:
            for v in violations:
                print(f"    -> {v}")

        all_results.append(chosen)

    # Aggregate with new leaderboard dimensions
    results_tuple = tuple(sorted(all_results, key=lambda r: r.episode_id))
    summary = aggregate(results_tuple)

    print(f"\n{'='*60}")
    print(f"  LEADERBOARD SCORES (0-1, higher = better)")
    print(f"{'='*60}")
    print(f"  Safety:     {summary.safety:.3f}")
    print(f"  Compliance: {summary.compliance:.3f}")
    print(f"  Precision:  {summary.precision:.3f}")
    print(f"  Robustness: {summary.robustness:.3f}")
    print(f"  ─────────────────────")
    print(f"  Overall:    {summary.overall:.3f}")
    print(f"{'='*60}")

    # Diagnostics
    print(f"\n  Diagnostics:")
    for k, v in sorted(summary.diagnostics.items()):
        print(f"    {k}: {v:.3f}")

    # Per-rule breakdown
    if summary.rule_violation_rates:
        print(f"\n  Per-rule violation rates:")
        for rid, rate in summary.rule_violation_rates.items():
            dim = "?"
            # Look up dimension from violations
            for r in all_results:
                for viol in r.policy.violations:
                    if viol.rule_id == rid:
                        dim = RULE_KIND_TO_DIMENSION.get(viol.kind, "?")
                        break
                if dim != "?":
                    break
            print(f"    {rid}: {rate:.3f} ({dim})")

    print()


if __name__ == "__main__":
    asyncio.run(main())
