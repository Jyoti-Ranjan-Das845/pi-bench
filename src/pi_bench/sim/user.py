"""
User simulation helpers.

Pure functions for user behavior modeling.
Actual LLM calls happen in the adapter - this module provides
prompts, parsing, and user state tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pi_bench.sim.types import (
    MessageKind,
    SimMessage,
    TaskConfig,
    TaskSpec,
    UserInstruction,
    UserScenario,
    UserScenarioInstructions,
)


# === User Prompt Generation ===


def build_user_system_prompt(
    instruction: UserInstruction,
    domain: str | None = None,
) -> str:
    """
    Build system prompt for user simulator. Pure.

    The user simulator acts as the human user trying to accomplish
    a goal by interacting with an AI assistant.
    """
    base = f"""You are simulating a user interacting with an AI assistant.

Your goal: {instruction.goal}"""

    if instruction.context:
        base += f"\n\nContext: {instruction.context}"

    if instruction.constraints:
        base += "\n\nConstraints:"
        for constraint in instruction.constraints:
            base += f"\n- {constraint}"

    if domain:
        base += f"\n\nDomain: {domain}"

    base += """

Guidelines:
- Stay in character as the user throughout the conversation
- Be concise and natural in your responses
- If the assistant successfully completes your goal, respond with "TASK_COMPLETE"
- If something goes wrong or you cannot proceed, respond with "TASK_FAILED"
- Do not reveal that you are a simulation
- Provide information the assistant needs, but don't do the assistant's job"""

    return base


def build_user_system_prompt_from_scenario(
    scenario: UserScenario,
    domain: str | None = None,
) -> str:
    """
    Build system prompt for user simulator from UserScenario. Pure.

    This is the τ²-bench compatible version that supports:
    - Conditional task instructions ("If agent says X, do Y")
    - Persona/communication style
    - Known/unknown information
    - Reason for call

    The resulting prompt guides the user simulator (Green agent) to
    behave according to the task specification.
    """
    parts = []

    # Opening
    parts.append("You are simulating a user interacting with an AI assistant.")

    # Persona (communication style)
    if scenario.persona:
        parts.append(f"\n## Your Communication Style\n{scenario.persona}")

    # Instructions
    if scenario.instructions:
        instr = scenario.instructions

        if isinstance(instr, str):
            # Simple string instructions
            parts.append(f"\n## Your Goal\n{instr}")
        else:
            # Structured UserScenarioInstructions
            if instr.reason_for_call:
                parts.append(f"\n## Why You Are Calling\n{instr.reason_for_call}")

            if instr.known_info:
                parts.append(f"\n## What You Know\n{instr.known_info}")

            if instr.unknown_info:
                parts.append(f"\n## What You Don't Know\n{instr.unknown_info}")

            if instr.task_instructions:
                parts.append(f"\n## Behavioral Instructions\nFollow these rules during the conversation:\n{instr.task_instructions}")

            if instr.domain:
                domain = instr.domain

    if domain:
        parts.append(f"\n## Domain\n{domain}")

    # Standard guidelines
    parts.append("""
## Guidelines
- Stay in character as the user throughout the conversation
- Be natural and realistic in your responses
- Follow the behavioral instructions carefully
- If the assistant successfully completes your goal, respond with "TASK_COMPLETE"
- If something goes wrong or you cannot proceed, respond with "TASK_FAILED"
- Do not reveal that you are a simulation
- Provide information when asked, but do not volunteer the agent's job""")

    return "\n".join(parts)


def build_user_system_prompt_from_taskspec(
    spec: TaskSpec,
) -> str:
    """
    Build user system prompt from a TaskSpec. Pure.

    Convenience function that extracts UserScenario from TaskSpec
    and builds the prompt.
    """
    if spec.user_scenario:
        return build_user_system_prompt_from_scenario(
            scenario=spec.user_scenario,
            domain=spec.domain,
        )

    # Fallback: create simple prompt from ticket
    if spec.ticket:
        return build_user_system_prompt(
            instruction=UserInstruction(goal=spec.ticket),
            domain=spec.domain,
        )

    # Default
    return build_user_system_prompt(
        instruction=UserInstruction(goal="Complete the task."),
        domain=spec.domain,
    )


def build_user_prompt_from_trajectory(
    trajectory: tuple[SimMessage, ...],
) -> list[dict[str, Any]]:
    """
    Convert simulation trajectory to user simulator messages. Pure.

    Returns messages in chat completion format from user's perspective.
    """
    messages = []

    for msg in trajectory:
        if msg.kind == MessageKind.USER:
            # User's own previous messages
            messages.append({"role": "assistant", "content": msg.content or ""})
        elif msg.kind == MessageKind.AGENT:
            # Assistant's messages (from user's view, these are incoming)
            content = msg.content or ""
            if msg.tool_calls:
                # Optionally include tool call info
                tool_names = [tc.name for tc in msg.tool_calls]
                if content:
                    content += f"\n\n[Used tools: {', '.join(tool_names)}]"
                else:
                    content = f"[Used tools: {', '.join(tool_names)}]"
            messages.append({"role": "user", "content": content})
        elif msg.kind == MessageKind.TOOL_RESULT:
            # Tool results - summarize for user context
            pass  # Skip tool results in user view

    return messages


# === User Response Parsing ===


@dataclass(frozen=True)
class UserResponseAnalysis:
    """Analysis of user's response. Pure data."""

    content: str
    indicates_complete: bool
    indicates_failed: bool
    provides_info: bool
    asks_question: bool


def analyze_user_response(content: str) -> UserResponseAnalysis:
    """
    Analyze user response for task completion signals. Pure.
    """
    upper = content.upper()

    return UserResponseAnalysis(
        content=content,
        indicates_complete="TASK_COMPLETE" in upper,
        indicates_failed="TASK_FAILED" in upper,
        provides_info=len(content) > 20,  # Simple heuristic
        asks_question="?" in content,
    )


# === User State (for multi-turn context) ===


@dataclass(frozen=True, slots=True)
class UserState:
    """
    Immutable user simulation state.

    Tracks user-side context across turns.
    """

    instruction: UserInstruction
    turn_count: int = 0
    info_provided: tuple[str, ...] = ()
    questions_asked: tuple[str, ...] = ()
    frustration_level: int = 0  # 0-10


def init_user_state(task: TaskConfig) -> UserState:
    """Initialize user state from task. Pure."""
    return UserState(instruction=task.user_instruction)


def update_user_state(
    state: UserState,
    user_response: str,
    agent_response: str | None,
) -> UserState:
    """
    Update user state after a turn. Pure.

    Tracks what info has been exchanged and user satisfaction.
    """
    analysis = analyze_user_response(user_response)

    # Track info provided
    new_info = state.info_provided
    if analysis.provides_info:
        new_info = state.info_provided + (user_response[:50],)

    # Track questions
    new_questions = state.questions_asked
    if analysis.asks_question:
        new_questions = state.questions_asked + (user_response[:50],)

    # Frustration increases if agent doesn't seem to help
    new_frustration = state.frustration_level
    if agent_response and len(agent_response) < 10:
        new_frustration = min(10, state.frustration_level + 1)

    return UserState(
        instruction=state.instruction,
        turn_count=state.turn_count + 1,
        info_provided=new_info,
        questions_asked=new_questions,
        frustration_level=new_frustration,
    )


# === Instruction Templates ===


def create_instruction(
    goal: str,
    context: str | None = None,
    constraints: tuple[str, ...] | None = None,
) -> UserInstruction:
    """Create user instruction. Convenience function."""
    return UserInstruction(
        goal=goal,
        context=context,
        constraints=constraints or (),
    )


# Common instruction patterns
def booking_instruction(
    item: str,
    date: str | None = None,
    preferences: tuple[str, ...] = (),
) -> UserInstruction:
    """Create booking-style instruction."""
    goal = f"Book a {item}"
    if date:
        goal += f" for {date}"

    return UserInstruction(
        goal=goal,
        context=f"You need to book a {item}.",
        constraints=preferences,
    )


def support_instruction(
    issue: str,
    account_info: str | None = None,
) -> UserInstruction:
    """Create customer support instruction."""
    context = f"You have an issue: {issue}"
    if account_info:
        context += f" Your account info: {account_info}"

    return UserInstruction(
        goal=f"Get help resolving: {issue}",
        context=context,
        constraints=("Be polite but firm", "Ask for confirmation when done"),
    )


def query_instruction(question: str) -> UserInstruction:
    """Create information query instruction."""
    return UserInstruction(
        goal=f"Get an answer to: {question}",
        context=None,
        constraints=("Accept concise answers", "Ask follow-up if unclear"),
    )
