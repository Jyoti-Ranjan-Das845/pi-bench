"""
Mock Purple Agent Server for local E2E testing.

Rule-based responses, no LLM calls. Deterministic behavior
for testing the Green agent assessment pipeline.

Run: python -m policybeats.purple.mock_server
"""

import json
import os
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="MockPurple Agent", version="0.1.0")

AGENT_CARD = {
    "name": "MockPurple",
    "description": "Mock purple agent for local E2E testing",
    "version": "0.1.0",
    "url": os.getenv("PURPLE_URL", "http://localhost:8001"),
    "capabilities": {"streaming": False, "tools": True},
}


def _make_response_parts(scenario: dict) -> list[dict]:
    """Generate rule-based response parts from a scenario message."""
    instruction = scenario.get("instruction", "").lower()
    tools = scenario.get("tools", [])
    tool_names = {t["name"] if isinstance(t, dict) else t for t in tools}
    parts = []

    # Always include AI disclosure prefix
    prefix = "As an AI assistant, "

    if "delete" in instruction and "delete_user_data" in tool_names:
        # Tool call: delete user data
        parts.append({
            "kind": "tool_call",
            "name": "delete_user_data",
            "arguments": {"user_id": scenario.get("environment", {}).get("user_id", "unknown")},
            "callId": uuid.uuid4().hex[:12],
        })
        parts.append({
            "kind": "text",
            "text": json.dumps({
                "response": f"{prefix}I have initiated deletion of your personal data.",
                "env_updates": {"data_deleted": ["personal_data"]},
            }),
        })

    elif ("close" in instruction or "account" in instruction) and "escalate_to_human" in tool_names:
        # Tool call: escalate to human
        parts.append({
            "kind": "tool_call",
            "name": "escalate_to_human",
            "arguments": {"reason": "Account closure request"},
            "callId": uuid.uuid4().hex[:12],
        })
        parts.append({
            "kind": "text",
            "text": json.dumps({
                "response": f"{prefix}I am escalating your account closure request to a human agent.",
                "env_updates": {"session_escalated": True},
            }),
        })

    else:
        # Default: polite GDPR compliance text
        parts.append({
            "kind": "text",
            "text": json.dumps({
                "response": (
                    f"{prefix}I understand your request. Under GDPR, you have the right "
                    "to access, rectify, and erase your personal data. "
                    "How can I help you with your data rights today?"
                ),
                "env_updates": {},
            }),
        })

    return parts


@app.get("/.well-known/agent.json")
async def agent_card():
    return AGENT_CARD


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/a2a/message/send")
async def message_send(request: Request):
    body = await request.json()
    req_id = body.get("id", "unknown")

    # Extract scenario message from the text part
    try:
        params = body.get("params", {})
        message = params.get("message", {})
        parts = message.get("parts", [])
        text = next((p["text"] for p in parts if p.get("kind") == "text"), "{}")
        scenario = json.loads(text)
    except Exception:
        scenario = {}

    response_parts = _make_response_parts(scenario)

    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "message": {
                "role": "assistant",
                "parts": response_parts,
                "messageId": uuid.uuid4().hex,
            },
        },
    })


def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)


if __name__ == "__main__":
    main()
