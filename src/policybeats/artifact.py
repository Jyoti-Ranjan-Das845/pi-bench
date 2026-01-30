"""
Artifact creation and serialization.

Pure functions for creating the final evaluation artifact.
Deterministic JSON serialization with canonical formatting.

Invariants:
- Same inputs produce byte-identical outputs
- All dataclasses serialize to JSON without loss
- No timestamps, UUIDs, or non-deterministic data allowed
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any

from policybeats.score import aggregate
from policybeats.types import (
    Artifact,
    EpisodeResult,
    PolicyPack,
    RunMetadata,
)

# Package version - single source of truth
__version__ = "0.1.0"

# Spec version this implementation conforms to
SPEC_VERSION = "1.0"


def _serialize_value(obj: Any) -> Any:
    """Convert a value to JSON-serializable form."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _serialize_value(v) for k, v in asdict(obj).items()}
    if isinstance(obj, Enum):
        return obj.value
    if isinstance(obj, tuple):
        return [_serialize_value(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _serialize_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize_value(item) for item in obj]
    return obj


def canonical_json_bytes(obj: Any) -> bytes:
    """
    Serialize object to canonical JSON bytes.

    Canonical format:
    - Keys sorted alphabetically
    - No whitespace (compact)
    - UTF-8 encoding
    - Consistent handling of dataclasses and enums

    Args:
        obj: Any JSON-serializable object, dataclass, or enum

    Returns:
        Deterministic byte representation
    """
    serializable = _serialize_value(obj)
    return json.dumps(
        serializable,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def make_artifact(
    results: tuple[EpisodeResult, ...],
    policy_pack: PolicyPack,
    config: dict[str, Any] | None = None,
) -> Artifact:
    """
    Create the final evaluation artifact.

    Combines episode results with aggregate metrics and metadata.

    Args:
        results: Tuple of episode results (will be sorted by episode_id)
        policy_pack: The policy pack used for evaluation
        config: Optional configuration to include in metadata

    Returns:
        Complete Artifact ready for serialization
    """
    # Sort results by episode_id for determinism
    sorted_results = tuple(sorted(results, key=lambda r: r.episode_id))

    # Compute aggregate metrics
    summary = aggregate(sorted_results)

    # Build metadata
    run_metadata = RunMetadata(
        evaluator_version=__version__,
        config=config or {},
    )

    return Artifact(
        spec_version=SPEC_VERSION,
        policy_pack_id=policy_pack.policy_pack_id,
        policy_version=policy_pack.version,
        run_metadata=run_metadata,
        summary=summary,
        episodes=sorted_results,
    )


def artifact_to_json(artifact: Artifact) -> str:
    """
    Serialize artifact to canonical JSON string.

    Convenience wrapper around canonical_json_bytes for string output.
    """
    return canonical_json_bytes(artifact).decode("utf-8")
