"""
Trace validation, normalization, and hashing.

All functions are pure. Validation is total (never throws).

Invariants:
- validate_trace returns errors, never raises
- trace_hash uses sha256 over canonical JSON bytes
- canonical_trace_json_bytes produces deterministic output
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pi_bench.types import (
    EventKind,
    Trace,
    TraceEvent,
    TraceValidation,
    ValidationError,
)

# Valid event kinds as strings for validation
_VALID_KINDS = frozenset(k.value for k in EventKind)


def normalize_trace(raw_events: list[dict[str, Any]]) -> Trace:
    """
    Convert raw event dicts to typed Trace.

    Drops/normalizes nondeterministic fields (timestamps, random UUIDs).
    Enforces stable ordering by re-indexing events.

    Args:
        raw_events: List of raw event dictionaries

    Returns:
        Tuple of TraceEvent objects
    """
    events: list[TraceEvent] = []

    for i, raw in enumerate(raw_events):
        # Extract and normalize fields
        kind_str = raw.get("kind", "")
        try:
            kind = EventKind(kind_str)
        except ValueError:
            # Keep invalid kind for validation to catch
            kind = EventKind.TERMINATION  # placeholder, validation will fail

        actor = str(raw.get("actor", "unknown"))
        payload = dict(raw.get("payload", {}))

        # Remove nondeterministic fields from payload
        payload.pop("timestamp", None)
        payload.pop("created_at", None)
        payload.pop("updated_at", None)

        # Extract call_id for tool events
        call_id = raw.get("call_id")
        if call_id is not None:
            call_id = str(call_id)

        events.append(
            TraceEvent(
                i=i,  # Re-index to ensure contiguity
                kind=kind,
                actor=actor,
                payload=payload,
                call_id=call_id,
            )
        )

    return tuple(events)


def validate_trace(trace: Trace) -> TraceValidation:
    """
    Validate a trace for correctness.

    Checks:
    1. Event indices are contiguous starting at 0
    2. Event kinds are valid
    3. Tool results reference earlier tool calls by call_id
    4. Events are JSON-serializable
    5. No forbidden nondeterministic fields

    Args:
        trace: The trace to validate

    Returns:
        TraceValidation with valid=True/False and list of errors
    """
    errors: list[ValidationError] = []

    # Track tool calls for linking validation
    tool_call_ids: set[str] = set()

    for i, event in enumerate(trace):
        # Check 1: Index contiguity
        if event.i != i:
            errors.append(
                ValidationError(
                    code="non_contiguous_index",
                    message=f"Expected index {i}, got {event.i}",
                    event_i=i,
                )
            )

        # Check 2: Valid kind
        if event.kind.value not in _VALID_KINDS:
            errors.append(
                ValidationError(
                    code="invalid_event_kind",
                    message=f"Invalid event kind: {event.kind}",
                    event_i=i,
                )
            )

        # Track tool calls
        if event.kind == EventKind.TOOL_CALL:
            if event.call_id is None:
                errors.append(
                    ValidationError(
                        code="missing_call_id",
                        message="tool_call event missing call_id",
                        event_i=i,
                    )
                )
            else:
                tool_call_ids.add(event.call_id)

        # Check 3: Tool results reference earlier tool calls
        if event.kind == EventKind.TOOL_RESULT:
            if event.call_id is None:
                errors.append(
                    ValidationError(
                        code="missing_call_id",
                        message="tool_result event missing call_id",
                        event_i=i,
                    )
                )
            elif event.call_id not in tool_call_ids:
                errors.append(
                    ValidationError(
                        code="orphan_tool_result",
                        message=f"tool_result references unknown call_id: {event.call_id}",
                        event_i=i,
                    )
                )

        # Check 4: JSON-serializable payload
        try:
            json.dumps(event.payload, sort_keys=True)
        except (TypeError, ValueError) as e:
            errors.append(
                ValidationError(
                    code="non_serializable_payload",
                    message=f"Payload not JSON-serializable: {e}",
                    event_i=i,
                )
            )

        # Check 5: Forbidden nondeterministic fields
        for forbidden in ("timestamp", "created_at", "updated_at", "random_id"):
            if forbidden in event.payload:
                errors.append(
                    ValidationError(
                        code="forbidden_nondeterministic_field",
                        message=f"Payload contains forbidden field: {forbidden}",
                        event_i=i,
                    )
                )

    return TraceValidation(
        valid=len(errors) == 0,
        errors=tuple(errors),
    )


def _event_to_dict(event: TraceEvent) -> dict[str, Any]:
    """Convert TraceEvent to dict for JSON serialization."""
    d: dict[str, Any] = {
        "i": event.i,
        "kind": event.kind.value,
        "actor": event.actor,
        "payload": event.payload,
    }
    if event.call_id is not None:
        d["call_id"] = event.call_id
    return d


def canonical_trace_json_bytes(trace: Trace) -> bytes:
    """
    Serialize trace to canonical JSON bytes.

    Canonical means:
    - Keys sorted
    - No whitespace
    - UTF-8 encoding
    - Stable ordering

    Args:
        trace: The trace to serialize

    Returns:
        Canonical JSON bytes
    """
    events_list = [_event_to_dict(e) for e in trace]
    json_str = json.dumps(events_list, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return json_str.encode("utf-8")


def trace_hash(trace: Trace) -> str:
    """
    Compute deterministic hash of trace.

    Uses sha256 over canonical JSON bytes.

    Args:
        trace: The trace to hash

    Returns:
        Hex-encoded hash string (first 16 chars for brevity)
    """
    canonical_bytes = canonical_trace_json_bytes(trace)
    full_hash = hashlib.sha256(canonical_bytes).hexdigest()
    return full_hash[:16]
