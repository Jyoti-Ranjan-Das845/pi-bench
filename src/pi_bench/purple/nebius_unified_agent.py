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

Architecture (Standard A2A Framework):
- Model: nebius/gpt-oss-120b (GPT-OSS-Safeguard-120B via Nebius API)
- API: Nebius Studio API (https://api.studio.nebius.com/v1)
- Framework: unified (9-dimensional π-bench)
- System Prompt: UNIFIED_SYSTEM_PROMPT (all 9 policy packs combined)
- Scenarios: 54 multi-turn test cases
- Scoring: 9 dimension-specific compliance rates
- A2A Server: Uses AgentExecutor + A2AStarletteApplication (standard pattern)

Requirements:
    export NEBIUS_API_KEY="your-nebius-api-key"

Usage:
    from pi_bench.purple.nebius_unified_agent import create_nebius_unified_agent

    app = create_nebius_unified_agent(agent_url="http://localhost:8002")

    # Or run directly:
    # python -m pi_bench.purple.nebius_unified_agent --port 8002
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from a2a.server.agent_execution import AgentExecutor
from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill
from a2a.utils import new_agent_text_message
from starlette.applications import Starlette

from pi_bench.purple.llm_agent import UNIFIED_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


class NebiusExecutor(AgentExecutor):
    """
    Executor for Nebius GPT-OSS-120B with unified 9-dimensional policy framework.

    Follows the standard AgentBeats A2A pattern (tau2 baseline).
    """

    def __init__(self, model: str = "openai/gpt-oss-120b"):
        self.model = model
        self.ctx_id_to_messages: dict[str, list[dict[str, Any]]] = {}
        self.system_prompt = UNIFIED_SYSTEM_PROMPT

    async def execute(self, context: Any, event_queue: Any) -> None:
        """
        Execute LLM call and queue response via A2A event system.

        Args:
            context: A2A RequestContext with message and context_id
            event_queue: A2A EventQueue for sending responses
        """
        from openai import AsyncOpenAI

        # Extract context ID and user input from message
        ctx_id = context.context_id

        # Extract user input from message parts
        user_input = ""
        if context.message and context.message.parts:
            for part in context.message.parts:
                if hasattr(part.root, "text") and part.root.text:
                    user_input += part.root.text

        # Initialize conversation history if new context
        if ctx_id not in self.ctx_id_to_messages:
            self.ctx_id_to_messages[ctx_id] = [
                {"role": "system", "content": self.system_prompt}
            ]

        # Append user message
        self.ctx_id_to_messages[ctx_id].append({"role": "user", "content": user_input})

        # Call Nebius API via OpenAI SDK
        api_key = os.getenv("NEBIUS_API_KEY")
        if not api_key:
            raise ValueError("NEBIUS_API_KEY environment variable required")

        nebius_client = AsyncOpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1",
            api_key=api_key,
        )

        try:
            response = await nebius_client.chat.completions.create(
                model=self.model,
                messages=self.ctx_id_to_messages[ctx_id],
            )

            # Extract assistant response
            assistant_message = response.choices[0].message.content or ""

            # Add to conversation history
            self.ctx_id_to_messages[ctx_id].append(
                {"role": "assistant", "content": assistant_message}
            )

            # Queue response through A2A event system
            response_message = new_agent_text_message(
                assistant_message,
                context_id=ctx_id
            )
            await event_queue.enqueue_event(response_message)

        except Exception as e:
            logger.exception(f"LLM call failed for context {ctx_id}")
            error_msg = f"I apologize, I'm experiencing technical difficulties: {str(e)}"
            error_message = new_agent_text_message(error_msg, context_id=ctx_id)
            await event_queue.enqueue_event(error_message)

    async def cancel(self, task_id: str) -> None:
        """Cancel not supported."""
        raise NotImplementedError("Task cancellation not supported for Nebius agent")


def get_agent_card(url: str | None = None) -> AgentCard:
    """
    Return the agent card for discovery.

    Served at /.well-known/agent.json
    """
    return AgentCard(
        name="PI-Bench Nebius Purple Agent",
        description="Nebius GPT-OSS-Safeguard-120B purple agent for policy compliance testing. "
        "Uses unified 9-dimensional framework (54 scenarios) covering Compliance, Understanding, "
        "Robustness, Process, Restraint, Conflict Resolution, Detection, Explainability, and Adaptation.",
        version="0.1.0",
        url=url or os.getenv("AGENT_URL", "http://localhost:8002"),
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(
            assessment=False,
            streaming=False,
            tools=False,
        ),
        skills=[
            AgentSkill(
                id="policy_compliance_testing",
                name="Policy Compliance Testing Subject",
                description="Purple agent (test subject) for GDPR policy compliance benchmark. "
                "Evaluated across 9 dimensions and 54 multi-turn scenarios.",
                tags=["gdpr", "policy", "compliance", "purple", "test-subject"],
                examples=[
                    '{"message": "I need help with a product return"}',
                    '{"message": "Can you access my personal data?"}',
                ],
            )
        ],
    )


def create_nebius_unified_agent(agent_url: str | None = None) -> Starlette:
    """
    Create Nebius GPT-OSS-Safeguard-120B Purple Agent with standard A2A framework.

    This agent uses Nebius's GPT-OSS-Safeguard-120B model via their OpenAI-compatible API
    with the UNIFIED_SYSTEM_PROMPT that contains all 9 policy pack instructions.
    It's designed to be tested across 54 scenarios spanning 9 dimensions of policy compliance.

    The Nebius API uses the OpenAI Python SDK with a custom base URL:
        base_url="https://api.tokenfactory.nebius.com/v1"
        model="openai/gpt-oss-120b"

    Args:
        agent_url: Public URL for agent card discovery (optional)

    Returns:
        Starlette app configured with A2AStarletteApplication

    Raises:
        ValueError: If NEBIUS_API_KEY environment variable is not set
        ImportError: If required dependencies are not installed

    Example:
        >>> app = create_nebius_unified_agent(agent_url="http://localhost:8002")
        >>> import uvicorn
        >>> uvicorn.run(app, host="0.0.0.0", port=8002)
    """
    # Check for API key
    if not os.getenv("NEBIUS_API_KEY"):
        raise ValueError(
            "NEBIUS_API_KEY environment variable is required for Nebius models. "
            "Set it with: export NEBIUS_API_KEY='your-api-key'"
        )

    # Create agent card
    agent_card = get_agent_card(url=agent_url)

    # Create executor and request handler
    executor = NebiusExecutor(model="openai/gpt-oss-120b")
    task_store = InMemoryTaskStore()
    request_handler = DefaultRequestHandler(
        agent_executor=executor,
        task_store=task_store,
    )

    # Create A2A server
    a2a_app = A2AStarletteApplication(
        agent_card=agent_card,
        http_handler=request_handler,
    )

    # Build and return the application
    return a2a_app.build()


def main():
    """Main entry point for the Nebius purple agent."""
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
    parser.add_argument(
        "--card-url",
        type=str,
        help="Public URL for agent card discovery (optional, for AgentBeats compatibility)",
    )
    args = parser.parse_args()

    # Check API key before starting
    if not os.getenv("NEBIUS_API_KEY"):
        print("ERROR: NEBIUS_API_KEY environment variable not set", file=sys.stderr)
        print("\nSet it with:")
        print("  export NEBIUS_API_KEY='your-api-key'")
        print("\nGet your API key from: https://studio.nebius.com")
        sys.exit(1)

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("=" * 80)
    print("Nebius GPT-OSS-Safeguard-120B Purple Agent - Unified 9-Dimensional Framework")
    print("=" * 80)
    print(f"Model:     nebius/gpt-oss-120b (GPT-OSS-Safeguard-120B)")
    print(f"Framework: unified (9 dimensions, 54 scenarios)")
    print(f"URL:       http://{args.host}:{args.port}")
    print(f"A2A Server: Standard AgentExecutor + A2AStarletteApplication")
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

    # Store card URL in environment if provided
    if args.card_url:
        os.environ["AGENT_URL"] = args.card_url

    # Create app
    app = create_nebius_unified_agent(agent_url=args.card_url)

    # Run server
    logger.info(f"Starting Nebius purple agent on {args.host}:{args.port}")
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
