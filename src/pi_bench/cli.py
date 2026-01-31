"""
CLI entry point for PolicyBeats.

Minimal interface for scoring episodes from JSON files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pi_bench.artifact import artifact_to_json, make_artifact
from pi_bench.policy import forbid_substring
from pi_bench.score import score_episode
from pi_bench.types import (
    EpisodeBundle,
    EpisodeMetadata,
    EventKind,
    ExposedState,
    PolicyPack,
    TraceEvent,
)


def parse_episode_bundle(data: dict) -> EpisodeBundle:
    """Parse a JSON dict into an EpisodeBundle."""
    trace = tuple(
        TraceEvent(
            i=event["i"],
            kind=EventKind(event["kind"]),
            actor=event["actor"],
            payload=event.get("payload", {}),
            call_id=event.get("call_id"),
        )
        for event in data.get("trace", [])
    )

    exposed_state = ExposedState(
        success=data.get("exposed_state", {}).get("success", False),
        end_reason=data.get("exposed_state", {}).get("end_reason"),
        data=data.get("exposed_state", {}).get("data", {}),
    )

    metadata = EpisodeMetadata(
        domain=data.get("metadata", {}).get("domain"),
        seed=data.get("metadata", {}).get("seed"),
        config=data.get("metadata", {}).get("config", {}),
    )

    return EpisodeBundle(
        episode_id=data["episode_id"],
        trace=trace,
        exposed_state=exposed_state,
        metadata=metadata,
    )


def parse_policy_pack(data: dict) -> PolicyPack:
    """Parse a JSON dict into a PolicyPack (simplified for now)."""
    from pi_bench.types import ResolutionSpec, RuleScope, RuleSpec

    rules = []
    for rule_data in data.get("rules", []):
        rules.append(
            RuleSpec(
                rule_id=rule_data["rule_id"],
                kind=rule_data["kind"],
                params=rule_data.get("params", {}),
                scope=RuleScope(rule_data.get("scope", "trace")),
                description=rule_data.get("description"),
            )
        )

    return PolicyPack(
        policy_pack_id=data["policy_pack_id"],
        version=data["version"],
        rules=tuple(rules),
        resolution=ResolutionSpec(),
    )


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="policybeats",
        description="Deterministic policy compliance evaluator for AI agents",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # score command
    score_parser = subparsers.add_parser("score", help="Score episodes against a policy")
    score_parser.add_argument(
        "episodes",
        type=Path,
        help="Path to episodes JSON file (list of episode bundles)",
    )
    score_parser.add_argument(
        "--policy",
        type=Path,
        help="Path to policy pack JSON file",
    )
    score_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output path for artifact JSON (default: stdout)",
    )

    # version command
    subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "version":
        from policybeats import __version__

        print(f"policybeats {__version__}")
        return 0

    if args.command == "score":
        # Load episodes
        episodes_data = json.loads(args.episodes.read_text())
        if isinstance(episodes_data, dict):
            episodes_data = [episodes_data]

        bundles = [parse_episode_bundle(ep) for ep in episodes_data]

        # Load or create default policy
        if args.policy:
            policy_data = json.loads(args.policy.read_text())
            policy = parse_policy_pack(policy_data)
        else:
            # Default minimal policy
            policy = PolicyPack(
                policy_pack_id="default",
                version="1.0",
                rules=(forbid_substring("no-secrets", "SECRET"),),
            )

        # Score all episodes
        results = tuple(score_episode(bundle, policy) for bundle in bundles)

        # Create artifact
        artifact = make_artifact(results, policy)

        # Output
        output_json = artifact_to_json(artifact)
        if args.output:
            args.output.write_text(output_json)
            print(f"Wrote artifact to {args.output}")
        else:
            print(output_json)

        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
