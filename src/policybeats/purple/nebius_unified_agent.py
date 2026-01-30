"""
Nebius GPT-OSS-Safeguard-120B Purple Agent with Unified 9-Dimensional Policy Framework.

This Purple agent uses Nebius's GPT-OSS-Safeguard-120B model (via OpenAI-compatible API)
with a unified system prompt that combines all 9 policy pack dimensions into a single
comprehensive instruction set.

The agent is tested across 54 multi-turn scenarios covering:
1. Compliance - Retail returns policy (6 scenarios)
2. Understanding - Insurance claims interpretation (6 scenarios)
3. Robustness - Adversarial resistance (6 scenarios)
4. Process - Procedural compliance (6 scenarios)
5. Restraint - Over-refusal prevention (6 scenarios)
6. Conflict Resolution - Ambiguity handling (6 scenarios)
7. Detection - Policy violation detection (6 scenarios)
8. Explainability - Decision justification (6 scenarios)
9. Adaptation - Context-triggered rules (6 scenarios)

Architecture:
- Model: nebius/gpt-oss-120b (GPT-OSS-Safeguard-120B via Nebius API)
- API: Nebius Studio API (https://api.studio.nebius.com/v1)
- Framework: unified (9-dimensional π-bench)
- System Prompt: UNIFIED_SYSTEM_PROMPT (all 9 policy packs combined)
- Scenarios: 54 multi-turn test cases
- Scoring: 9 dimension-specific compliance rates

Requirements:
    export NEBIUS_API_KEY="your-nebius-api-key"

Usage:
    from policybeats.purple.nebius_unified_agent import create_nebius_unified_agent

    app = create_nebius_unified_agent(port=8002)

    # Or run directly:
    # python -m policybeats.purple.nebius_unified_agent --port 8002
"""

from __future__ import annotations

import os

from policybeats.purple.llm_agent import create_llm_server


def create_nebius_unified_agent(port: int = 8002):
    """
    Create Nebius GPT-OSS-Safeguard-120B Purple Agent with unified 9-dimensional framework.

    This agent uses Nebius's GPT-OSS-Safeguard-120B model via their OpenAI-compatible API
    with the UNIFIED_SYSTEM_PROMPT that contains all 9 policy pack instructions.
    It's designed to be tested across 54 scenarios spanning 9 dimensions of policy compliance.

    The Nebius API uses the OpenAI Python SDK with a custom base URL:
        base_url="https://api.studio.nebius.com/v1/"
        model="nebius/gpt-oss-120b"

    Args:
        port: Port number for the server (default: 8002)

    Returns:
        FastAPI app configured for Nebius GPT-OSS-Safeguard-120B with unified framework

    Raises:
        ValueError: If NEBIUS_API_KEY environment variable is not set
        ImportError: If required dependencies are not installed

    Example:
        >>> app = create_nebius_unified_agent(port=8002)
        >>> # Start with uvicorn:
        >>> import uvicorn
        >>> uvicorn.run(app, host="0.0.0.0", port=8002)
    """
    # Check for API key
    if not os.getenv("NEBIUS_API_KEY"):
        raise ValueError(
            "NEBIUS_API_KEY environment variable is required for Nebius models. "
            "Set it with: export NEBIUS_API_KEY='your-api-key'"
        )

    return create_llm_server(
        model="nebius/gpt-oss-120b",
        framework="unified",
        port=port,
    )


if __name__ == "__main__":
    import argparse
    import sys
    import uvicorn

    parser = argparse.ArgumentParser(
        description="Nebius GPT-OSS-Safeguard-120B Purple Agent - Unified 9-Dimensional Framework"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8002,
        help="Server port (default: 8002)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    # Check API key before starting
    if not os.getenv("NEBIUS_API_KEY"):
        print("ERROR: NEBIUS_API_KEY environment variable not set", file=sys.stderr)
        print("\nSet it with:")
        print("  export NEBIUS_API_KEY='your-api-key'")
        print("\nGet your API key from: https://studio.nebius.com")
        sys.exit(1)

    print("=" * 80)
    print("Nebius GPT-OSS-Safeguard-120B Purple Agent - Unified 9-Dimensional Framework")
    print("=" * 80)
    print(f"Model:     nebius/gpt-oss-120b (GPT-OSS-Safeguard-120B)")
    print(f"Framework: unified (9 dimensions, 54 scenarios)")
    print(f"URL:       http://{args.host}:{args.port}")
    print("=" * 80)
    print()
    print("Policy Dimensions:")
    print("  1. Compliance       - Retail returns policy")
    print("  2. Understanding    - Insurance claims interpretation")
    print("  3. Robustness       - Adversarial resistance")
    print("  4. Process          - Procedural compliance")
    print("  5. Restraint        - Over-refusal prevention")
    print("  6. Conflict Res.    - Ambiguity handling")
    print("  7. Detection        - Policy violation detection")
    print("  8. Explainability   - Decision justification")
    print("  9. Adaptation       - Context-triggered rules")
    print("=" * 80)
    print()
    print("NOTE: Requires NEBIUS_API_KEY environment variable")
    print()

    app = create_nebius_unified_agent(port=args.port)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
