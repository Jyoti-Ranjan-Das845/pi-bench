#!/usr/bin/env python3
"""FastAPI A2A user server -- serves pi-bench's local user simulators."""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from pi_bench.env import load_env
from pi_bench.users.scripted_user import ScriptedUser
from pi_bench.users.user import LiteLLMUser

logger = logging.getLogger(__name__)

app = FastAPI(title="pi-bench user simulator")

_kind: str = "litellm"
_model: str = "gpt-4.1-mini"
_max_turns: int = 8
_seed: int | None = None


@app.get("/.well-known/agent.json")
async def agent_card() -> JSONResponse:
    return JSONResponse({
        "name": "pi-bench-user-simulator",
        "description": "A2A wrapper around pi-bench user simulators",
        "url": "",
        "capabilities": {"message": True},
    })


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "kind": _kind,
        "model": _model if _kind == "litellm" else "scripted",
    })


@app.post("/")
async def message_send(request: Request) -> JSONResponse:
    body = await request.json()
    request_id = body.get("id")

    if body.get("method") != "message/send":
        return _jsonrpc_error(request_id, -32601, f"Unknown method: {body.get('method')}")

    try:
        data = _extract_data(body)
    except ValueError as exc:
        return _jsonrpc_error(request_id, -32602, str(exc))

    try:
        result = await _handle_user_request(data)
    except Exception as exc:
        logger.exception("A2A user request failed")
        return _jsonrpc_error(request_id, -32000, str(exc))

    return _jsonrpc_success(request_id, {"kind": "data", "data": result})


async def _handle_user_request(data: dict[str, Any]) -> dict[str, Any]:
    user = _build_user()
    seed = data.get("seed", _seed)
    if seed is not None:
        user.set_seed(int(seed))

    if data.get("init"):
        state = user.init_state(
            data.get("scenario", {}),
            message_history=data.get("message_history") or None,
        )
        return {"state": state}

    if data.get("stop"):
        user.stop(data.get("message"), data.get("state"))
        return {"stopped": True}

    message = data.get("message")
    state = data.get("state")
    if not isinstance(message, dict):
        raise ValueError("user generate request requires message")
    if not isinstance(state, dict):
        raise ValueError("user generate request requires state")

    generated, new_state = await asyncio.to_thread(user.generate, message, state)
    return {"message": generated, "state": new_state}


def _build_user() -> LiteLLMUser | ScriptedUser:
    if _kind == "scripted":
        return ScriptedUser()
    return LiteLLMUser(
        model_name=_model,
        max_turns=_max_turns,
        drop_params=True,
        num_retries=2,
    )


def _extract_data(body: dict[str, Any]) -> dict[str, Any]:
    params = body.get("params", {})
    message = params.get("message", {})
    parts = message.get("parts", [])
    if not parts:
        raise ValueError("No message parts")
    data = parts[0].get("data")
    if not isinstance(data, dict):
        raise ValueError("A2A user message data must be an object")
    return data


def _jsonrpc_success(request_id: str | None, part: dict) -> JSONResponse:
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
    global _kind, _model, _max_turns, _seed

    load_env()
    parser = argparse.ArgumentParser(description="pi-bench A2A user simulator server")
    parser.add_argument("--kind", choices=["litellm", "scripted"], default="litellm")
    parser.add_argument("--model", type=str, default="gpt-4.1-mini")
    parser.add_argument("--max-turns", type=int, default=8)
    parser.add_argument("--port", type=int, default=8768)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    _kind = args.kind
    _model = args.model
    _max_turns = args.max_turns
    _seed = args.seed

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger.info(
        "Starting user simulator server: kind=%s model=%s host=%s port=%d",
        _kind,
        _model,
        args.host,
        args.port,
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
