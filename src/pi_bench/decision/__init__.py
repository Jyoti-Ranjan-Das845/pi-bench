"""Decision Signal Resolution — extract canonical decision from a trace.

Two channels: record_decision tool calls (preferred), fenced JSON blocks
(fallback). Exactly one canonical decision per valid run. Structural
parsing only — no semantic inference, no LLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from pi_bench.trace import TraceRecorder

VALID_DECISIONS = frozenset({"ALLOW", "ALLOW-CONDITIONAL", "DENY", "ESCALATE"})

_FENCED_BLOCK_RE = re.compile(r"```(?:json)?\s*\n(.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class InvalidRun:
    """A run where no valid canonical decision could be extracted."""

    reason: str  # INVALID_DECISION, MULTIPLE_DECISIONS_JSON, MISSING_DECISION
    detail: str = ""


@dataclass(frozen=True)
class CanonicalDecision:
    """A successfully resolved canonical decision."""

    decision: str  # ALLOW, ALLOW-CONDITIONAL, DENY, ESCALATE
    channel: str  # "tool" or "json"


def resolve(trace: TraceRecorder) -> CanonicalDecision | InvalidRun:
    """Resolve the canonical decision from a trace.

    Resolution procedure (deterministic):
    1. Extract all record_decision tool calls by assistant.
    2. If any valid calls exist → last valid call wins.
    3. If count == 0, fall back to JSON blocks in messages.
    4. Multiple JSON-channel decisions → InvalidRun(MULTIPLE_DECISIONS_JSON).
    """
    # Channel A: Decision Tool — take the last valid call.
    # Models legitimately update their decision as conversations evolve
    # (e.g., first DENY, then user escalates → model records ESCALATE too).
    tool_decisions = [
        e for e in trace.entries
        if e.tool_name == "record_decision"
    ]

    if tool_decisions:
        for entry in reversed(tool_decisions):
            decision = entry.arguments.get("decision", "")
            if (
                isinstance(decision, str)
                and decision in VALID_DECISIONS
                and not entry.result_error
                and not entry.blocked
            ):
                return CanonicalDecision(decision=decision, channel="tool")
        return InvalidRun(
            reason="INVALID_DECISION",
            detail="no valid record_decision tool call was found",
        )

    # Channel B: JSON Decision Block (fallback)
    json_decisions = _extract_json_decisions(trace)

    if len(json_decisions) == 1:
        return CanonicalDecision(decision=json_decisions[0], channel="json")

    if len(json_decisions) > 1:
        return InvalidRun(reason="MULTIPLE_DECISIONS_JSON")

    return InvalidRun(reason="MISSING_DECISION")


def _extract_json_decisions(trace: TraceRecorder) -> list[str]:
    """Extract valid decision values from fenced JSON blocks in messages."""
    decisions: list[str] = []

    for msg in trace.messages:
        if msg.role != "assistant":
            continue
        for match in _FENCED_BLOCK_RE.finditer(msg.content):
            block = match.group(1).strip()
            try:
                obj = json.loads(block)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(obj, dict):
                continue
            decision = obj.get("decision")
            if isinstance(decision, str) and decision in VALID_DECISIONS:
                decisions.append(decision)

    return decisions


def check_compliance_missing_decision(
    result: CanonicalDecision | InvalidRun,
) -> tuple[bool, str | None]:
    """Check if a missing decision makes the run non-compliant.

    Returns (is_compliant, evidence_reason).
    """
    if isinstance(result, InvalidRun) and result.reason == "MISSING_DECISION":
        return False, "missing_decision"
    return True, None
