"""A2AUserAgent -- UserProtocol adapter for a remote A2A user simulator."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

import httpx

from pi_bench.a2a.purple_adapter import _agent_card_base_url, _normalize_message_url
from pi_bench.types import is_stop_signal

logger = logging.getLogger(__name__)


class A2AUserProtocolError(ValueError):
    """Raised when an A2A user simulator returns an invalid response."""


class A2AUserAgent:
    """User simulator that routes UserProtocol calls to an A2A HTTP server."""

    model_name: str

    def __init__(self, user_url: str, timeout: float = 120.0) -> None:
        self.user_url = _normalize_message_url(user_url)
        self._agent_card_base_url = _agent_card_base_url(user_url)
        self.model_name = f"a2a-user:{user_url}"
        self._client = httpx.Client(timeout=timeout)
        self._seed: int | None = None
        self._task_id: str | None = None

    def init_state(
        self,
        scenario: dict,
        message_history: list[dict] | None = None,
    ) -> dict:
        self._task_id = str(uuid.uuid4())
        payload: dict[str, Any] = {
            "init": True,
            "scenario": scenario,
            "message_history": message_history or [],
        }
        if self._seed is not None:
            payload["seed"] = self._seed

        data = self._send(payload)
        state = data.get("state")
        if not isinstance(state, dict):
            raise A2AUserProtocolError("A2A user init response missing state")
        return state

    def generate(self, message: dict, state: dict) -> tuple[dict, dict]:
        payload: dict[str, Any] = {
            "message": message,
            "state": state,
        }
        if self._seed is not None:
            payload["seed"] = self._seed

        data = self._send(payload)
        user_message = data.get("message")
        new_state = data.get("state")
        if not isinstance(user_message, dict):
            raise A2AUserProtocolError("A2A user generate response missing message")
        if not isinstance(new_state, dict):
            raise A2AUserProtocolError("A2A user generate response missing state")
        return user_message, new_state

    def is_stop(self, message: dict) -> bool:
        return is_stop_signal(message)

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def stop(self, message: dict | None, state: dict | None) -> None:
        try:
            self._send({"stop": True, "message": message, "state": state})
        except Exception as exc:
            logger.warning("A2A user stop failed: %s", exc)
        self._client.close()

    def _send(self, data: dict[str, Any]) -> dict:
        request = _build_user_request(data, task_id=self._task_id)
        try:
            response = self._client.post(
                self.user_url,
                json=request,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise A2AUserProtocolError(f"A2A user HTTP request failed: {exc}") from exc

        try:
            return _parse_user_response(response.json())
        except ValueError as exc:
            raise A2AUserProtocolError("A2A user returned invalid JSON") from exc


def _build_user_request(data: dict[str, Any], task_id: str | None = None) -> dict:
    a2a_message = {
        "role": "user",
        "parts": [{"kind": "data", "data": data}],
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


def _parse_user_response(response: dict) -> dict:
    if not isinstance(response, dict):
        raise A2AUserProtocolError("A2A user response must be a JSON object")

    if "error" in response:
        error = response.get("error") or {}
        message = error.get("message", error) if isinstance(error, dict) else error
        raise A2AUserProtocolError(f"A2A user returned JSON-RPC error: {message}")

    result = response.get("result")
    if not isinstance(result, dict):
        raise A2AUserProtocolError("A2A user response missing result")

    if "artifacts" in result:
        for artifact in result["artifacts"]:
            for part in artifact.get("parts", []):
                return _part_data(part)

    status = result.get("status", {})
    if isinstance(status, dict):
        message = status.get("message", {})
        if isinstance(message, dict):
            for part in message.get("parts", []):
                return _part_data(part)

    if "message" in result:
        message = result.get("message", {})
        if isinstance(message, dict):
            for part in message.get("parts", []):
                return _part_data(part)

    raise A2AUserProtocolError("A2A user response missing data part")


def _part_data(part: dict) -> dict:
    if not isinstance(part, dict) or part.get("kind") != "data":
        raise A2AUserProtocolError("A2A user response part must be kind='data'")
    data = part.get("data")
    if not isinstance(data, dict):
        raise A2AUserProtocolError("A2A user response data must be an object")
    # Round-trip through JSON to catch unserializable server payloads early.
    json.dumps(data)
    return data
