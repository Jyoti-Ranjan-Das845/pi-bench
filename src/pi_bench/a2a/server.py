"""A2A Server — AgentBeats-compliant green agent HTTP server.

Exposes pi-bench as an A2A agent that can receive assessment requests
and evaluate purple agents against policy-compliance scenarios across
all domains (finra, retail, helpdesk).

Usage:
    pi-bench-green --host 0.0.0.0 --port 9009

Endpoints:
    /.well-known/agent.json  — A2A agent card discovery
    /a2a/message/send        — A2A JSON-RPC 2.0 message handler
    /health                  — Container liveness check
    /scenarios               — List available scenario files
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from pi_bench import __version__
from pi_bench.a2a.executor import PIBenchExecutor
from pi_bench.scenario_loader import default_workspace_root

# The green server is aware of the bootstrap extension
# (urn:pi-bench:policy-bootstrap:v1) but does not need to declare it in its
# own AgentCard — the extension is negotiated between the green *adapter*
# (purple_adapter.py) and the purple agent's card.

logger = logging.getLogger(__name__)

SCENARIOS_DIR = default_workspace_root() / "scenarios"


def build_agent_card(host: str, port: int, card_url: str | None = None) -> AgentCard:
    """Build the A2A agent card for pi-bench."""
    skill = AgentSkill(
        id="policy_compliance_assessment",
        name="Policy Compliance Assessment",
        description=(
            "Evaluates AI agents on policy compliance across multiple "
            "domains: AML/FINRA financial compliance, retail refund SOPs, "
            "and IT helpdesk access control. Tests procedural compliance, "
            "decision-making under pressure, escalation accuracy, and "
            "policy interpretation."
        ),
        tags=[
            "policy", "compliance", "assessment", "benchmark",
            "finra", "aml", "retail", "helpdesk",
        ],
        examples=[
            "Evaluate agent on policy compliance scenarios",
            "Run AML compliance assessment",
            "Test retail refund SOP compliance",
            "Assess helpdesk access control procedures",
        ],
    )

    return AgentCard(
        name="PI-Bench",
        description=(
            "Policy Interpretation Benchmark — evaluates AI agents on "
            "policy interpretation and compliance across financial services "
            "(FINRA AML), retail customer service, and IT helpdesk domains."
        ),
        url=card_url or f"http://{host}:{port}/",
        version=__version__,
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(),
        skills=[skill],
    )


async def health(request: Request) -> JSONResponse:
    """Health check endpoint for container orchestration."""
    return JSONResponse({"status": "ok"})


async def list_scenarios(request: Request) -> JSONResponse:
    """List available scenario files across all domains."""
    from pi_bench.scenario_loader import discover_scenarios

    scenarios_dir = Path(getattr(request.app.state, "scenarios_dir", SCENARIOS_DIR))
    scenario_files = discover_scenarios(scenarios_dir)
    scenarios = []
    for path in scenario_files:
        try:
            data = json.loads(path.read_text())
            meta = data.get("meta", {})
            try:
                file_name = str(path.relative_to(scenarios_dir))
            except ValueError:
                file_name = str(path)
            scenarios.append({
                "scenario_id": meta.get("scenario_id", path.stem),
                "domain": meta.get("domain", "unknown"),
                "label": data.get("label", "?"),
                "file": file_name,
            })
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.warning("Failed to read scenario %s: %s", path, exc)
            scenarios.append({
                "scenario_id": path.stem,
                "file": path.name,
                "error": str(exc),
            })

    # Group counts by domain
    domain_counts: dict[str, int] = {}
    for s in scenarios:
        d = s.get("domain", "unknown")
        domain_counts[d] = domain_counts.get(d, 0) + 1

    return JSONResponse({
        "count": len(scenarios),
        "domains": domain_counts,
        "scenarios": scenarios,
    })


def create_app(
    host: str = "0.0.0.0",
    port: int = 9009,
    card_url: str | None = None,
    scenarios_dir: str | Path | None = None,
    concurrency: int = 1,
) -> Starlette:
    """Create the full Starlette application with A2A + health routes."""
    agent_card = build_agent_card(host, port, card_url=card_url)

    request_handler = DefaultRequestHandler(
        agent_executor=PIBenchExecutor(concurrency=concurrency),
        task_store=InMemoryTaskStore(),
    )

    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    app = a2a_app.build(
        agent_card_url="/.well-known/agent.json",
        rpc_url="/a2a/message/send",
    )
    app.routes.append(
        Route(
            "/",
            a2a_app._handle_requests,
            methods=["POST"],
            name="a2a_handler_legacy",
        )
    )
    app.routes.append(
        Route(
            "/.well-known/agent-card.json",
            a2a_app._handle_get_agent_card,
            methods=["GET"],
            name="agent_card_legacy",
        )
    )
    app.state.scenarios_dir = Path(scenarios_dir) if scenarios_dir else SCENARIOS_DIR
    app.state.concurrency = max(1, int(concurrency))

    app.routes.append(Route("/health", health))
    app.routes.append(Route("/scenarios", list_scenarios))

    logger.info("PI-Bench A2A server configured on %s:%d", host, port)
    return app


def main() -> None:
    """Entry point for pi-bench-green CLI."""
    from pi_bench.env import load_env

    load_env()
    parser = argparse.ArgumentParser(
        description="PI-Bench A2A Green Agent Server"
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)",
    )
    parser.add_argument(
        "--port", type=int, default=9009,
        help="Port to listen on (default: 9009)",
    )
    parser.add_argument(
        "--card-url", default=None,
        help="Public URL for agent card (for AgentBeats Docker)",
    )
    parser.add_argument(
        "--scenarios-dir", default=str(SCENARIOS_DIR),
        help="Scenarios directory to expose and assess",
    )
    parser.add_argument(
        "--concurrency", type=int, default=1,
        help="Maximum parallel A2A scenario workers (default: 1)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    from pi_bench.scenario_loader import discover_scenarios
    scenarios_dir = Path(args.scenarios_dir)
    scenario_count = len(discover_scenarios(scenarios_dir))
    logger.info("Found %d scenario files in %s", scenario_count, scenarios_dir)

    app = create_app(
        host=args.host,
        port=args.port,
        card_url=args.card_url,
        scenarios_dir=scenarios_dir,
        concurrency=args.concurrency,
    )
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
