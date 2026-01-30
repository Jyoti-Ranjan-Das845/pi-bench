#!/usr/bin/env python3
"""
Test dual-agent simulation: Purple Agent (assistant) vs Green Agent (user simulator).

Purple Agent: The AI assistant being evaluated
Green Agent: Simulates a user trying to accomplish a task

Usage:
    # With real LLMs (requires OPENAI_API_KEY)
    python scripts/test_dual_agent.py --model gpt-4o-mini

    # With scenario-based mock (no API key needed)
    python scripts/test_dual_agent.py --scenario-mock

    # With simple mock responses
    python scripts/test_dual_agent.py --mock
"""

import argparse
import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env.local if present
load_dotenv(Path(__file__).parent.parent / ".env.local")

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from policybeats.sim import (
    TaskConfig,
    UserInstruction,
    SimulationResult,
    TerminationReason,
)
from policybeats.adapters.runner import run_simulation
from policybeats.adapters.domains.mock import create_mock_domain
from policybeats.ports.llm import MockLLMPort

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def create_test_task() -> TaskConfig:
    """Create a test task for dual-agent simulation."""
    return TaskConfig(
        task_id="user_management_task",
        domain="mock",
        system_prompt="""You are a helpful assistant for a task management system.
You have access to tools to manage users and tasks.

Available actions:
- list_users: List all users
- create_user: Create a new user (requires: name, optional: email)
- get_user: Get user by ID
- list_tasks: List all tasks
- create_task: Create a new task (requires: title, optional: description, assignee)
- complete_task: Mark a task as complete

Be helpful and use the tools to accomplish the user's requests.
Always confirm actions taken and provide clear responses.
When you've completed the user's request, let them know.""",
        user_instruction=UserInstruction(
            goal="Create a new user named 'Alice' with email 'alice@example.com', then create a task titled 'Review Documentation' assigned to Alice.",
            context="You are testing a task management system. You want to set up a new user and give them their first task.",
            constraints=(
                "Confirm each action was successful before proceeding",
                "When both the user and task are created, say TASK_COMPLETE",
            ),
        ),
        initial_db={
            "users": {},
            "tasks": {},
        },
        available_tools=(
            "list_users",
            "create_user",
            "get_user",
            "list_tasks",
            "create_task",
            "complete_task",
        ),
        max_steps=30,
        max_errors=3,
    )


def print_result(result: SimulationResult) -> None:
    """Print simulation result in a readable format."""
    print("\n" + "=" * 70)
    print("SIMULATION RESULT")
    print("=" * 70)
    print(f"Task ID:     {result.task_id}")
    print(f"Domain:      {result.domain}")
    print(f"Success:     {'YES' if result.success else 'NO'}")
    print(f"Steps:       {result.step_count}")
    print(f"Termination: {result.termination_reason.value}")
    print(f"DB Version:  {result.final_db.version}")

    # Print final DB state
    print("\n" + "-" * 70)
    print("FINAL DATABASE STATE")
    print("-" * 70)
    for key, value in result.final_db.data.items():
        if isinstance(value, dict) and len(value) > 0:
            print(f"\n{key}:")
            for item_id, item in value.items():
                print(f"  {item_id}: {item}")
        else:
            print(f"{key}: {value}")

    # Print trajectory
    print("\n" + "-" * 70)
    print("CONVERSATION TRAJECTORY")
    print("-" * 70)
    for i, msg in enumerate(result.trajectory):
        kind = msg.kind.value

        # Color coding for terminal
        if "user" in kind.lower():
            color = "\033[92m"  # Green
            role = "GREEN/USER"
        elif "agent" in kind.lower():
            color = "\033[95m"  # Purple
            role = "PURPLE/AGENT"
        elif "tool_result" in kind.lower():
            color = "\033[93m"  # Yellow
            role = "TOOL RESULT"
        elif "tool_call" in kind.lower():
            color = "\033[96m"  # Cyan
            role = "TOOL CALL"
        else:
            color = ""
            role = kind.upper()

        reset = "\033[0m"

        print(f"\n{color}[{i+1}] {role}{reset}")

        if msg.tool_calls:
            for tc in msg.tool_calls:
                print(f"    CALL: {tc.name}({tc.arguments})")

        content = msg.content or ""
        if content:
            # Wrap long content
            lines = content.split('\n')
            for line in lines:
                if len(line) > 80:
                    # Word wrap
                    words = line.split()
                    current_line = "    "
                    for word in words:
                        if len(current_line) + len(word) + 1 > 80:
                            print(current_line)
                            current_line = "    " + word
                        else:
                            current_line += " " + word if current_line.strip() else "    " + word
                    if current_line.strip():
                        print(current_line)
                else:
                    print(f"    {line}")

    print("\n" + "=" * 70)


def run_with_mock() -> SimulationResult:
    """Run simulation with simple mock LLM responses."""
    logger.info("Running with SIMPLE MOCK LLM (no API calls)")

    task = create_test_task()
    tools = create_mock_domain()

    # Predefined conversation
    mock_responses = [
        "Hi! I'd like to create a new user named Alice with email alice@example.com.",
        "I'll help you create that user. Let me do that now.",
        "Great! Now please create a task called 'Review Documentation' and assign it to Alice.",
        "I'll create that task for you right away.",
        "Perfect, that's exactly what I needed. TASK_COMPLETE",
    ]

    mock_llm = MockLLMPort(responses=mock_responses)

    return run_simulation(
        task=task,
        llm=mock_llm,
        tools=tools,
        max_iterations=20,
        verbose=True,
    )


def run_with_scenario_mock() -> SimulationResult:
    """Run simulation with scenario-based mock that generates tool calls."""
    from policybeats.adapters.scenario_mock import create_scenario_mock

    logger.info("Running with SCENARIO MOCK LLM (understands task metadata)")

    task = create_test_task()
    tools = create_mock_domain()

    scenario_llm = create_scenario_mock(task)

    return run_simulation(
        task=task,
        llm=scenario_llm,
        tools=tools,
        max_iterations=30,
        verbose=True,
    )


def run_with_llm(model: str, user_model: str | None = None) -> SimulationResult:
    """Run simulation with real LLM."""
    from policybeats.adapters.litellm import LiteLLMAdapter

    user_model = user_model or model
    logger.info(f"Running with LLM - Purple: {model}, Green: {user_model}")

    task = create_test_task()
    tools = create_mock_domain()

    llm = LiteLLMAdapter(
        model=model,
        temperature=0.7,
        max_tokens=1024,
        user_model=user_model,
        user_temperature=0.7,
    )

    return run_simulation(
        task=task,
        llm=llm,
        tools=tools,
        max_iterations=30,
        verbose=True,
    )


def main():
    parser = argparse.ArgumentParser(description="Test dual-agent simulation")
    parser.add_argument(
        "--model",
        default="gpt-4o-mini",
        help="LLM model for Purple agent (default: gpt-4o-mini)",
    )
    parser.add_argument(
        "--user-model",
        default=None,
        help="LLM model for Green agent (default: same as --model)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use simple mock responses instead of real LLM",
    )
    parser.add_argument(
        "--scenario-mock",
        action="store_true",
        help="Use scenario-based mock that generates tool calls",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Check for API keys
    has_openai = bool(os.environ.get("OPENAI_API_KEY"))

    if args.mock:
        result = run_with_mock()
    elif args.scenario_mock:
        result = run_with_scenario_mock()
    elif has_openai:
        result = run_with_llm(args.model, args.user_model)
    else:
        logger.warning("No OPENAI_API_KEY found in environment")
        logger.info("Falling back to scenario mock. Use --mock or --scenario-mock to suppress.")
        result = run_with_scenario_mock()

    print_result(result)

    # Summary
    print("\nSUMMARY:")
    if result.success:
        print("  The dual-agent simulation completed successfully!")
        print(f"  - Users created: {len(result.final_db.data.get('users', {}))}")
        print(f"  - Tasks created: {len(result.final_db.data.get('tasks', {}))}")
    else:
        print(f"  Simulation ended with: {result.termination_reason.value}")
        if result.termination_reason == TerminationReason.MAX_STEPS:
            print("  - The conversation exceeded maximum steps")
        elif result.termination_reason == TerminationReason.MAX_ERRORS:
            print("  - Too many tool execution errors")

    return 0 if result.success else 1


if __name__ == "__main__":
    sys.exit(main())
