"""Verification utilities for leaderboard submissions."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from pi_bench.packs import CATEGORIES, load_scenarios


def compute_official_scenario_hashes() -> dict[str, str]:
    """Compute hashes of all official scenarios.

    Returns:
        Dictionary mapping scenario_id -> hash
    """
    hashes: dict[str, str] = {}

    for category in CATEGORIES:
        scenarios = load_scenarios(category)
        for scenario in scenarios:
            scenario_dict = {
                "scenario_id": scenario.scenario_id,
                "turns": [
                    {
                        "turn_number": t.turn_number,
                        "instruction": t.instruction,
                        "rules_to_check": list(t.rules_to_check),
                    }
                    for t in scenario.turns
                ],
            }
            scenario_json = json.dumps(scenario_dict, sort_keys=True)
            scenario_hash = hashlib.sha256(scenario_json.encode()).hexdigest()[:16]
            hashes[scenario.scenario_id] = scenario_hash

    return hashes


def verify_results(results: dict[str, Any]) -> tuple[bool, list[str]]:
    """Verify leaderboard submission results.

    Checks:
    1. Scenario hashes match official scenarios (no tampering)
    2. All 9 dimensions evaluated
    3. Result format valid

    Args:
        results: Results dictionary loaded from JSON

    Returns:
        (valid, errors) - True if valid, list of error messages
    """
    from pi_bench.leaderboard.format import validate_results_format

    errors: list[str] = []

    # Validate format
    format_valid, format_errors = validate_results_format(results)
    errors.extend(format_errors)

    # Verify scenario hashes
    official_hashes = compute_official_scenario_hashes()
    submitted_hashes = results.get("scenario_hashes", {})

    for scenario_id, submitted_hash in submitted_hashes.items():
        if scenario_id in official_hashes:
            official_hash = official_hashes[scenario_id]
            if submitted_hash != official_hash:
                errors.append(
                    f"Scenario hash mismatch for {scenario_id}: "
                    f"expected {official_hash}, got {submitted_hash}"
                )

    # Check that all official scenarios were tested
    official_scenario_ids = set(official_hashes.keys())
    submitted_scenario_ids = set(submitted_hashes.keys())

    missing_scenarios = official_scenario_ids - submitted_scenario_ids
    if missing_scenarios:
        errors.append(f"Missing official scenarios: {sorted(missing_scenarios)[:5]}...")

    return len(errors) == 0, errors
