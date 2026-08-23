"""Provider-neutral typed schemas shared across providers, tools, and the core.

These types are the lingua franca between the reasoning layer (providers) and the
orchestrator. Provider adapters translate *to and from* their wire formats; the
rest of the codebase only ever sees these shapes. Nothing here is coupled to a
specific vendor.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TextBlock(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ToolUseBlock(BaseModel):
    """A model's request to call a tool."""

    type: Literal["tool_use"] = "tool_use"
    id: str
    name: str
    input: dict[str, Any] = Field(default_factory=dict)


class ToolResultBlock(BaseModel):
    """The result of executing a tool, fed back to the model."""

    type: Literal["tool_result"] = "tool_result"
    tool_use_id: str
    content: str
    is_error: bool = False


ContentBlock = Annotated[
    TextBlock | ToolUseBlock | ToolResultBlock,
    Field(discriminator="type"),
]


class Message(BaseModel):
    """A single conversation turn."""

    model_config = ConfigDict(use_enum_values=True)

    role: Role
    content: list[ContentBlock]

    @classmethod
    def user(cls, text: str) -> Message:
        return cls(role=Role.USER, content=[TextBlock(text=text)])

    @classmethod
    def assistant(cls, text: str) -> Message:
        return cls(role=Role.ASSISTANT, content=[TextBlock(text=text)])

    def text(self) -> str:
        """Concatenate all text blocks (ignoring tool blocks)."""
        return "".join(b.text for b in self.content if isinstance(b, TextBlock))


class ToolSpec(BaseModel):
    """A typed tool definition exposed to a provider.

    ``writes`` distinguishes read-only tools from ones that would modify external
    state; the orchestrator keeps the two classes separate and never exposes
    write tools without an explicit ``--apply`` opt-in.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    writes: bool = False


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class Usage(BaseModel):
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    reasoning_tokens: int | None = None
    cost_usd: float | None = None

    def merge(self, other: Usage) -> Usage:
        def _add(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return Usage(
            input_tokens=_add(self.input_tokens, other.input_tokens),
            output_tokens=_add(self.output_tokens, other.output_tokens),
            cached_input_tokens=_add(self.cached_input_tokens, other.cached_input_tokens),
            reasoning_tokens=_add(self.reasoning_tokens, other.reasoning_tokens),
            cost_usd=_add_float(self.cost_usd, other.cost_usd),
        )


def _add_float(a: float | None, b: float | None) -> float | None:
    if a is None and b is None:
        return None
    return (a or 0.0) + (b or 0.0)


class StopReason(StrEnum):
    END_TURN = "end_turn"
    TOOL_USE = "tool_use"
    MAX_TOKENS = "max_tokens"
    STOP_SEQUENCE = "stop_sequence"
    REFUSAL = "refusal"
    ERROR = "error"
    CANCELLED = "cancelled"


class Completion(BaseModel):
    """A single provider response (one round; may contain tool-call requests)."""

    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    stop_reason: StopReason = StopReason.END_TURN
    usage: Usage = Field(default_factory=Usage)
    model: str | None = None


class ModelInfo(BaseModel):
    """A model advertised by a provider's discovery endpoint."""

    id: str
    provider: str
    display_name: str | None = None
    context_window: int | None = None


class GenerateParams(BaseModel):
    """Inputs to a single provider generation call.

    A typed request object (rather than a long kwargs list) keeps the provider
    interface stable and makes contract tests trivial to construct.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: str
    messages: list[Message]
    system: str | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    max_tokens: int = 4096
    temperature: float | None = None
    timeout_s: float = 120.0
    # JSON Schema for structured output, when the caller wants a typed result.
    response_schema: dict[str, Any] | None = None


class StreamEventType(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    DONE = "done"
    ERROR = "error"


class StreamEvent(BaseModel):
    """A single streamed increment from a provider."""

    type: StreamEventType
    text: str = ""
    tool_call: ToolCall | None = None
    completion: Completion | None = None
