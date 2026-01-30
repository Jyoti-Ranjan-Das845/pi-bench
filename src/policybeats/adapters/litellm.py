"""
LiteLLM adapter - implements LLMPort using LiteLLM.

LiteLLM provides a unified interface to multiple LLM providers:
- OpenAI (gpt-4, gpt-3.5-turbo, etc.)
- Anthropic (claude-3, etc.)
- Google (gemini, etc.)
- Local models (ollama, etc.)
"""

from __future__ import annotations

import json
from typing import Any, Literal

from policybeats.sim.types import MessageKind, SimMessage, ToolCallData


class LiteLLMAdapter:
    """
    LLM adapter using LiteLLM.

    Provides generate() method for both agent and user simulation.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        user_model: str | None = None,
        user_temperature: float | None = None,
    ):
        """
        Initialize LiteLLM adapter.

        Args:
            model: Model name for agent (e.g., "gpt-4o-mini", "claude-3-haiku")
            temperature: Sampling temperature for agent
            max_tokens: Max tokens for responses
            user_model: Optional different model for user simulation
            user_temperature: Optional different temperature for user
        """
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._user_model = user_model or model
        self._user_temperature = user_temperature or temperature

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
        Generate response using LiteLLM.

        Args:
            messages: Conversation history
            role: "agent" or "user" (for user simulation)
            system_prompt: Optional system prompt
            tools: Optional tool schemas (for agent with function calling)

        Returns:
            SimMessage with generated response
        """
        try:
            import litellm
        except ImportError as e:
            raise ImportError(
                "litellm is required for LiteLLMAdapter. "
                "Install with: pip install litellm"
            ) from e

        # Select model and temperature based on role
        model = self._model if role == "agent" else self._user_model
        temperature = self._temperature if role == "agent" else self._user_temperature

        # Convert messages to LiteLLM format
        api_messages = self._to_api_messages(messages, role, system_prompt)

        # Build request kwargs
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "temperature": temperature,
            "max_tokens": self._max_tokens,
        }

        # Add tools for agent if provided
        if role == "agent" and tools:
            kwargs["tools"] = list(tools)
            kwargs["tool_choice"] = "auto"

        # Make API call
        response = litellm.completion(**kwargs)

        # Parse response
        return self._parse_response(response, role, model)

    def _to_api_messages(
        self,
        messages: tuple[SimMessage, ...],
        role: Literal["agent", "user"],
        system_prompt: str | None,
    ) -> list[dict[str, Any]]:
        """Convert SimMessages to API format."""
        api_messages: list[dict[str, Any]] = []

        # Add system prompt
        if system_prompt:
            api_messages.append({"role": "system", "content": system_prompt})

        # Convert messages
        for msg in messages:
            api_msg = self._sim_to_api_message(msg, role)
            if api_msg:
                api_messages.append(api_msg)

        return api_messages

    def _sim_to_api_message(
        self,
        msg: SimMessage,
        perspective: Literal["agent", "user"],
    ) -> dict[str, Any] | None:
        """
        Convert single SimMessage to API format.

        The perspective determines role mapping:
        - Agent perspective: user messages are "user", agent messages are "assistant"
        - User perspective: user messages are "assistant", agent messages are "user"
        """
        if msg.kind == MessageKind.USER:
            if perspective == "agent":
                return {"role": "user", "content": msg.content or ""}
            else:
                # User simulator sees their own messages as "assistant"
                return {"role": "assistant", "content": msg.content or ""}

        elif msg.kind == MessageKind.AGENT:
            content = msg.content or ""

            if perspective == "agent":
                # Agent's own messages
                api_msg: dict[str, Any] = {"role": "assistant"}

                if msg.tool_calls:
                    # Include tool calls in proper format
                    api_msg["tool_calls"] = [
                        {
                            "id": tc.call_id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in msg.tool_calls
                    ]
                    if content:
                        api_msg["content"] = content
                else:
                    api_msg["content"] = content

                return api_msg
            else:
                # User sees agent messages as incoming
                if msg.tool_calls:
                    tool_names = [tc.name for tc in msg.tool_calls]
                    content = f"{content}\n[Used tools: {', '.join(tool_names)}]" if content else f"[Used tools: {', '.join(tool_names)}]"
                return {"role": "user", "content": content}

        elif msg.kind == MessageKind.TOOL_RESULT:
            if perspective == "agent":
                # Agent sees tool results
                return {
                    "role": "tool",
                    "tool_call_id": msg.call_id,
                    "content": msg.content or "",
                }
            # User doesn't see tool results directly
            return None

        elif msg.kind == MessageKind.SYSTEM:
            return {"role": "system", "content": msg.content or ""}

        return None

    def _parse_response(
        self,
        response: Any,
        role: Literal["agent", "user"],
        model: str,
    ) -> SimMessage:
        """Parse LiteLLM response to SimMessage."""
        choice = response.choices[0]
        message = choice.message

        # Determine message kind
        kind = MessageKind.USER if role == "user" else MessageKind.AGENT

        # Extract content
        content = message.content

        # Extract tool calls if present
        tool_calls: tuple[ToolCallData, ...] = ()
        if hasattr(message, "tool_calls") and message.tool_calls:
            tool_calls = tuple(
                ToolCallData(
                    call_id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments) if tc.function.arguments else {},
                )
                for tc in message.tool_calls
            )

        return SimMessage(
            kind=kind,
            content=content,
            tool_calls=tool_calls,
            model=model,
        )


class OllamaAdapter(LiteLLMAdapter):
    """
    Convenience adapter for Ollama local models.

    Uses litellm's ollama provider prefix.
    """

    def __init__(
        self,
        model: str = "llama3.2",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        base_url: str = "http://localhost:11434",
    ):
        # Ollama models in litellm use "ollama/" prefix
        ollama_model = f"ollama/{model}" if not model.startswith("ollama/") else model
        super().__init__(
            model=ollama_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._base_url = base_url


class AnthropicAdapter(LiteLLMAdapter):
    """
    Convenience adapter for Anthropic Claude models.

    Uses litellm's anthropic provider.
    """

    def __init__(
        self,
        model: str = "claude-3-haiku-20240307",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )


class OpenAIAdapter(LiteLLMAdapter):
    """
    Convenience adapter for OpenAI models.

    Uses litellm's default OpenAI provider.
    """

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ):
        super().__init__(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
