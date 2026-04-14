"""Shared message types, factory functions, and validation for pi-bench."""

import uuid
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)


VALID_REQUESTORS = {"assistant", "user"}
PARTICIPANT_ROLES = {"assistant", "user"}
MESSAGE_ROLES = {"assistant", "user", "system", "tool", "multi_tool"}
STOP_SIGNALS = ("###STOP###", "###TRANSFER###", "###OUT-OF-SCOPE###")
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


# --- Pydantic runtime contract models ---


class ToolCallModel(BaseModel):
    """Strict public shape for a participant tool call."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: NonEmptyStr
    name: NonEmptyStr
    arguments: dict[str, Any]
    requestor: Literal["assistant", "user"] | None = None


class ParticipantMessageModel(BaseModel):
    """Strict public shape for assistant/user messages."""

    model_config = ConfigDict(extra="allow", strict=True)

    role: Literal["assistant", "user"]
    content: Any = None
    tool_calls: list[ToolCallModel] | None = None

    @model_validator(mode="after")
    def _content_or_tool_calls(self) -> "ParticipantMessageModel":
        if self.tool_calls is not None and not self.tool_calls:
            raise ValueError("tool_calls must be non-empty when provided")
        has_content = bool(extract_message_content({"content": self.content}).strip())
        if not has_content and not self.tool_calls:
            raise ValueError("participant messages require content or tool_calls")
        return self


class ToolMessageModel(BaseModel):
    """Strict public shape for tool result messages."""

    model_config = ConfigDict(extra="allow", strict=True)

    role: Literal["tool"] = "tool"
    id: NonEmptyStr
    content: Any
    requestor: Literal["assistant", "user"]
    error: bool = False


class SystemMessageModel(BaseModel):
    """Strict public shape for system messages."""

    model_config = ConfigDict(extra="allow", strict=True)

    role: Literal["system"] = "system"
    content: Any

    @model_validator(mode="after")
    def _has_content(self) -> "SystemMessageModel":
        if not extract_message_content({"content": self.content}).strip():
            raise ValueError("system messages require non-empty content")
        return self


class MultiToolMessageModel(BaseModel):
    """Strict public shape for a wrapper around multiple tool results."""

    model_config = ConfigDict(extra="allow", strict=True)

    role: Literal["multi_tool"] = "multi_tool"
    tool_messages: list[ToolMessageModel] = Field(min_length=1)


# --- Factory functions ---


def make_assistant_msg(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    cost: float = 0.0,
    usage: dict | None = None,
) -> dict:
    """Create an assistant message dict."""
    msg: dict[str, Any] = {"role": "assistant", "cost": cost, "usage": usage}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def make_user_msg(
    content: str | None = None,
    tool_calls: list[dict] | None = None,
    cost: float = 0.0,
    usage: dict | None = None,
) -> dict:
    """Create a user message dict."""
    msg: dict[str, Any] = {"role": "user", "cost": cost, "usage": usage}
    if content is not None:
        msg["content"] = content
    if tool_calls is not None:
        msg["tool_calls"] = tool_calls
    return msg


def make_tool_msg(
    call_id: str,
    content: str,
    requestor: str,
    error: bool = False,
    name: str | None = None,
) -> dict:
    """Create a tool result message dict."""
    msg: dict[str, Any] = _validate_or_raise(
        ToolMessageModel,
        {
            "role": "tool",
            "id": call_id,
            "content": content,
            "requestor": requestor,
            "error": error,
        },
        "tool message",
    )
    if name is not None:
        msg["name"] = name
    return msg


def make_system_msg(content: str) -> dict:
    """Create a system message dict."""
    return _validate_or_raise(
        SystemMessageModel,
        {"role": "system", "content": content},
        "system message",
    )


def build_tool_call(
    name: str,
    arguments: dict | None = None,
    requestor: str = "assistant",
    call_id: str | None = None,
) -> dict:
    """Create a tool call dict (for embedding in assistant/user messages)."""
    if arguments is None:
        normalized_arguments = {}
    else:
        normalized_arguments = arguments
    return _validate_or_raise(
        ToolCallModel,
        {
            "id": str(uuid.uuid4()) if call_id is None else call_id,
            "name": name,
            "arguments": normalized_arguments,
            "requestor": requestor,
        },
        "tool call",
    )


# --- Validation ---


def validate_message(msg: dict) -> bool:
    """Check that a pi-bench message has a valid public shape.

    Assistant/user messages may contain text, tool calls, or both. If tool calls
    are present, the orchestrator routes the message to the environment and keeps
    any text content in the trajectory for context/debugging.
    """
    try:
        _message_model_for(msg).model_validate(msg)
    except (TypeError, ValidationError, ValueError):
        return False

    return True


def validate_tool_call(tool_call: dict) -> bool:
    """Check that a tool-call dict has the required runtime shape."""
    try:
        ToolCallModel.model_validate(tool_call)
    except (TypeError, ValidationError, ValueError):
        return False
    return True


def is_stop_signal(msg: dict) -> bool:
    """Check if a message contains a stop, transfer, or out-of-scope signal."""
    content = msg.get("content", "")
    return content in STOP_SIGNALS


# --- Content extraction ---


def extract_message_content(msg: dict) -> str:
    """Extract text content from a message, handling string and list formats.

    Handles both plain string content and Anthropic-format list content blocks
    (e.g., [{"type": "text", "text": "..."}]).
    """
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content if isinstance(b, dict)
        )
    return content if isinstance(content, str) else ""


def _validate_participant_message(msg: dict) -> bool:
    try:
        ParticipantMessageModel.model_validate(msg)
    except (TypeError, ValidationError, ValueError):
        return False
    return True


def _validate_tool_message(msg: dict) -> bool:
    try:
        ToolMessageModel.model_validate(msg)
    except (TypeError, ValidationError, ValueError):
        return False
    return True


def _has_text_content(msg: dict) -> bool:
    content = extract_message_content(msg)
    return bool(content.strip())


def _message_model_for(msg: Any) -> type[BaseModel]:
    """Return the Pydantic model matching a raw message role."""
    if not isinstance(msg, dict):
        raise TypeError("message must be a dict")
    role = msg.get("role")
    if role in PARTICIPANT_ROLES:
        return ParticipantMessageModel
    if role == "system":
        return SystemMessageModel
    if role == "tool":
        return ToolMessageModel
    if role == "multi_tool":
        return MultiToolMessageModel
    raise ValueError(f"unknown message role: {role!r}")


def _validate_or_raise(model_type: type[BaseModel], data: dict, label: str) -> dict:
    """Validate data with Pydantic and raise compact ValueError on failure."""
    try:
        return model_type.model_validate(data).model_dump(exclude_none=True)
    except ValidationError as exc:
        fields = ", ".join(
            str(error["loc"][0]) if error.get("loc") else "value"
            for error in exc.errors()
        )
        raise ValueError(f"{label} validation failed for {fields}: {exc}") from exc


__all__ = [
    "MESSAGE_ROLES",
    "PARTICIPANT_ROLES",
    "STOP_SIGNALS",
    "VALID_REQUESTORS",
    "MultiToolMessageModel",
    "ParticipantMessageModel",
    "SystemMessageModel",
    "ToolCallModel",
    "ToolMessageModel",
    "build_tool_call",
    "extract_message_content",
    "is_stop_signal",
    "make_assistant_msg",
    "make_system_msg",
    "make_tool_msg",
    "make_user_msg",
    "validate_message",
    "validate_tool_call",
]
