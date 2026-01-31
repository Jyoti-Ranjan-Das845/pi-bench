"""
Simulation runner - imperative shell.

This module executes the effects produced by the pure functional core.
It's the only place where actual I/O happens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pi_bench.ports.llm import LLMPort
from pi_bench.ports.tools import ToolRegistryPort
from pi_bench.sim.orchestration import (
    init_simulation,
    integrate_tool_result,
    step,
)
from pi_bench.sim.tools import execute_tool
from pi_bench.sim.types import (
    DBSnapshot,
    DoneEffect,
    LLMCallEffect,
    MessageKind,
    SimMessage,
    SimState,
    SimulationResult,
    TaskConfig,
    TaskSpec,
    TerminationReason,
    ToolExecEffect,
)
from pi_bench.sim.user import (
    build_user_system_prompt,
    build_user_system_prompt_from_taskspec,
)

logger = logging.getLogger(__name__)


def run_simulation(
    task: TaskConfig,
    llm: LLMPort,
    tools: ToolRegistryPort,
    max_iterations: int = 100,
    verbose: bool = False,
) -> SimulationResult:
    """
    Run a complete simulation.

    This is the imperative shell that executes effects from the pure core.

    Args:
        task: Task configuration
        llm: LLM adapter for generating responses
        tools: Tool registry for executing tools
        max_iterations: Safety limit on iterations
        verbose: Print debug info

    Returns:
        SimulationResult with final state and trajectory
    """
    # Initialize simulation
    result = init_simulation(task)
    state = result.state

    if verbose:
        logger.info(f"Starting simulation: {task.task_id}")

    iteration = 0
    while not state.done and iteration < max_iterations:
        iteration += 1

        # Execute effects from last step
        response, new_db = _execute_effects(
            effects=result.effects,
            state=state,
            task=task,
            llm=llm,
            tools=tools,
            verbose=verbose,
        )

        # Update state DB if tool modified it
        if new_db is not None and new_db != state.db:
            state = state.with_db(new_db)

        # Step the simulation
        result = step(state, response)
        state = result.state

        if verbose and response:
            _log_message(response)

    # Handle iteration limit
    if iteration >= max_iterations and not state.done:
        logger.warning(f"Hit max iterations ({max_iterations})")
        state = state.terminated(TerminationReason.MAX_STEPS)

    # Determine success
    success = state.termination_reason == TerminationReason.SUCCESS

    return SimulationResult(
        task_id=task.task_id,
        domain=task.domain,
        trajectory=state.trajectory,
        final_db=state.db,
        step_count=state.step_count,
        termination_reason=state.termination_reason or TerminationReason.ERROR,
        success=success,
    )


def _execute_effects(
    effects: tuple[Any, ...],
    state: SimState,
    task: TaskConfig,
    llm: LLMPort,
    tools: ToolRegistryPort,
    verbose: bool = False,
) -> tuple[SimMessage | None, DBSnapshot | None]:
    """
    Execute effects and return the resulting message and updated DB.

    Returns (response_message, new_db) to feed back into step().
    new_db is only set for tool execution effects.
    """
    for effect in effects:
        if isinstance(effect, DoneEffect):
            if verbose:
                logger.info(f"Simulation done: {effect.reason}")
            return None, None

        elif isinstance(effect, LLMCallEffect):
            return _execute_llm_effect(effect, task, llm, tools, verbose), None

        elif isinstance(effect, ToolExecEffect):
            # Tool effects also return the new DB
            msg, new_db = _execute_tool_effect_with_db(effect, state, tools, verbose)
            return msg, new_db

    return None, None


def _execute_llm_effect(
    effect: LLMCallEffect,
    task: TaskConfig,
    llm: LLMPort,
    tools: ToolRegistryPort,
    verbose: bool = False,
) -> SimMessage:
    """Execute an LLM call effect."""
    if effect.role == "agent":
        # Agent generation
        system_prompt = effect.system_prompt or task.system_prompt
        tool_schemas = tools.get_schemas() if task.available_tools else None

        if verbose:
            logger.debug(f"Generating agent response (tools: {len(tool_schemas or [])})")

        return llm.generate(
            messages=effect.messages,
            role="agent",
            system_prompt=system_prompt,
            tools=tool_schemas,
        )

    else:
        # User simulation
        system_prompt = effect.system_prompt or build_user_system_prompt(
            instruction=task.user_instruction,
            domain=task.domain,
        )

        if verbose:
            logger.debug("Generating user response")

        return llm.generate(
            messages=effect.messages,
            role="user",
            system_prompt=system_prompt,
            tools=None,
        )


def _execute_tool_effect_with_db(
    effect: ToolExecEffect,
    state: SimState,
    tools: ToolRegistryPort,
    verbose: bool = False,
) -> tuple[SimMessage, DBSnapshot]:
    """
    Execute a tool call effect.

    Returns (tool_result_message, new_db).
    """
    tool_fn = tools.get_tool(effect.tool_name)

    if tool_fn is None:
        # Tool not found
        if verbose:
            logger.warning(f"Tool not found: {effect.tool_name}")
        return (
            SimMessage(
                kind=MessageKind.TOOL_RESULT,
                content=f"Error: Tool '{effect.tool_name}' not found",
                call_id=effect.call_id,
                error=True,
            ),
            effect.db,  # DB unchanged
        )

    # Execute the tool
    if verbose:
        logger.debug(f"Executing tool: {effect.tool_name}")

    new_db, result, is_error = execute_tool(tool_fn, effect.db, effect.arguments)

    # Return tool result message and new DB
    return (
        SimMessage(
            kind=MessageKind.TOOL_RESULT,
            content=result,
            call_id=effect.call_id,
            error=is_error,
        ),
        new_db,
    )


def _log_message(msg: SimMessage) -> None:
    """Log a message for debugging."""
    kind = msg.kind.value
    content = (msg.content or "")[:100]
    if msg.tool_calls:
        tool_names = [tc.name for tc in msg.tool_calls]
        logger.info(f"[{kind}] {content} [tools: {tool_names}]")
    else:
        logger.info(f"[{kind}] {content}")


# === Convenience runners ===


def run_with_mock_llm(
    task: TaskConfig,
    tools: ToolRegistryPort,
    agent_responses: list[str],
    user_responses: list[str] | None = None,
) -> SimulationResult:
    """
    Run simulation with mock LLM responses.

    Useful for deterministic testing.
    """
    from pi_bench.ports.llm import MockLLMPort

    # Interleave user and agent responses
    all_responses = []
    user_resps = user_responses or ["I'd like to complete this task. TASK_COMPLETE"]

    for i in range(max(len(agent_responses), len(user_resps))):
        if i < len(user_resps):
            all_responses.append(user_resps[i])
        if i < len(agent_responses):
            all_responses.append(agent_responses[i])

    mock_llm = MockLLMPort(responses=all_responses)
    return run_simulation(task, mock_llm, tools)


def run_single_turn(
    task: TaskConfig,
    llm: LLMPort,
    tools: ToolRegistryPort,
    user_message: str,
) -> tuple[SimMessage | None, DBSnapshot]:
    """
    Run a single turn of interaction.

    Returns (agent_response, final_db).
    """
    # Create initial state with user message
    result = init_simulation(task)
    state = result.state

    # Add user message
    user_msg = SimMessage(kind=MessageKind.USER, content=user_message)
    state = state.with_message(user_msg)

    # Get agent response
    result = step(state, None)

    for effect in result.effects:
        if isinstance(effect, LLMCallEffect) and effect.role == "agent":
            response = llm.generate(
                messages=state.trajectory,
                role="agent",
                system_prompt=task.system_prompt,
                tools=tools.get_schemas(),
            )
            return response, state.db

    return None, state.db


# === CLI Entry Point ===


def main() -> None:
    """CLI entry point for running simulations."""
    import argparse

    parser = argparse.ArgumentParser(description="Run PolicyBeats simulation")
    parser.add_argument("--domain", default="mock", help="Domain to use")
    parser.add_argument("--task", required=True, help="Task ID to run")
    parser.add_argument("--model", default="gpt-4o-mini", help="LLM model")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()

    # Set up logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Import adapters
    from pi_bench.adapters.domains.mock import create_mock_domain
    from pi_bench.adapters.litellm import LiteLLMAdapter
    from pi_bench.ports.tasks import create_mock_task_loader

    # Load task
    task_loader = create_mock_task_loader()
    try:
        task = task_loader.load(args.task)
    except KeyError:
        logger.error(f"Task not found: {args.task}")
        logger.info(f"Available tasks: {task_loader.list_tasks()}")
        return

    # Set up adapters
    llm = LiteLLMAdapter(model=args.model)
    tools = create_mock_domain()

    # Run simulation
    logger.info(f"Running task: {task.task_id}")
    result = run_simulation(task, llm, tools, verbose=args.verbose)

    # Print result
    print("\n" + "=" * 50)
    print(f"Task: {result.task_id}")
    print(f"Domain: {result.domain}")
    print(f"Success: {result.success}")
    print(f"Steps: {result.step_count}")
    print(f"Termination: {result.termination_reason.value}")
    print("=" * 50)

    # Print trajectory
    print("\nTrajectory:")
    for i, msg in enumerate(result.trajectory):
        kind = msg.kind.value
        content = msg.content or ""
        if len(content) > 80:
            content = content[:77] + "..."
        print(f"  {i}: [{kind}] {content}")


if __name__ == "__main__":
    main()
