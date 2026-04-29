"""SSE framing + content coalescing for streaming chat completions."""
from __future__ import annotations

import json
import time

# Per-chunk SSE envelope is ~25 bytes. For provider streams that emit one token
# per delta, the envelope can dominate output. Coalescing within ~30ms — below
# the human visual fusion threshold — roughly halves stream traffic without a
# perceptible UI change.
COALESCE_WINDOW = 0.03


def sse_event(event: str, data: dict) -> str:
    """Format a single SSE frame."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def is_ollama_model(model: str) -> bool:
    return model.startswith("ollama/")


class TextCoalescer:
    """Buffers streamed content/reasoning text and emits batched SSE frames
    when the time window elapses or a flush is forced."""

    __slots__ = ("_content", "_reasoning", "_last_flush")

    def __init__(self) -> None:
        self._content = ""
        self._reasoning = ""
        self._last_flush = 0.0

    def add(self, content: str = "", reasoning: str = "") -> None:
        if content:
            self._content += content
        if reasoning:
            self._reasoning += reasoning

    def maybe_flush(self) -> list[str]:
        now = time.monotonic()
        if not self._content and not self._reasoning:
            return []
        if self._last_flush and (now - self._last_flush) < COALESCE_WINDOW:
            return []
        return self.flush()

    def flush(self) -> list[str]:
        out: list[str] = []
        if self._reasoning:
            out.append(sse_event("reasoning", {"text": self._reasoning}))
            self._reasoning = ""
        if self._content:
            out.append(sse_event("content", {"text": self._content}))
            self._content = ""
        if out:
            self._last_flush = time.monotonic()
        return out
