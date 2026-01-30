"""
FastAPI A2A Server for PolicyBeats Green Agent.

Endpoints:
- GET /.well-known/agent.json - Agent card (discovery)
- POST /a2a/message/send - Receive A2A messages from Purple
- POST /assess - Direct assessment endpoint (testing)

Flow:
1. Purple sends message via A2A
2. Green runs GDPR scenarios
3. Green evaluates responses against policy rules
4. Results pushed to GitHub leaderboard
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from policybeats.a2a.assessment import (
    AssessmentConfig,
    AssessmentRequest,
    run_assessment,
)
from policybeats.a2a.engine import run_multi_turn_assessment
from policybeats.a2a.results import report_to_agentbeats
from policybeats.a2a.scenarios import ALL_SCENARIOS

logger = logging.getLogger(__name__)


# === Pydantic Models for A2A Protocol ===


class A2AMessagePart(BaseModel):
    """A2A message part."""
    kind: str  # "text", "tool_call", "tool_result"
    text: str | None = None
    name: str | None = None
    arguments: dict[str, Any] | None = None
    callId: str | None = None
    result: Any | None = None


class A2AMessage(BaseModel):
    """A2A message."""
    role: str  # "user", "assistant"
    parts: list[A2AMessagePart]
    messageId: str


class A2AMessageSendParams(BaseModel):
    """Parameters for message/send."""
    message: A2AMessage


class A2ARequest(BaseModel):
    """A2A JSON-RPC request."""
    jsonrpc: str = "2.0"
    id: str
    method: str
    params: dict[str, Any]


class A2AResponse(BaseModel):
    """A2A JSON-RPC response."""
    jsonrpc: str = "2.0"
    id: str
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


# === Agent Card ===


def get_agent_card() -> dict[str, Any]:
    """
    Return the agent card for discovery.

    Served at /.well-known/agent.json
    """
    return {
        "name": "PolicyBeats",
        "description": "GDPR policy compliance benchmark for AI agents. "
        "Deterministic evaluation of whether agents comply with GDPR operational policies.",
        "version": "0.1.0",
        "url": os.getenv("AGENT_URL", "http://localhost:8000"),
        "capabilities": {
            "assessment": True,
            "streaming": False,
            "tools": False,
        },
        "metadata": {
            "policy_type": "gdpr",
            "category": "Agent Safety",
            "surfaces": ["Access", "Privacy", "Disclosure", "Process", "Safety", "Governance"],
            "num_scenarios": len(ALL_SCENARIOS),
            "deterministic": True,
            "no_llm_judges": True,
        },
    }


# === Request Handling ===


def parse_assessment_request(message: A2AMessage) -> AssessmentRequest | None:
    """Parse an A2A message into an assessment request."""
    text_content = ""
    for part in message.parts:
        if part.kind == "text" and part.text:
            text_content += part.text

    if not text_content:
        return None

    try:
        data = json.loads(text_content)

        purple_agent_url = data.get("purple_agent_url")
        purple_agent_id = data.get("purple_agent_id")

        if not purple_agent_url or not purple_agent_id:
            return None

        config_data = data.get("config", {})
        config = AssessmentConfig(
            num_tasks=config_data.get("num_tasks", 8),
            timeout_per_task=config_data.get("timeout_per_task", 60.0),
            domain=config_data.get("domain", "policy_compliance"),
        )

        return AssessmentRequest(
            purple_agent_url=purple_agent_url,
            purple_agent_id=purple_agent_id,
            config=config,
        )

    except json.JSONDecodeError:
        return None


def results_to_a2a_message(results: dict[str, Any]) -> A2AMessage:
    """Convert assessment results to A2A message format."""
    return A2AMessage(
        role="assistant",
        parts=[
            A2AMessagePart(
                kind="text",
                text=json.dumps(results, indent=2),
            )
        ],
        messageId=uuid.uuid4().hex,
    )


# === FastAPI App ===


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for startup/shutdown."""
    logger.info("PolicyBeats Green Agent starting...")
    logger.info(f"Loaded {len(ALL_SCENARIOS)} GDPR scenarios")
    yield
    logger.info("PolicyBeats Green Agent shutting down...")


app = FastAPI(
    title="PolicyBeats Green Agent",
    description="GDPR policy compliance benchmark for AI agents",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/.well-known/agent.json")
async def agent_card():
    """Return the agent card (A2A discovery endpoint)."""
    return get_agent_card()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "agent": "policybeats-green", "policy_type": "gdpr"}


@app.get("/scenarios")
async def list_scenarios():
    """List available GDPR scenarios."""
    return {
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


@app.post("/a2a/message/send")
async def message_send(request: Request):
    """
    A2A message/send endpoint.

    Receives assessment requests from Purple agents.
    """
    try:
        body = await request.json()
        a2a_request = A2ARequest(**body)

        if a2a_request.method != "message/send":
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": a2a_request.id,
                    "error": {
                        "code": -32601,
                        "message": f"Method not found: {a2a_request.method}",
                    },
                },
                status_code=200,
            )

        params = A2AMessageSendParams(**a2a_request.params)
        assessment_request = parse_assessment_request(params.message)

        if assessment_request is None:
            return JSONResponse(
                content={
                    "jsonrpc": "2.0",
                    "id": a2a_request.id,
                    "error": {
                        "code": -32602,
                        "message": "Invalid assessment request. Expected JSON with "
                        "purple_agent_url and purple_agent_id.",
                    },
                },
                status_code=200,
            )

        logger.info(
            f"Running multi-turn GDPR assessment for {assessment_request.purple_agent_id} "
            f"at {assessment_request.purple_agent_url}"
        )

        import time as _time
        t0 = _time.monotonic()
        report = await run_multi_turn_assessment(
            purple_url=assessment_request.purple_agent_url,
        )
        elapsed = _time.monotonic() - t0

        results_json = report_to_agentbeats(
            report,
            purple_agent_id=assessment_request.purple_agent_id,
            time_used=elapsed,
        )

        response_message = results_to_a2a_message(results_json)

        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": a2a_request.id,
                "result": {
                    "message": response_message.model_dump(),
                },
            },
            status_code=200,
        )

    except Exception as e:
        logger.exception("Error handling message/send")
        return JSONResponse(
            content={
                "jsonrpc": "2.0",
                "id": "unknown",
                "error": {
                    "code": -32603,
                    "message": f"Internal error: {str(e)}",
                },
            },
            status_code=200,
        )


# === Direct Assessment Endpoint (for testing) ===


class DirectAssessmentRequest(BaseModel):
    """Direct assessment request (non-A2A, for testing)."""
    purple_agent_url: str
    purple_agent_id: str
    num_tasks: int = 8
    timeout_per_task: float = 60.0


@app.post("/assess", deprecated=True)
async def direct_assess(request: DirectAssessmentRequest):
    """
    Direct GDPR assessment endpoint (DEPRECATED - use /assess/multi-turn).
    """
    assessment_request = AssessmentRequest(
        purple_agent_url=request.purple_agent_url,
        purple_agent_id=request.purple_agent_id,
        config=AssessmentConfig(
            num_tasks=request.num_tasks,
            timeout_per_task=request.timeout_per_task,
        ),
    )

    result = await run_assessment(assessment_request)

    if not result.success:
        raise HTTPException(status_code=500, detail=result.error)

    return result.results_json


# === Multi-Turn Assessment Endpoint ===


@app.post("/assess/multi-turn")
async def multi_turn_assess(purple_agent_url: str):
    """
    Multi-turn GDPR assessment endpoint.

    Runs full multi-turn scenarios with:
    - Environment state management
    - Per-turn evaluation
    - Multi-dimensional scoring
    """
    report = await run_multi_turn_assessment(purple_url=purple_agent_url)
    return report.to_dict()


# === Entry Point ===


def main():
    """Run the server."""
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    host = os.getenv("HOST", "0.0.0.0")

    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
