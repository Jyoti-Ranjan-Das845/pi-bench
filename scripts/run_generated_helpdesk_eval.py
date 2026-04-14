#!/usr/bin/env python3
"""Run generated helpdesk scenarios and classify baseline pass/fail.

Generated scenarios that the baseline example agent fully passes are marked as
``leave_out_baseline_passed`` because they are likely too easy for promotion.
Scenarios that the baseline fails are marked ``review_candidate_baseline_failed``.
The script does not move, delete, or promote any scenario files.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from pi_bench.agents import LiteLLMAgent
from pi_bench.env import load_env
from pi_bench.evaluator.generated_scenario_checks import (
    validate_generated_scenario_file,
)
from pi_bench.metrics import compute_metrics, compute_repeatability, metrics_to_dict
from pi_bench.runner import run_domain
from pi_bench.scenario_loader import default_workspace_root, load
from pi_bench.users.user import LiteLLMUser


def _default_output_dir(workspace_root: Path) -> Path:
    run_id = time.strftime("%Y%m%d_%H%M%S")
    return workspace_root / "reports" / "generated_helpdesk_eval" / run_id


def _discover_generated_paths(scenarios_dir: Path, pattern: str) -> list[Path]:
    return sorted(
        p for p in scenarios_dir.glob(pattern)
        if p.is_file() and p.suffix == ".json"
    )


def _load_generated_domain(paths: list[Path], workspace_root: Path) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    for scenario_path in paths:
        loaded = load(scenario_path, workspace_root=workspace_root)
        task = loaded["task"]
        task["_scenario_path"] = str(scenario_path)
        task["_source_path"] = str(scenario_path)
        tasks.append(task)

    def get_environment(task: dict[str, Any] | None = None) -> dict[str, Any]:
        if task is None or "_scenario_path" not in task:
            raise ValueError("Generated-helpdesk runner requires a scenario task")
        return load(task["_scenario_path"], workspace_root=workspace_root)["env"]

    return {
        "name": "generated_helpdesk",
        "tasks": tasks,
        "get_environment": get_environment,
    }


def _check_static_validation(
    paths: list[Path],
    workspace_root: Path,
) -> list[dict[str, Any]]:
    failures = []
    for path in paths:
        errors = validate_generated_scenario_file(path, workspace_root)
        if errors:
            failures.append(
                {
                    "path": str(path),
                    "errors": errors,
                }
            )
    return failures


def _scenario_score(sim: dict[str, Any]) -> float:
    dimensions = sim.get("dimensions") or {}
    total = 0
    passed = 0
    for dim in dimensions.values():
        checks = dim.get("checks") or []
        total += len(checks)
        passed += sum(1 for check in checks if check.get("passed"))
    return passed / total if total else 0.0


def _tool_names(sim: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for msg in sim.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "assistant":
            names.extend(
                tc.get("name", "")
                for tc in msg.get("tool_calls") or []
                if tc.get("name")
            )
    return names


def _tool_error_count(sim: dict[str, Any]) -> int:
    count = 0
    for msg in sim.get("messages") or []:
        if not isinstance(msg, dict):
            continue
        if msg.get("role") == "tool" and msg.get("error"):
            count += 1
        if msg.get("role") == "multi_tool":
            count += sum(
                1
                for sub in msg.get("tool_messages") or []
                if isinstance(sub, dict) and sub.get("error")
            )
    return count


def _summarize_results(result: dict[str, Any]) -> dict[str, Any]:
    simulations = result.get("simulations", [])
    source_by_id = {
        task.get("id") or task.get("scenario_id"): task.get("_source_path")
        for task in result.get("tasks", [])
        if isinstance(task, dict)
    }
    rows = []
    for sim in sorted(simulations, key=lambda s: s.get("task_id", "")):
        all_passed = bool(sim.get("all_passed"))
        status = sim.get("status", "unknown")
        if status != "completed":
            classification = "runtime_error"
        elif all_passed:
            classification = "leave_out_baseline_passed"
        else:
            classification = "review_candidate_baseline_failed"

        rows.append(
            {
                "scenario_id": sim.get("task_id") or sim.get("scenario_id"),
                "source_path": source_by_id.get(sim.get("task_id") or sim.get("scenario_id")),
                "label": sim.get("label"),
                "leaderboard_primary": sim.get("leaderboard_primary"),
                "status": status,
                "classification": classification,
                "all_passed": all_passed,
                "score": _scenario_score(sim),
                "termination_reason": sim.get("termination_reason"),
                "canonical_decision": sim.get("canonical_decision"),
                "decision_error": sim.get("decision_error"),
                "event_flags": sim.get("event_flags", {}),
                "tool_calls": _tool_names(sim),
                "tool_error_count": _tool_error_count(sim),
            }
        )

    total = len(rows)
    passed = sum(1 for row in rows if row["classification"] == "leave_out_baseline_passed")
    failed = sum(
        1
        for row in rows
        if row["classification"] == "review_candidate_baseline_failed"
    )
    runtime_errors = sum(1 for row in rows if row["classification"] == "runtime_error")

    return {
        "total": total,
        "baseline_passed_leave_out": passed,
        "baseline_failed_review_candidates": failed,
        "runtime_errors": runtime_errors,
        "baseline_pass_rate": passed / total if total else 0.0,
        "rows": rows,
    }


def _write_markdown_report(
    path: Path,
    summary: dict[str, Any],
    result: dict[str, Any],
    raw_results_path: Path,
    args: argparse.Namespace,
) -> None:
    metrics = result.get("metrics", {})
    lines = [
        "# Generated Helpdesk Baseline Evaluation",
        "",
        f"- Raw results: `{raw_results_path}`",
        f"- Scenarios directory: `{args.scenarios_dir}`",
        f"- Pattern: `{args.pattern}`",
        f"- Agent model: `{args.agent_llm}`",
        f"- User model: `{args.user_llm}`",
        f"- Concurrency: `{args.concurrency}`",
        f"- Seed: `{args.seed}`",
        f"- Max steps: `{args.max_steps}`",
        "",
        "## Summary",
        "",
        f"- Total generated scenarios: `{summary['total']}`",
        f"- Baseline fully passed, leave out: `{summary['baseline_passed_leave_out']}`",
        f"- Baseline failed, review candidates: `{summary['baseline_failed_review_candidates']}`",
        f"- Runtime errors: `{summary['runtime_errors']}`",
        f"- Baseline pass rate: `{summary['baseline_pass_rate']:.1%}`",
        f"- Overall score: `{metrics.get('overall_score', 0.0):.1%}`",
        f"- Compliance rate: `{metrics.get('compliance_rate', 0.0):.1%}`",
        "",
        "## Leave Out Because Baseline Passed",
        "",
    ]

    passed_rows = [
        row
        for row in summary["rows"]
        if row["classification"] == "leave_out_baseline_passed"
    ]
    if passed_rows:
        lines.extend(_rows_table(passed_rows))
    else:
        lines.append("_None._")

    lines.extend(
        [
            "",
            "## Review Candidates Because Baseline Failed",
            "",
        ]
    )
    failed_rows = [
        row
        for row in summary["rows"]
        if row["classification"] == "review_candidate_baseline_failed"
    ]
    if failed_rows:
        lines.extend(_rows_table(failed_rows))
    else:
        lines.append("_None._")

    lines.extend(
        [
            "",
            "## Runtime Errors",
            "",
        ]
    )
    error_rows = [
        row for row in summary["rows"] if row["classification"] == "runtime_error"
    ]
    if error_rows:
        lines.extend(_rows_table(error_rows))
    else:
        lines.append("_None._")

    path.write_text("\n".join(lines) + "\n")


def _rows_table(rows: list[dict[str, Any]]) -> list[str]:
    lines = [
        "| Scenario | Label | Column | Score | Decision | Termination | Tool Errors |",
        "|---|---|---|---:|---|---|---:|",
    ]
    for row in rows:
        decision = row.get("canonical_decision") or row.get("decision_error") or ""
        lines.append(
            "| {scenario_id} | {label} | {column} | {score:.1%} | {decision} | {term} | {tool_errors} |".format(
                scenario_id=row.get("scenario_id", ""),
                label=row.get("label", ""),
                column=row.get("leaderboard_primary", ""),
                score=row.get("score", 0.0),
                decision=decision,
                term=row.get("termination_reason", ""),
                tool_errors=row.get("tool_error_count", 0),
            )
        )
    return lines


def main() -> int:
    load_env()

    workspace_root = default_workspace_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=workspace_root,
        help="Workspace root for resolving domains and policies.",
    )
    parser.add_argument(
        "--scenarios-dir",
        type=Path,
        default=workspace_root / "XYZscenarios" / "helpdesk",
        help="Directory containing generated helpdesk scenario JSON files.",
    )
    parser.add_argument(
        "--pattern",
        default="*gen*.json",
        help="Generated scenario filename glob inside --scenarios-dir.",
    )
    parser.add_argument("--agent-llm", default="gpt-4o-mini")
    parser.add_argument("--user-llm", default="gpt-4.1-mini")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-steps", type=int, default=40)
    parser.add_argument("--num-trials", type=int, default=1)
    parser.add_argument("--retry-failed", type=int, default=0)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--no-static-validation",
        action="store_true",
        help="Skip generated-scenario structural/tool validation before LLM runs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list matching generated scenarios; do not call models.",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        raise SystemExit("--concurrency must be >= 1")
    if args.num_trials < 1:
        raise SystemExit("--num-trials must be >= 1")

    scenarios_dir = args.scenarios_dir
    paths = _discover_generated_paths(scenarios_dir, args.pattern)
    if not paths:
        raise SystemExit(
            f"No generated scenario JSON files matched {args.pattern!r} in {scenarios_dir}"
        )

    print(f"Found {len(paths)} generated helpdesk scenario(s):")
    for path in paths:
        print(f"  - {path}")

    if args.dry_run:
        return 0

    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Put it in .env or export it first.")

    if not args.no_static_validation:
        static_failures = _check_static_validation(paths, args.workspace_root)
        if static_failures:
            output_dir = args.output_dir or _default_output_dir(args.workspace_root)
            output_dir.mkdir(parents=True, exist_ok=True)
            static_path = output_dir / "static_validation_failures.json"
            static_path.write_text(json.dumps(static_failures, indent=2))
            print(f"Static validation failed. Details: {static_path}")
            return 1

    output_dir = args.output_dir or _default_output_dir(args.workspace_root)
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_results_path = output_dir / "raw_results.json"
    summary_json_path = output_dir / "summary.json"
    report_path = output_dir / "report.md"

    domain = _load_generated_domain(paths, args.workspace_root)

    def agent_factory() -> LiteLLMAgent:
        return LiteLLMAgent(model_name=args.agent_llm)

    def user_factory() -> LiteLLMUser:
        return LiteLLMUser(model_name=args.user_llm)

    print(
        f"Running generated helpdesk set with agent={args.agent_llm}, "
        f"user={args.user_llm}, concurrency={args.concurrency}"
    )
    result = run_domain(
        domain=domain,
        agent=agent_factory(),
        user=user_factory(),
        num_trials=args.num_trials,
        seed=args.seed,
        max_concurrency=args.concurrency,
        save_to=raw_results_path,
        max_steps=args.max_steps,
        solo=False,
        retry_failed=args.retry_failed,
        agent_factory=agent_factory if args.concurrency > 1 else None,
        user_factory=user_factory if args.concurrency > 1 else None,
    )

    metrics = metrics_to_dict(
        compute_metrics(result["simulations"]),
        repeatability=compute_repeatability(result["simulations"]),
    )
    result["metrics"] = metrics
    summary = _summarize_results(result)
    summary_json_path.write_text(json.dumps(summary, indent=2, default=str))
    _write_markdown_report(report_path, summary, result, raw_results_path, args)

    print()
    print(f"Raw results: {raw_results_path}")
    print(f"Summary JSON: {summary_json_path}")
    print(f"Report: {report_path}")
    print()
    print(f"Total generated scenarios: {summary['total']}")
    print(f"Baseline fully passed, leave out: {summary['baseline_passed_leave_out']}")
    print(f"Baseline failed, review candidates: {summary['baseline_failed_review_candidates']}")
    print(f"Runtime errors: {summary['runtime_errors']}")
    print(f"Baseline pass rate: {summary['baseline_pass_rate']:.1%}")

    return 1 if summary["runtime_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
