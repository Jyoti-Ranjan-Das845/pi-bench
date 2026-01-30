"""
GPT-5.2 Purple Agent with Unified 9-Dimensional Policy Framework.

This Purple agent uses OpenAI's GPT-5.2 model with a unified system prompt
that combines all 9 policy pack dimensions into a single comprehensive
instruction set.

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
- Model: GPT-5.2 (OpenAI)
- Framework: unified (9-dimensional π-bench)
- System Prompt: UNIFIED_SYSTEM_PROMPT (all 9 policy packs combined)
- Scenarios: 54 multi-turn test cases
- Scoring: 9 dimension-specific compliance rates

Usage:
    from policybeats.purple.gpt52_unified_agent import create_gpt52_unified_agent

    app = create_gpt52_unified_agent(port=8001)

    # Or run directly:
    # python -m policybeats.purple.gpt52_unified_agent --port 8001

Requirements:
    export OPENAI_API_KEY="sk-..."
"""

from __future__ import annotations

from policybeats.purple.llm_agent import create_llm_server


def create_gpt52_unified_agent(port: int = 8001):
    """
    Create GPT-5.2 Purple Agent with unified 9-dimensional framework.

    This agent uses OpenAI's GPT-5.2 model with the UNIFIED_SYSTEM_PROMPT
    that contains all 9 policy pack instructions. It's designed to be tested
    across 54 scenarios spanning 9 dimensions of policy compliance.

    Args:
        port: Port number for the server (default: 8001)

    Returns:
        FastAPI app configured for GPT-5.2 with unified framework

    Raises:
        ImportError: If required dependencies are not installed
        ValueError: If OPENAI_API_KEY is not set

    Example:
        >>> app = create_gpt52_unified_agent(port=8001)
        >>> # Start with uvicorn:
        >>> import uvicorn
        >>> uvicorn.run(app, host="0.0.0.0", port=8001)
    """
    import os

    # Check for API key
    if not os.getenv("OPENAI_API_KEY"):
        raise ValueError(
            "OPENAI_API_KEY environment variable is required. "
            "Set it with: export OPENAI_API_KEY='sk-...'"
        )

    return create_llm_server(
        model="gpt-5.2",
        framework="unified",
        port=port,
    )


if __name__ == "__main__":
    import argparse
    import sys
    import uvicorn

    parser = argparse.ArgumentParser(
        description="GPT-5.2 Purple Agent - Unified 9-Dimensional Framework"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Server port (default: 8001)",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Server host (default: 0.0.0.0)",
    )
    args = parser.parse_args()

    # Check API key before starting
    import os
    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY environment variable not set", file=sys.stderr)
        print("\nSet it with:")
        print("  export OPENAI_API_KEY='sk-...'")
        sys.exit(1)

    print("=" * 80)
    print("GPT-5.2 Purple Agent - Unified 9-Dimensional Framework")
    print("=" * 80)
    print(f"Model:     gpt-5.2 (OpenAI)")
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

    app = create_gpt52_unified_agent(port=args.port)

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )
