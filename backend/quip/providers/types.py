"""Provider-neutral completion events. Providers re-export these for compatibility."""

from dataclasses import dataclass


@dataclass
class UsageInfo:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost: float = 0.0
    is_byok: bool = False
    generation_id: str = ""
    provider: str = ""


@dataclass
class ToolCallDelta:
    """A partial tool call from streaming."""

    index: int = 0
    id: str = ""
    function_name: str = ""
    function_arguments: str = ""


@dataclass
class StreamChunk:
    """A single chunk from the SSE stream."""

    content: str = ""
    reasoning: str = ""
    finish_reason: str | None = None
    usage: UsageInfo | None = None
    error: str | None = None
    model: str = ""
    provider: str = ""
    tool_calls: list[ToolCallDelta] | None = None
