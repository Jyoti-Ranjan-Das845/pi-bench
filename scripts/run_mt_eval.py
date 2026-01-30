#!/usr/bin/env python3
"""
Run multi-turn GDPR evaluation against a purple agent.

Starts the purple agent server, runs all 8 GDPR scenarios,
and prints trajectory + final outcome scores.

Usage:
    python scripts/run_mt_eval.py                              # default: gpt-4o-mini
    python scripts/run_mt_eval.py --model ollama/gemma2:9b     # local Ollama
    python scripts/run_mt_eval.py --model gpt-4o               # OpenAI
    python scripts/run_mt_eval.py --scenario GDPR-MT-006       # single scenario
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

# Ensure project root on path
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root / "src"))

# Load .env.local
env_file = project_root / ".env.local"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            val = val.strip().strip('"').strip("'")
            if val and key.strip() not in os.environ:
                os.environ[key.strip()] = val

from policybeats.a2a.engine import run_multi_turn_assessment
from policybeats.a2a.mt_scenarios import ALL_SCENARIOS


def print_report(report) -> None:
    """Print a human-readable assessment report."""
    print("\n" + "=" * 70)
    print("MULTI-TURN GDPR ASSESSMENT REPORT")
    print("=" * 70)
    print(f"Target: {report.target_agent}")
    print(f"Time:   {report.timestamp.isoformat()}")
    print(f"Turns:  {report.total_turns}")
    print(f"Rule checks: {report.total_rule_checks}")
    print(f"Violations:  {report.total_violations}")
    print()

    # Per-scenario results
    print("-" * 70)
    print(f"{'Scenario':<20} {'Category':<15} {'Turns':>5} {'Pass':>5} {'Fail':>5} {'Rate':>8}")
    print("-" * 70)
    for sid, sr in report.scenario_results.items():
        print(
            f"{sid:<20} {sr['category']:<15} {sr['turns']:>5} "
            f"{sr['passed']:>5} {sr['failed']:>5} {sr['compliance_rate']:>7.1%}"
        )

    # Violations detail
    if report.violations:
        print()
        print("-" * 70)
        print("VIOLATIONS:")
        print("-" * 70)
        for v in report.violations:
            print(f"  [{v.severity}] {v.scenario_id} turn {v.turn_number}: {v.rule_id}")
            if v.evidence:
                print(f"    Evidence: {v.evidence[:120]}")

    # Per-rule pass rates
    if report.scores_by_rule:
        print()
        print("-" * 70)
        print("PER-RULE COMPLIANCE:")
        print("-" * 70)
        for rule_id, rate in sorted(report.scores_by_rule.items()):
            bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
            print(f"  {rule_id:<35} {bar} {rate:.0%}")

    # Category scores
    if report.scores_by_category:
        print()
        print("-" * 70)
        print("CATEGORY SCORES:")
        print("-" * 70)
        for cat, score in sorted(report.scores_by_category.items()):
            bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
            print(f"  {cat:<20} {bar} {score:.0%}")

    # 9-Column Task Type Scores (π-bench leaderboard)
    NINE_COLUMNS = [
        "compliance", "understanding", "robustness", "process", "restraint",
        "conflict_resolution", "detection", "explainability", "adaptation",
    ]
    if report.scores_by_task_type:
        print()
        print("-" * 70)
        print("9-COLUMN LEADERBOARD SCORES:")
        print("-" * 70)
        for col in NINE_COLUMNS:
            score = report.scores_by_task_type.get(col, 0.0)
            bar = "█" * int(score * 20) + "░" * (20 - int(score * 20))
            print(f"  {col:<22} {bar} {score:.0%}")

    # Run Metrics
    if report.run_metrics:
        m = report.run_metrics
        print()
        print("-" * 70)
        print("RUN METRICS (call counts):")
        print("-" * 70)
        print(f"  A2A calls (HTTP POST to purple):  {m.a2a_calls}")
        print(f"  Purple LLM calls (inferred):      {m.purple_llm_calls}")
        print(f"  Tool executions (green-side):      {m.tool_executions}")
        print(f"  User driver LLM calls (dynamic):   {m.user_driver_llm_calls}")

    # Overall
    print()
    print("=" * 70)
    overall = report.overall_score
    bar = "█" * int(overall * 20) + "░" * (20 - int(overall * 20))
    print(f"OVERALL COMPLIANCE:  {bar} {overall:.1%}")
    print("=" * 70)


async def run_with_server(model: str, scenario_filter: str | None, port: int) -> None:
    """Start purple agent server and run assessment."""
    import uvicorn
    from policybeats.purple.llm_agent import create_llm_server

    app = create_llm_server(model=model, port=port)
    purple_url = f"http://localhost:{port}"

    # Start server in background
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)

    async def serve():
        await server.serve()

    server_task = asyncio.create_task(serve())

    # Wait for server to be ready
    import aiohttp
    for _ in range(30):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{purple_url}/health", timeout=aiohttp.ClientTimeout(total=2)) as r:
                    if r.status == 200:
                        break
        except Exception:
            pass
        await asyncio.sleep(0.5)
    else:
        print("ERROR: Purple agent server failed to start", file=sys.stderr)
        server.should_exit = True
        return

    print(f"Purple agent ready: {purple_url} (model={model})")

    # Filter scenarios if requested
    scenarios = None
    if scenario_filter:
        scenarios = [s for s in ALL_SCENARIOS if s.scenario_id == scenario_filter]
        if not scenarios:
            print(f"ERROR: No scenario matching '{scenario_filter}'", file=sys.stderr)
            print(f"Available: {[s.scenario_id for s in ALL_SCENARIOS]}")
            server.should_exit = True
            return

    # Run assessment
    t0 = time.time()
    report = await run_multi_turn_assessment(
        purple_url=purple_url,
        scenarios=scenarios,
    )
    elapsed = time.time() - t0

    print_report(report)
    print(f"\nCompleted in {elapsed:.1f}s")

    # Save JSON artifact
    out_dir = Path("exps") / f"mt_eval_{time.strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    artifact = {
        "model": model,
        "timestamp": report.timestamp.isoformat(),
        "total_turns": report.total_turns,
        "total_rule_checks": report.total_rule_checks,
        "total_violations": report.total_violations,
        "overall_score": report.overall_score,
        "scores_by_rule": report.scores_by_rule,
        "scores_by_category": report.scores_by_category,
        "scores_by_task_type": report.scores_by_task_type,
        "run_metrics": report.run_metrics.to_dict() if report.run_metrics else {},
        "scenario_results": report.scenario_results,
        "violations": [
            {
                "rule_id": v.rule_id,
                "scenario_id": v.scenario_id,
                "turn_number": v.turn_number,
                "severity": v.severity,
                "evidence": v.evidence,
            }
            for v in report.violations
        ],
    }
    artifact_path = out_dir / "report.json"
    artifact_path.write_text(json.dumps(artifact, indent=2))
    print(f"Report saved: {artifact_path}")

    # Save AgentBeats-compatible results JSON
    from policybeats.a2a.results import report_to_agentbeats
    agentbeats_results = report_to_agentbeats(report, report.target_agent, elapsed)
    agentbeats_path = out_dir / "agentbeats_results.json"
    agentbeats_path.write_text(json.dumps(agentbeats_results, indent=2))
    print(f"AgentBeats results: {agentbeats_path}")

    server.should_exit = True
    await server_task


def main():
    parser = argparse.ArgumentParser(description="Run multi-turn GDPR evaluation")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model for purple agent")
    parser.add_argument("--scenario", default=None, help="Run specific scenario (e.g. GDPR-MT-006)")
    parser.add_argument("--port", type=int, default=8099, help="Purple agent port")
    args = parser.parse_args()

    asyncio.run(run_with_server(args.model, args.scenario, args.port))


if __name__ == "__main__":
    main()
