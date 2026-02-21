"""
CLI entry point for PI-Bench.

Supports both official leaderboard and custom runner modes.
"""

from __future__ import annotations

import argparse
import json
import sys
import asyncio
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


def cmd_score(args):
    """Score episodes against a policy (original command)."""
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


def cmd_leaderboard(args):
    """Run official leaderboard benchmark (all 9 dimensions)."""
    from pi_bench.a2a.engine import AssessmentEngine
    from pi_bench.a2a.mt_scenarios import ALL_SCENARIOS

    print("Running official PI-Bench leaderboard evaluation...")
    print(f"Agent URL: {args.agent_url}")
    print(f"Total scenarios: {len(ALL_SCENARIOS)}")
    print(f"Dimensions: 9 (all official)")

    if args.dry_run:
        print("\nDry run - scenarios that would be tested:")
        for scenario in ALL_SCENARIOS[:10]:
            print(f"  - {scenario.scenario_id}: {scenario.name}")
        print(f"  ... and {len(ALL_SCENARIOS) - 10} more")
        return 0

    async def run_assessment():
        engine = AssessmentEngine(requests_per_minute=args.rate_limit)
        report = await engine.assess(
            purple_url=args.agent_url,
            scenarios=ALL_SCENARIOS,
        )
        return report

    report = asyncio.run(run_assessment())

    # Format as official results
    results = report.to_dict()
    results.update({
        "benchmark": "pi-bench",
        "version": "1.0.0",
        "agent": {
            "name": args.agent_name or "unknown",
            "url": args.agent_url,
        },
    })

    # Output
    output_json = json.dumps(results, indent=2)
    if args.output:
        args.output.write_text(output_json)
        print(f"\n✓ Results written to {args.output}")
        print(f"✓ Overall Score: {report.overall_score:.2%}")
        print(f"✓ Total Violations: {report.total_violations}/{report.total_rule_checks}")
    else:
        print(output_json)

    return 0


def cmd_run(args):
    """Run custom evaluation (custom policies/scenarios)."""
    from pi_bench.a2a.engine import AssessmentEngine
    from pi_bench.registry import Registry
    from pi_bench.packs import load_scenarios

    print("Running custom PI-Bench evaluation...")
    print(f"Agent URL: {args.agent_url}")

    # Load scenarios
    scenarios = []
    for scenario_spec in args.scenarios.split(","):
        scenario_spec = scenario_spec.strip()

        # Check if it's a custom scenario
        try:
            scenario = Registry.get_scenario(scenario_spec)
            scenarios.append(scenario)
        except KeyError:
            # Try loading as official dimension
            try:
                dim_scenarios = load_scenarios(scenario_spec)
                scenarios.extend(dim_scenarios)
            except Exception:
                print(f"Warning: Could not load scenario '{scenario_spec}'")

    print(f"Total scenarios: {len(scenarios)}")

    async def run_assessment():
        engine = AssessmentEngine(requests_per_minute=args.rate_limit)
        report = await engine.assess(
            purple_url=args.agent_url,
            scenarios=scenarios,
        )
        return report

    report = asyncio.run(run_assessment())

    # Output
    output_json = json.dumps(report.to_dict(), indent=2)
    if args.output:
        args.output.write_text(output_json)
        print(f"\n✓ Results written to {args.output}")
        print(f"✓ Overall Score: {report.overall_score:.2%}")
    else:
        print(output_json)

    return 0


def cmd_verify(args):
    """Verify leaderboard submission results."""
    from pi_bench.leaderboard import verify_results

    print(f"Verifying results from {args.results_file}...")

    results = json.loads(args.results_file.read_text())
    valid, errors = verify_results(results)

    if valid:
        print("✓ Verification passed!")
        print(f"  Agent: {results['agent']['name']}")
        print(f"  Overall Score: {results['scores']['overall']:.2%}")
        return 0
    else:
        print("✗ Verification failed:")
        for error in errors:
            print(f"  - {error}")
        return 1


def cmd_list(args):
    """List available resources."""
    from pi_bench.registry import Registry
    from pi_bench.packs import CATEGORIES

    if args.resource_type == "policies":
        print("Official Policies (Dimensions):")
        for cat in CATEGORIES:
            print(f"  - {cat}")

        custom_policies = Registry.list_policies()
        custom_only = [p for p in custom_policies if p not in CATEGORIES]
        if custom_only:
            print("\nCustom Policies:")
            for policy in custom_only:
                print(f"  - {policy}")

    elif args.resource_type == "scenarios":
        custom_scenarios = Registry.list_scenarios()
        if custom_scenarios:
            print("Custom Scenarios:")
            for scenario in custom_scenarios:
                print(f"  - {scenario}")
        else:
            print("No custom scenarios registered.")

    elif args.resource_type == "dimensions":
        print("Official Dimensions (9):")
        for cat in CATEGORIES:
            print(f"  - {cat}")

    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="pi-bench",
        description="Deterministic policy compliance evaluator for AI agents",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # score command (original)
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
    score_parser.set_defaults(func=cmd_score)

    # leaderboard command
    leaderboard_parser = subparsers.add_parser(
        "leaderboard",
        help="Run official leaderboard benchmark (all 9 dimensions)"
    )
    leaderboard_parser.add_argument(
        "--agent-url",
        required=True,
        help="URL of purple agent A2A endpoint",
    )
    leaderboard_parser.add_argument(
        "--agent-name",
        help="Name of agent for results",
    )
    leaderboard_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output path for results JSON",
    )
    leaderboard_parser.add_argument(
        "--rate-limit",
        type=int,
        default=30,
        help="Requests per minute (default: 30)",
    )
    leaderboard_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be tested without running",
    )
    leaderboard_parser.set_defaults(func=cmd_leaderboard)

    # run command (custom)
    run_parser = subparsers.add_parser(
        "run",
        help="Run custom evaluation (custom policies/scenarios)"
    )
    run_parser.add_argument(
        "--agent-url",
        required=True,
        help="URL of purple agent A2A endpoint",
    )
    run_parser.add_argument(
        "--scenarios",
        required=True,
        help="Comma-separated scenario names or dimensions (e.g., 'compliance,my-scenario')",
    )
    run_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Output path for results JSON",
    )
    run_parser.add_argument(
        "--rate-limit",
        type=int,
        default=30,
        help="Requests per minute (default: 30)",
    )
    run_parser.set_defaults(func=cmd_run)

    # verify command
    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify leaderboard submission results"
    )
    verify_parser.add_argument(
        "results_file",
        type=Path,
        help="Path to results JSON file to verify",
    )
    verify_parser.set_defaults(func=cmd_verify)

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List available resources"
    )
    list_parser.add_argument(
        "resource_type",
        choices=["policies", "scenarios", "dimensions"],
        help="Type of resource to list",
    )
    list_parser.set_defaults(func=cmd_list)

    # version command
    version_parser = subparsers.add_parser("version", help="Show version")

    args = parser.parse_args()

    if args.command == "version":
        from pi_bench import __version__
        print(f"pi-bench {__version__}")
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
