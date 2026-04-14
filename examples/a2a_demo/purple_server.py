#!/usr/bin/env python3
"""FastAPI purple agent server — wraps litellm for A2A-based pi-bench evaluation.

Receives pi-bench messages already in OpenAI format via A2A JSON-RPC,
calls litellm.completion() directly, returns results in A2A format.

Supports the pi-bench bootstrap extension (urn:pi-bench:policy-bootstrap:v1):
benchmark context and tools are sent once and cached per context_id.

Usage:
    python examples/a2a_demo/purple_server.py --model gpt-4o-mini --port 8766
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import uuid
from typing import Any

import litellm
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pi_bench.env import load_env

logger = logging.getLogger(__name__)

POLICY_BOOTSTRAP_EXTENSION = "urn:pi-bench:policy-bootstrap:v1"
_DEFAULT_SYSTEM_PROMPT = (
    "You are a policy-compliance agent. Use the benchmark-provided context "
    "and structured tools to complete the task."
)

app = FastAPI(title="pi-bench purple agent")

# Module-level state
_model: str = "gpt-4o-mini"
_seed: int | None = None
_card_url: str = ""
_sessions: dict[str, dict] = {}  # context_id → {benchmark_context, tools}


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    """Return agent card declaring bootstrap extension support."""
    return JSONResponse({
        "name": "pi-bench-purple-agent",
        "description": "LiteLLM-based purple agent for pi-bench evaluation",
        "url": _card_url,
        "extensions": [POLICY_BOOTSTRAP_EXTENSION],
        "capabilities": {
            "message": True,
        },
    })


@app.get("/.well-known/agent-card.json")
async def agent_card_alias() -> JSONResponse:
    """Compatibility alias used by AgentBeats docker-compose health checks."""
    return await agent_card()


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"status": "ok", "model": _model})


@app.post("/")
async def message_send(request: Request) -> JSONResponse:
    """Handle A2A JSON-RPC message/send requests."""
    body = await request.json()

    method = body.get("method", "")
    if method != "message/send":
        return _jsonrpc_error(body.get("id"), -32601, f"Unknown method: {method}")

    params = body.get("params", {})
    message = params.get("message", {})
    parts = message.get("parts", [])

    if not parts:
        return _jsonrpc_error(body.get("id"), -32602, "No message parts")

    data = parts[0].get("data", {})

    # Bootstrap request
    if data.get("bootstrap"):
        return _handle_bootstrap(body.get("id"), data)

    # Regular turn
    return await _handle_turn(body.get("id"), data)


def _handle_bootstrap(request_id: str | None, data: dict) -> JSONResponse:
    """Cache benchmark context and tools for a new session, return context_id."""
    context_id = str(uuid.uuid4())

    _sessions[context_id] = {
        "benchmark_context": data.get("benchmark_context", []),
        "tools": data.get("tools", []),
    }

    logger.info(
        "Bootstrap: cached context_id=%s (%d context nodes, %d tools)",
        context_id,
        len(data.get("benchmark_context", [])),
        len(data.get("tools", [])),
    )

    return _jsonrpc_success(request_id, {
        "kind": "data",
        "data": {"bootstrapped": True, "context_id": context_id},
    })


async def _handle_turn(request_id: str | None, data: dict) -> JSONResponse:
    """Process a regular conversation turn."""
    context_id = data.get("context_id")
    messages = data.get("messages", [])
    benchmark_context = data.get("benchmark_context", [])
    tools = data.get("tools", [])

    # If bootstrapped, use cached benchmark context and tools
    if context_id and context_id in _sessions:
        session = _sessions[context_id]
        benchmark_context = session["benchmark_context"]
        tools = session["tools"]

    if _should_include_benchmark_context(messages):
        messages = _benchmark_context_to_system_messages(benchmark_context) + messages

    # Build litellm kwargs
    kwargs: dict[str, Any] = {
        "model": _model,
        "messages": messages,
        "drop_params": True,
        "num_retries": 2,
    }
    if tools:
        kwargs["tools"] = tools
    if _seed is not None:
        kwargs["seed"] = _seed

    try:
        response = await asyncio.to_thread(litellm.completion, **kwargs)
    except Exception as exc:
        logger.exception("litellm.completion failed")
        return _jsonrpc_error(request_id, -32000, str(exc))

    choice = response.choices[0]
    result_part = _format_response(choice.message)

    return _jsonrpc_success(request_id, result_part)


def _format_response(choice_message: Any) -> dict:
    """Format an OpenAI response as an A2A data part.

    Must match the format expected by _parse_a2a_response in purple_adapter.py.
    """
    tool_calls_raw = getattr(choice_message, "tool_calls", None)
    content = getattr(choice_message, "content", None)

    if tool_calls_raw:
        tc_list = []
        for tc in tool_calls_raw:
            tc_list.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            })
        data: dict[str, Any] = {"tool_calls": tc_list}
        if content:
            data["content"] = content
        return {"kind": "data", "data": data}

    if content:
        return {"kind": "data", "data": {"content": content}}

    return {"kind": "data", "data": {"content": "###STOP###"}}


def _should_include_benchmark_context(messages: list[dict]) -> bool:
    """Mirror LiteLLMAgent: include benchmark context on the first model turn.

    A2A bootstrap sends benchmark context/tools once to the purple server. The
    local LiteLLMAgent includes the formatted benchmark context only on the
    first API call, then omits it on later turns to avoid repeated policy-token
    overhead. Use the same rule here: once the conversation already contains an
    assistant message, do not prepend the context again.
    """
    return not any(msg.get("role") == "assistant" for msg in messages)


def _benchmark_context_to_system_messages(benchmark_context: list[dict]) -> list[dict]:
    """Example choice: place benchmark context into this agent's system prompt."""
    sections = [_DEFAULT_SYSTEM_PROMPT]
    for node in benchmark_context or []:
        kind = str(node.get("kind", "context")).strip() or "context"
        content = str(node.get("content", "")).strip()
        if not content:
            continue
        sections.append(f"\n<{kind}>\n{content}\n</{kind}>")
    return [{"role": "system", "content": "\n".join(sections)}]


def _jsonrpc_success(request_id: str | None, part: dict) -> JSONResponse:
    """Wrap a result part in a JSON-RPC success response."""
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "result": {
            "status": {
                "message": {
                    "role": "agent",
                    "parts": [part],
                },
            },
        },
    })


def _jsonrpc_error(request_id: str | None, code: int, message: str) -> JSONResponse:
    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id or str(uuid.uuid4()),
        "error": {"code": code, "message": message},
    })


def main() -> None:
    global _model, _seed, _card_url

    load_env()
    parser = argparse.ArgumentParser(description="pi-bench purple agent server")
    parser.add_argument("--model", type=str, default="gpt-4o-mini", help="LiteLLM model name")
    parser.add_argument("--port", type=int, default=8766, help="Server port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Server host")
    parser.add_argument("--card-url", type=str, default="", help="Public A2A agent-card URL")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for LLM calls")
    args = parser.parse_args()

    _model = args.model
    _seed = args.seed
    _card_url = args.card_url

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info("Starting purple agent server: model=%s host=%s port=%d", _model, args.host, args.port)

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
