"""COMMUNICATE evaluator — check required info strings in agent messages.

Matches tau2-bench behavior: all-or-nothing scoring. All required
information strings must appear in agent messages for the evaluator
to return 1.0. Any missing string → 0.0.
"""

import logging

from pi_bench.types import extract_message_content

logger = logging.getLogger(__name__)


def evaluate_communicate(communicate_info: list[str], trajectory: list[dict]) -> float:
    """Check that required information strings appear in agent messages.

    Case-insensitive substring matching. Commas stripped before comparison.
    Returns 1.0 if ALL required strings found, 0.0 if any missing.
    """
    results = evaluate_communicate_rich(communicate_info, trajectory)
    return 1.0 if all(r["passed"] for r in results) else 0.0


def evaluate_communicate_rich(communicate_info: list[str], trajectory: list[dict]) -> list[dict]:
    """Return one explainable result per required communication string."""
    if not communicate_info:
        return []

    agent_text = ""
    for msg in trajectory:
        if msg.get("role") == "assistant" and msg.get("content"):
            agent_text += " " + extract_message_content(msg)

    agent_text_clean = agent_text.replace(",", "").lower()
    results = []

    for idx, info in enumerate(communicate_info):
        info_clean = info.replace(",", "").lower()
        passed = info_clean in agent_text_clean
        if not passed:
            logger.info("COMMUNICATE: missing required string: '%s'", info[:80])
        results.append({
            "outcome_id": f"COMMUNICATE_{idx}",
            "type": "communicate",
            "passed": passed,
            "detail": (
                f"required text found: {info[:80]!r}"
                if passed
                else f"missing required text: {info[:80]!r}"
            ),
        })

    logger.debug("COMMUNICATE: %d/%d required strings found", sum(r["passed"] for r in results), len(results))
    return results
