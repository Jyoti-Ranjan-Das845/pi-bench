"""
Scenario-based mock LLM for testing without API keys.

Captures task metadata and generates realistic responses including tool calls.
The scenario context is maintained across the conversation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from policybeats.sim.types import (
    MessageKind,
    SimMessage,
    TaskConfig,
    ToolCallData,
    UserInstruction,
)


@dataclass
class ScenarioState:
    """Tracks scenario state for realistic mock responses."""

    turn: int = 0
    user_goal: str = ""
    user_constraints: tuple[str, ...] = ()
    available_tools: tuple[str, ...] = ()
    pending_actions: list[str] = field(default_factory=list)
    completed_actions: list[str] = field(default_factory=list)
    tool_results: dict[str, str] = field(default_factory=dict)


class ScenarioMockLLM:
    """
    Mock LLM that generates realistic responses based on scenario context.

    Features:
    - Understands task metadata (goal, constraints, tools)
    - Generates appropriate tool calls for agent role
    - Simulates user responses based on goal progress
    - Maintains conversation context across turns
    """

    def __init__(self, task: TaskConfig):
        """
        Initialize with task configuration.

        Args:
            task: TaskConfig containing scenario metadata
        """
        self._task = task
        self._state = ScenarioState(
            user_goal=task.user_instruction.goal,
            user_constraints=task.user_instruction.constraints,
            available_tools=task.available_tools,
        )
        self._model = "scenario-mock"

        # Parse goal to determine expected actions
        self._parse_goal()

    def _parse_goal(self) -> None:
        """Parse user goal to determine expected actions."""
        goal = self._state.user_goal.lower()

        # Simple pattern matching for common actions
        if "create" in goal and "user" in goal:
            self._state.pending_actions.append("create_user")

        if "create" in goal and "task" in goal:
            self._state.pending_actions.append("create_task")

        if "list" in goal and "user" in goal:
            self._state.pending_actions.append("list_users")

        if "complete" in goal and "task" in goal:
            self._state.pending_actions.append("complete_task")

        # Extract names if mentioned
        name_match = re.search(r"named?\s+['\"]?(\w+)['\"]?", self._state.user_goal)
        if name_match:
            self._state.tool_results["target_name"] = name_match.group(1)

    @property
    def model_name(self) -> str:
        return self._model

    def generate(
        self,
        messages: tuple[SimMessage, ...],
        role: Literal["agent", "user"],
        system_prompt: str | None = None,
        tools: tuple[dict[str, Any], ...] | None = None,
    ) -> SimMessage:
        """
        Generate response based on role and scenario context.
        """
        self._state.turn += 1

        if role == "user":
            return self._generate_user_response(messages)
        else:
            return self._generate_agent_response(messages, tools)

    def _generate_user_response(
        self,
        messages: tuple[SimMessage, ...],
    ) -> SimMessage:
        """Generate user simulator response."""
        # Check if all actions completed
        if not self._state.pending_actions and self._state.completed_actions:
            return SimMessage(
                kind=MessageKind.USER,
                content=f"Thank you! That's exactly what I needed. TASK_COMPLETE",
                model=self._model,
            )

        # Check last agent message for context
        last_agent_msg = None
        for msg in reversed(messages):
            if msg.kind == MessageKind.AGENT:
                last_agent_msg = msg
                break

        # First turn - state the goal
        if self._state.turn <= 2:
            return SimMessage(
                kind=MessageKind.USER,
                content=self._state.user_goal,
                model=self._model,
            )

        # If agent just completed an action, acknowledge and continue
        if last_agent_msg and self._state.completed_actions:
            last_completed = self._state.completed_actions[-1]
            if self._state.pending_actions:
                next_action = self._state.pending_actions[0]
                return SimMessage(
                    kind=MessageKind.USER,
                    content=f"Great! The {last_completed} worked. Now please {next_action.replace('_', ' ')}.",
                    model=self._model,
                )

        # Default: request next action
        if self._state.pending_actions:
            action = self._state.pending_actions[0]
            return SimMessage(
                kind=MessageKind.USER,
                content=f"Please {action.replace('_', ' ')} for me.",
                model=self._model,
            )

        # Fallback
        return SimMessage(
            kind=MessageKind.USER,
            content="TASK_COMPLETE",
            model=self._model,
        )

    def _generate_agent_response(
        self,
        messages: tuple[SimMessage, ...],
        tools: tuple[dict[str, Any], ...] | None,
    ) -> SimMessage:
        """Generate agent response with potential tool calls."""
        # Check last message for context
        last_user_msg = None
        last_tool_result = None

        for msg in reversed(messages):
            if msg.kind == MessageKind.USER and not last_user_msg:
                last_user_msg = msg
            if msg.kind == MessageKind.TOOL_RESULT and not last_tool_result:
                last_tool_result = msg

        # If we just got a tool result, acknowledge it
        if last_tool_result:
            result = last_tool_result.content or ""
            try:
                data = json.loads(result)
                if "created" in data:
                    # Mark action as completed
                    for action in list(self._state.pending_actions):
                        if action in ["create_user", "create_task"]:
                            self._state.pending_actions.remove(action)
                            self._state.completed_actions.append(action)
                            break

                    return SimMessage(
                        kind=MessageKind.AGENT,
                        content=f"Done! I've {self._state.completed_actions[-1].replace('_', ' ')}. {json.dumps(data)}",
                        model=self._model,
                    )
            except json.JSONDecodeError:
                pass

            return SimMessage(
                kind=MessageKind.AGENT,
                content=f"Result: {result}",
                model=self._model,
            )

        # Determine what tool to call based on pending actions
        if self._state.pending_actions and tools:
            action = self._state.pending_actions[0]
            tool_name = action  # e.g., "create_user"

            # Find matching tool
            for tool_schema in tools:
                if tool_schema.get("function", {}).get("name") == tool_name:
                    args = self._generate_tool_args(tool_name)
                    call_id = f"call_{self._state.turn}_{tool_name}"

                    return SimMessage(
                        kind=MessageKind.AGENT,
                        content=f"I'll {tool_name.replace('_', ' ')} for you.",
                        tool_calls=(
                            ToolCallData(
                                call_id=call_id,
                                name=tool_name,
                                arguments=args,
                            ),
                        ),
                        model=self._model,
                    )

        # Default response
        return SimMessage(
            kind=MessageKind.AGENT,
            content="How can I help you?",
            model=self._model,
        )

    def _generate_tool_args(self, tool_name: str) -> dict[str, Any]:
        """Generate appropriate arguments for a tool call."""
        target_name = self._state.tool_results.get("target_name", "User1")

        if tool_name == "create_user":
            return {
                "name": target_name,
                "email": f"{target_name.lower()}@example.com",
            }
        elif tool_name == "create_task":
            return {
                "title": f"Task for {target_name}",
                "description": "Auto-generated task",
                "assignee": "user_1",  # Assume first user
            }
        elif tool_name == "get_user":
            return {"user_id": "user_1"}
        elif tool_name == "complete_task":
            return {"task_id": "task_1"}
        elif tool_name == "list_users":
            return {}
        elif tool_name == "list_tasks":
            return {}

        return {}


def create_scenario_mock(task: TaskConfig) -> ScenarioMockLLM:
    """Factory function to create a scenario mock LLM."""
    return ScenarioMockLLM(task)
