"""Official results format schema for PI-Bench leaderboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResultsSchema:
    """Official PI-Bench leaderboard results schema."""

    benchmark: str  # Must be "pi-bench"
    version: str    # Benchmark version (e.g., "1.0.0")
    agent: dict[str, Any]  # Agent metadata
    evaluation: dict[str, Any]  # Evaluation metadata
    scores: dict[str, Any]  # Score breakdown
    violations: list[dict[str, Any]]  # Violation records
    scenario_hashes: dict[str, str]  # Scenario verification hashes


def validate_results_format(results: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate results JSON against official schema.

    Args:
        results: Results dictionary loaded from JSON

    Returns:
        (valid, errors) - True if valid, list of error messages
    """
    errors: list[str] = []

    # Required top-level fields
    required_fields = [
        "benchmark",
        "version",
        "agent",
        "evaluation",
        "scores",
        "scenario_hashes",
    ]

    for field in required_fields:
        if field not in results:
            errors.append(f"Missing required field: {field}")

    # Benchmark must be "pi-bench"
    if results.get("benchmark") != "pi-bench":
        errors.append(f"Invalid benchmark: {results.get('benchmark')}, must be 'pi-bench'")

    # Scores must have all 9 dimensions
    scores = results.get("scores", {})
    by_dimension = scores.get("by_dimension", {})

    required_dimensions = [
        "compliance",
        "understanding",
        "robustness",
        "process",
        "restraint",
        "conflict_resolution",
        "detection",
        "explainability",
        "adaptation",
    ]

    for dim in required_dimensions:
        if dim not in by_dimension:
            errors.append(f"Missing dimension score: {dim}")

    # Agent metadata
    agent = results.get("agent", {})
    if "name" not in agent:
        errors.append("Missing agent.name")
    if "url" not in agent:
        errors.append("Missing agent.url")

    return len(errors) == 0, errors
