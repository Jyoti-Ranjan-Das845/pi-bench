"""
FastAPI A2A Server for PI-Bench Green Agent.

Uses a2a.server library for proper A2A protocol compliance.

Endpoints:
- GET /.well-known/agent.json - Agent card (discovery)
- POST / - A2A JSON-RPC endpoint
- GET /health - Health check
- GET /scenarios - List available scenarios
- POST /assess/multi-turn - Direct assessment endpoint (backwards compatibility)

Flow:
1. Purple sends message via A2A
2. Green runs GDPR scenarios
3. Green evaluates responses against policy rules
4. Results returned as artifacts via TaskUpdater
"""

from __future__ import annotations

import argparse
import logging
import os
from typing import Any

import uvicorn
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from fastapi import FastAPI, HTTPException
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from pi_bench.a2a.engine import run_multi_turn_assessment
from pi_bench.a2a.executor import Executor
from pi_bench.a2a.mt_scenarios import ALL_SCENARIOS

logger = logging.getLogger(__name__)


# === Agent Card ===


def get_agent_card(url: str | None = None) -> AgentCard:
    """
    Return the agent card for discovery.

    Served at /.well-known/agent.json
    """
    return AgentCard(
        name="PI-Bench",
        description=f"GDPR policy compliance benchmark for AI agents ({len(ALL_SCENARIOS)} scenarios). "
        "Deterministic evaluation of whether agents comply with GDPR operational policies across "
        "6 surfaces: Access, Privacy, Disclosure, Process, Safety, and Governance.",
        version="0.1.0",
        url=url or os.getenv("AGENT_URL", "http://localhost:8000"),
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            assessment=True,
            streaming=False,
            tools=False,
        ),
        skills=[
            AgentSkill(
                id="gdpr_policy_assessment",
                name="GDPR Policy Compliance Assessment",
                description=f"Evaluates AI agents on GDPR operational policy compliance "
                f"across 6 surfaces and {len(ALL_SCENARIOS)} scenarios. Deterministic evaluation "
                "with no LLM judges.",
                tags=["gdpr", "policy", "compliance", "assessment", "benchmark"],
                examples=[
                    """
{
  "participants": {
    "agent": "http://purple-agent:9009/"
  },
  "config": {
    "domain": "policy_compliance"
  }
}
""".strip()
                ],
            )
        ],
    )


# === Backwards Compatibility Endpoints ===


async def health(request) -> JSONResponse:
    """Health check endpoint."""
    return JSONResponse(
        {"status": "healthy", "agent": "pi-bench-green", "policy_type": "gdpr"}
    )


async def list_scenarios(request) -> JSONResponse:
    """List available GDPR scenarios."""
    return JSONResponse(
        {
            "policy_type": "gdpr",
            "count": len(ALL_SCENARIOS),
            "scenarios": [
                {
                    "id": s.scenario_id,
                    "name": s.name,
                    "surface": s.surface,
                    "description": s.description,
                }
                for s in ALL_SCENARIOS
            ],
        }
    )


async def multi_turn_assess(request) -> JSONResponse:
    """
    Multi-turn GDPR assessment endpoint (backwards compatibility).

    Query parameters:
    - purple_agent_url: URL of purple agent to assess
    """
    params = dict(request.query_params)
    purple_agent_url = params.get("purple_agent_url")

    if not purple_agent_url:
        raise HTTPException(status_code=400, detail="Missing purple_agent_url parameter")

    try:
        report = await run_multi_turn_assessment(purple_url=purple_agent_url)
        return JSONResponse(report.to_dict())
    except Exception as e:
        logger.exception("Multi-turn assessment failed")
        raise HTTPException(status_code=500, detail=str(e))


# === Application Factory ===


def create_app(agent_url: str | None = None, output_file: str | None = None) -> Starlette:
    """
    Create the PI-Bench Green Agent application.

    Combines A2A server with backwards compatibility routes.

    Args:
        agent_url: Public URL for agent card discovery
        output_file: Optional file path to write results JSON
    """
    # Create agent card
    agent_card = get_agent_card(url=agent_url)

    # Create executor and request handler
    executor = Executor(output_file=output_file)
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    # Create A2A server
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # Build the A2A server
    a2a_starlette = a2a_app.build()

    # Create backwards compatibility routes
    compat_routes = [
        Route("/health", health),
        Route("/scenarios", list_scenarios),
        Route("/assess/multi-turn", multi_turn_assess, methods=["POST", "GET"]),
    ]

    # Combine A2A server with compat routes
    # Mount compat routes, then mount A2A server at root
    app = Starlette(
        routes=[
            *compat_routes,
            Mount("/", app=a2a_starlette),
        ]
    )

    return app


# === Entry Point ===


def main():
    """Run the server."""
    parser = argparse.ArgumentParser(description="PI-Bench Green Agent")
    parser.add_argument("--host", default="0.0.0.0", help="Server host")
    parser.add_argument("--port", type=int, default=9009, help="Server port")
    parser.add_argument("--card-url", help="Public URL for agent card discovery")
    parser.add_argument(
        "--output-file",
        default="/app/output/results.json",
        help="Path to write results JSON (default: /app/output/results.json)",
    )
    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("PI-Bench Green Agent starting...")
    logger.info(f"Loaded {len(ALL_SCENARIOS)} GDPR scenarios")

    # Store card URL in environment if provided
    if args.card_url:
        os.environ["AGENT_URL"] = args.card_url

    logger.info(f"Results will be written to: {args.output_file}")

    # Create app
    app = create_app(agent_url=args.card_url, output_file=args.output_file)

    # Run server
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
