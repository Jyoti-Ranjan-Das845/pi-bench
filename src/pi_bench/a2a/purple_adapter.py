"""A2APurpleAgent — implements AgentProtocol by routing to a purple agent via HTTP.

This adapter lets pi-bench's orchestrator evaluate a remote purple agent
over the A2A protocol. The orchestrator sees it as any other AgentProtocol
implementation (like LiteLLMAgent), but generate() sends requests to a
purple agent's HTTP endpoint instead of calling an LLM directly.

Supports two modes:

1. **Bootstrapped** (preferred): benchmark context + tools are sent once via
   ``init_state()`` when the purple agent advertises
   ``urn:pi-bench:policy-bootstrap:v1``. Subsequent turns send only
   conversation history + ``context_id``.

2. **Stateless** (fallback): full conversation history + tool schemas are
   sent on every turn, as before.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx

from pi_bench.a2a.bootstrap import (
    BenchmarkBootstrap,
    build_bootstrap_request,
    check_bootstrap_support,
    parse_bootstrap_response,
)
from pi_bench.types import build_tool_call, make_assistant_msg

logger = logging.getLogger(__name__)


class A2AProtocolError(ValueError):
    """Raised when a purple agent returns an invalid A2A response."""


class A2APurpleAgent:
    """Agent that routes to a remote purple agent via A2A JSON-RPC."""

    model_name: str

    def __init__(self, purple_url: str, timeout: float = 120.0) -> None:
        self.purple_url = _normalize_message_url(purple_url)
        self._agent_card_base_url = _agent_card_base_url(purple_url)
        self.model_name = f"a2a:{purple_url}"
        self._client = httpx.Client(timeout=timeout)
        self._seed: int | None = None
        self._task_id: str | None = None
        self._bootstrapped: bool = False
        self._context_id: str | None = None

    # ── AgentProtocol interface ───────────────────────────

    def init_state(
        self,
        benchmark_context: list[dict],
        tools: list[dict],
        message_history: list[dict] | None = None,
    ) -> dict:
        """Store benchmark context and tool schemas in state.

        If the purple agent supports the bootstrap extension, sends benchmark
        context + tools once and stores the returned ``context_id``. Subsequent
        ``generate()`` calls will omit benchmark context and tools.
        """
        openai_tools = [_to_openai_tool(t) for t in tools] if tools else []
        openai_messages: list[dict] = []
        if message_history:
            for msg in message_history:
                openai_messages.extend(_to_openai_messages(msg))

        self._task_id = str(uuid.uuid4())

        # Attempt bootstrap handshake
        self._bootstrapped = False
        self._context_id = None
        try:
            if check_bootstrap_support(self._agent_card_base_url, self._client):
                bundle = BenchmarkBootstrap(
                    benchmark_context=benchmark_context,
                    tools=openai_tools,
                    run_id=self._task_id,
                )
                bootstrap_req = build_bootstrap_request(bundle, task_id=self._task_id)
                resp = self._client.post(
                    self.purple_url,
                    json=bootstrap_req,
                    headers={"Content-Type": "application/json"},
                )
                resp.raise_for_status()
                context_id = parse_bootstrap_response(resp.json())
                if context_id:
                    self._bootstrapped = True
                    self._context_id = context_id
                    logger.info("Bootstrap succeeded — context_id=%s", context_id)
                else:
                    logger.warning("Bootstrap response missing context_id, falling back")
        except Exception as exc:
            logger.warning("Bootstrap handshake failed, falling back to stateless: %s", exc)

        return {
            "messages": openai_messages,
            "benchmark_context": benchmark_context,
            "tools": openai_tools,
        }

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]:
        """Send conversation to the purple agent, parse response.

        When bootstrapped, benchmark context and tools are omitted from the
        payload; the purple agent uses them from its session cache.
        """
        messages = list(state["messages"])
        messages.extend(_to_openai_messages(message))

        if self._bootstrapped and self._context_id:
            a2a_request = _build_a2a_request_bootstrapped(
                messages=messages,
                context_id=self._context_id,
                task_id=self._task_id,
                seed=self._seed,
            )
        else:
            a2a_request = _build_a2a_request(
                messages=messages,
                benchmark_context=state["benchmark_context"],
                tools=state["tools"],
                task_id=self._task_id,
                seed=self._seed,
            )

        try:
            response = self._client.post(
                self.purple_url,
                json=a2a_request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise A2AProtocolError(f"purple agent HTTP request failed: {exc}") from exc

        try:
            a2a_response = response.json()
        except ValueError as exc:
            raise A2AProtocolError("purple agent returned invalid JSON") from exc

        result = _parse_a2a_response(a2a_response)

        assistant_msg = _result_to_openai_msg(result)
        messages.append(assistant_msg)
        new_state = {**state, "messages": messages}

        return result, new_state

    def is_stop(self, message: dict) -> bool:
        return False

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def stop(self, message: dict | None, state: dict | None) -> None:
        self._client.close()


# ── Conversion: pi_bench → OpenAI format ─────────────────


def _normalize_message_url(purple_url: str) -> str:
    """Normalize a purple URL while preserving explicit message endpoints."""
    if not isinstance(purple_url, str) or not purple_url.strip():
        raise ValueError("purple_url must be a non-empty URL")

    cleaned = purple_url.strip().rstrip("/")
    parsed = urlparse(cleaned)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"purple_url must be absolute, got {purple_url!r}")
    return cleaned


def _agent_card_base_url(purple_url: str) -> str:
    """Return scheme+host for agent-card discovery, even when URL is an endpoint."""
    parsed = urlparse(_normalize_message_url(purple_url))
    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))


def _to_openai_msg(msg: dict) -> dict:
    """Convert a single pi_bench message to OpenAI format."""
    role = msg.get("role", "user")

    if role == "system":
        return {"role": "system", "content": msg.get("content", "")}

    if role == "tool":
        return {
            "role": "tool",
            "tool_call_id": msg["id"],
            "content": msg.get("content", ""),
        }

    if role in ("assistant", "user"):
        out: dict[str, Any] = {"role": role}
        if "content" in msg and msg["content"] is not None:
            out["content"] = msg["content"]
        if "tool_calls" in msg and msg["tool_calls"]:
            out["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": (
                            json.dumps(tc["arguments"])
                            if isinstance(tc["arguments"], dict)
                            else tc["arguments"]
                        ),
                    },
                }
                for tc in msg["tool_calls"]
            ]
        return out

    return {"role": role, "content": msg.get("content", "")}


def _to_openai_messages(msg: dict) -> list[dict]:
    """Convert a pi_bench message to a list of OpenAI messages."""
    if msg.get("role") == "multi_tool":
        result = []
        for sub in msg.get("tool_messages", []):
            result.append(
                {
                    "role": "tool",
                    "tool_call_id": sub["id"],
                    "content": sub.get("content", ""),
                }
            )
        return result
    return [_to_openai_msg(msg)]


def _to_openai_tool(schema: dict) -> dict:
    """Wrap a pi_bench tool schema in OpenAI function-calling format."""
    func: dict[str, Any] = {
        "name": schema["name"],
        "parameters": schema.get("parameters", {}),
    }
    if "description" in schema:
        func["description"] = schema["description"]
    return {"type": "function", "function": func}


# ── A2A request/response ─────────────────────────────────


def _build_a2a_request(
    messages: list[dict],
    benchmark_context: list[dict],
    tools: list[dict],
    task_id: str | None = None,
    seed: int | None = None,
) -> dict:
    """Build an A2A JSON-RPC message/send request."""
    context: dict[str, Any] = {
        "messages": messages,
        "benchmark_context": benchmark_context,
        "tools": tools,
    }
    if seed is not None:
        context["seed"] = seed

    a2a_message = {
        "role": "user",
        "parts": [{"kind": "data", "data": context}],
    }

    params: dict[str, Any] = {"message": a2a_message}
    if task_id:
        params["configuration"] = {"taskId": task_id}

    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }


def _build_a2a_request_bootstrapped(
    messages: list[dict],
    context_id: str,
    task_id: str | None = None,
    seed: int | None = None,
) -> dict:
    """Build a lightweight A2A request for a bootstrapped session.

    Includes the ``context_id`` instead of resending benchmark context and
    tool schemas.
    """
    context: dict[str, Any] = {
        "messages": messages,
        "context_id": context_id,
    }
    if seed is not None:
        context["seed"] = seed

    a2a_message: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "data", "data": context}],
    }

    params: dict[str, Any] = {"message": a2a_message}
    if task_id:
        params["configuration"] = {"taskId": task_id}

    return {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": params,
    }


def _parse_a2a_response(response: dict) -> dict:
    """Parse an A2A JSON-RPC response into a pi-bench assistant message."""
    if not isinstance(response, dict):
        raise A2AProtocolError("A2A response must be a JSON object")

    if "error" in response:
        error = response.get("error") or {}
        message = error.get("message", error) if isinstance(error, dict) else error
        raise A2AProtocolError(f"purple agent returned JSON-RPC error: {message}")

    if "result" not in response:
        raise A2AProtocolError("A2A response missing result")

    result = response.get("result", {})

    # Task-based response (artifacts)
    if "artifacts" in result:
        for artifact in result["artifacts"]:
            for part in artifact.get("parts", []):
                return _part_to_pi_msg(part)

    # Status-based response
    status = result.get("status", {})
    message = status.get("message", {})
    if message:
        parts = message.get("parts", [])
        if parts:
            return _part_to_pi_msg(parts[0])

    # Direct message
    if "message" in result:
        parts = result["message"].get("parts", [])
        if parts:
            return _part_to_pi_msg(parts[0])

    raise A2AProtocolError("A2A response contained no message parts")


def _part_to_pi_msg(part: dict) -> dict:
    """Convert an A2A message part to a pi-bench assistant message."""
    kind = part.get("kind", "text")

    if kind == "data":
        data = part.get("data", {})
        if "tool_calls" in data:
            pi_tool_calls = []
            for tc in data["tool_calls"]:
                func = tc.get("function", tc)
                args = func.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError as exc:
                        name = func.get("name", tc.get("name", "unknown"))
                        raise A2AProtocolError(
                            f"invalid JSON arguments for tool call {name!r}"
                        ) from exc
                try:
                    pi_tool_calls.append(
                        build_tool_call(
                            name=func.get("name", tc.get("name", "unknown")),
                            arguments=args,
                            call_id=tc.get("id", str(uuid.uuid4())),
                        )
                    )
                except ValueError as exc:
                    raise A2AProtocolError(f"invalid tool call: {exc}") from exc
            return make_assistant_msg(
                content=data.get("content"),
                tool_calls=pi_tool_calls,
            )

        if "content" in data:
            return make_assistant_msg(content=data["content"])

        return make_assistant_msg(content=json.dumps(data))

    text = part.get("text", "")
    if not text:
        return make_assistant_msg()
    return make_assistant_msg(content=text)


def _result_to_openai_msg(result: dict) -> dict:
    """Convert a pi-bench result message to OpenAI format for state tracking."""
    out: dict[str, Any] = {"role": "assistant"}
    if "content" in result and result["content"] is not None:
        out["content"] = result["content"]
    if "tool_calls" in result and result["tool_calls"]:
        out["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": (
                        json.dumps(tc["arguments"])
                        if isinstance(tc["arguments"], dict)
                        else tc["arguments"]
                    ),
                },
            }
            for tc in result["tool_calls"]
        ]
    return out
