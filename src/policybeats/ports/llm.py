"""
LLM Port - abstract interface for language model calls.

Implementations provide actual LLM API calls (OpenAI, Anthropic, etc.).
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from policybeats.sim.types import SimMessage


class LLMPort(Protocol):
    """
    Protocol for LLM generation.

    Implementations handle the actual API calls to language models.
    """

    def generate(
        self,
        messages: tuple[SimMessage, ...],
        role: Literal["agent", "user"],
        system_prompt: str | None = None,
        tools: tuple[dict[str, Any], ...] | None = None,
    ) -> SimMessage:
        """
        Generate a response from the LLM.

        Args:
            messages: Conversation history as SimMessages
            role: Whether generating as "agent" or "user" (for user simulation)
            system_prompt: Optional system prompt override
            tools: Optional tool schemas (for agent role with function calling)

        Returns:
            SimMessage with the generated response
        """
        ...

    @property
    def model_name(self) -> str:
        """Return the model identifier being used."""
        ...


class MockLLMPort:
    """Mock LLM for testing - returns canned responses."""

    def __init__(
        self,
        responses: list[str] | None = None,
        model: str = "mock-model",
    ):
        self._responses = responses or ["Mock response."]
        self._index = 0
        self._model = model

    def generate(
        self,
        messages: tuple[SimMessage, ...],
        role: Literal["agent", "user"],
        system_prompt: str | None = None,
        tools: tuple[dict[str, Any], ...] | None = None,
    ) -> SimMessage:
        """Return next canned response."""
        from policybeats.sim.types import MessageKind

        response = self._responses[self._index % len(self._responses)]
        self._index += 1

        kind = MessageKind.USER if role == "user" else MessageKind.AGENT
        return SimMessage(kind=kind, content=response, model=self._model)

    @property
    def model_name(self) -> str:
        return self._model
