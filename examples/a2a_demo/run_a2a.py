#!/usr/bin/env python3
"""A2A demo — start a purple agent server and run pi-bench assessment via A2A.

Usage:
    # Start server + run all scenarios
    python examples/a2a_demo/run_a2a.py --model gpt-4o-mini --port 8766

    # Connect to an already-running server
    python examples/a2a_demo/run_a2a.py --external --port 8766
"""

from __future__ import annotations

import argparse
import atexit
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

import httpx

from pi_bench.a2a.assessment import run_assessment
from pi_bench.a2a.results import to_agentbeats_results
from pi_bench.env import load_env
from pi_bench.metrics import (
    compute_metrics,
    compute_repeatability,
    format_metrics_summary,
    metrics_to_dict,
)

logger = logging.getLogger(__name__)


def wait_for_server(url: str, timeout: float = 30.0) -> bool:
    """Poll /health until the server is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{url}/health", timeout=5.0)
            if resp.status_code == 200:
                return True
        except httpx.ConnectError:
            pass
        time.sleep(0.5)
    return False


def main() -> None:
    load_env()

    parser = argparse.ArgumentParser(description="Run pi-bench assessment via A2A")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="Purple/tested-agent LiteLLM model name")
    parser.add_argument("--user-model", type=str, default="gpt-4.1-mini", help="User simulator LiteLLM model name")
    parser.add_argument("--user-kind", choices=["litellm", "scripted"], default="litellm", help="User simulator implementation to serve over A2A")
    parser.add_argument("--port", type=int, default=8766, help="Server port")
    parser.add_argument("--user-port", type=int, default=8768, help="A2A user simulator server port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Server host")
    parser.add_argument("--scenarios-dir", type=str, default="scenarios", help="Scenarios directory")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--max-steps", type=int, default=50, help="Max steps per scenario")
    parser.add_argument("--user-max-turns", type=int, default=8, help="Max simulated-user turns")
    parser.add_argument("--concurrency", type=int, default=1, help="Parallel A2A scenario workers")
    parser.add_argument("--retry-failed", type=int, default=0, help="Retry runtime/protocol failures N times")
    parser.add_argument("--save-to", type=str, default=None, help="Write full A2A assessment JSON report")
    parser.add_argument("--external", action="store_true", help="Connect to an already-running server")
    parser.add_argument("--serve-user", action="store_true", help="Start a local A2A user simulator server")
    parser.add_argument("--user-url", type=str, default=None, help="Connect to an already-running A2A user simulator")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    purple_url = f"http://{args.host}:{args.port}"
    user_url = args.user_url
    server_proc = None
    user_proc = None

    if not args.external:
        # Start the purple server as a subprocess
        server_cmd = [
            sys.executable, "examples/a2a_demo/purple_server.py",
            "--model", args.model,
            "--port", str(args.port),
            "--host", "0.0.0.0",
        ]
        if args.seed is not None:
            server_cmd.extend(["--seed", str(args.seed)])

        logger.info("Starting purple server: %s", " ".join(server_cmd))
        server_proc = subprocess.Popen(server_cmd)

        def cleanup():
            if server_proc and server_proc.poll() is None:
                logger.info("Stopping purple server (pid=%d)", server_proc.pid)
                server_proc.terminate()
                try:
                    server_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    server_proc.kill()

        atexit.register(cleanup)

        # Wait for server to be ready
        logger.info("Waiting for server at %s ...", purple_url)
        if not wait_for_server(purple_url):
            print(f"ERROR: Server did not start within 30s at {purple_url}")
            if server_proc.poll() is not None:
                print(f"Server process exited with code {server_proc.returncode}")
            sys.exit(1)
        logger.info("Server is ready")

    if args.serve_user and user_url:
        print("ERROR: Use either --serve-user or --user-url, not both")
        sys.exit(1)

    if args.serve_user:
        user_url = f"http://{args.host}:{args.user_port}"
        user_cmd = [
            sys.executable, "examples/a2a_demo/user_server.py",
            "--kind", args.user_kind,
            "--model", args.user_model,
            "--max-turns", str(args.user_max_turns),
            "--port", str(args.user_port),
            "--host", "0.0.0.0",
        ]
        if args.seed is not None:
            user_cmd.extend(["--seed", str(args.seed)])

        logger.info("Starting A2A user server: %s", " ".join(user_cmd))
        user_proc = subprocess.Popen(user_cmd)

        def cleanup_user():
            if user_proc and user_proc.poll() is None:
                logger.info("Stopping A2A user server (pid=%d)", user_proc.pid)
                user_proc.terminate()
                try:
                    user_proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    user_proc.kill()

        atexit.register(cleanup_user)

        logger.info("Waiting for A2A user server at %s ...", user_url)
        if not wait_for_server(user_url):
            print(f"ERROR: User server did not start within 30s at {user_url}")
            if user_proc.poll() is not None:
                print(f"User server process exited with code {user_proc.returncode}")
            sys.exit(1)
        logger.info("A2A user server is ready")

    # Run assessment
    config = {
        "scenarios_dir": args.scenarios_dir,
        "max_steps": args.max_steps,
        "seed": args.seed,
        "concurrency": args.concurrency,
        "retry_failed": args.retry_failed,
        "user_model": args.user_model,
    }
    if user_url:
        config["user_url"] = user_url

    print(f"\nRunning assessment against {purple_url}")
    print(f"  Purple model: {args.model}")
    print(f"  User: {user_url or f'local LiteLLMUser({args.user_model})'}")
    print(f"  Scenarios: {args.scenarios_dir}")
    print()

    try:
        results = run_assessment(purple_url, config)
    except Exception as exc:
        print(f"ERROR: Assessment failed: {exc}")
        sys.exit(1)

    metrics = compute_metrics(results)
    repeatability = compute_repeatability(results)
    metrics_payload = metrics_to_dict(metrics, repeatability=repeatability)
    agentbeats_results = to_agentbeats_results(
        agent_id=f"local-{args.model}-a2a",
        domain="policy_compliance",
        scenario_results=results,
    )

    if args.save_to:
        path = Path(args.save_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "info": {
                "mode": "a2a",
                "purple_url": purple_url,
                "agent_model": args.model,
                "user_url": user_url,
                "user_model": args.user_model,
                "user_kind": args.user_kind,
                "config": config,
            },
            "metrics": metrics_payload,
            "results": results,
            "agentbeats_results": agentbeats_results,
        }, default=str, sort_keys=True))

    # Print results
    for result in results:
        status = result.get("status", "unknown")
        scenario_id = result.get("scenario_id", "?")
        if status == "error":
            print(f"  [{status.upper()}] {scenario_id}: {result.get('error', 'unknown')}")
        else:
            passed = "PASS" if result.get("all_passed") else "FAIL"
            decision = result.get("canonical_decision", "?")
            duration = result.get("duration", 0)
            print(f"  [{passed}] {scenario_id}: decision={decision} ({duration:.1f}s)")

    # Summary
    print()
    passed = sum(1 for r in results if r.get("all_passed"))
    errors = sum(1 for r in results if r.get("status") == "error")
    total = len(results)
    print(f"Total: {total}  Passed: {passed}  Failed: {total - passed - errors}  Errors: {errors}")
    print()
    print(format_metrics_summary(metrics, repeatability))
    if args.save_to:
        print(f"Saved: {args.save_to}")

    if errors:
        sys.exit(2)


if __name__ == "__main__":
    main()
