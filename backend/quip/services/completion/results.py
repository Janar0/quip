"""Accumulation and persistence of a provider stream, shared by send and regenerate."""

import json
from dataclasses import dataclass, field

from quip.services.completion.search_sources import append_retrieved_sources
from quip.services.completion.stream import fetch_generation_cost
from quip.services.streaming import sse_event


def _parse_sse_frame(frame: str) -> tuple[str, dict]:
    """Parse SSE frame into (event_type, data)."""
    ev = ""
    data_str = ""
    for line in frame.strip().split("\n"):
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]
    try:
        data = json.loads(data_str) if data_str else {}
    except json.JSONDecodeError:
        data = {}
    return ev, data


def _accumulate_usage(acc: dict | None, new: dict | None) -> dict | None:
    """Sum usage across streaming rounds.

    The orchestrator emits one usage event per round (a tool/search turn runs
    several rounds). Persisting only the last round under-counts tokens and
    cost for every earlier round, so we accumulate instead of overwrite —
    mirroring ResearchSession.add_usage for the deep-research path.
    """
    if not new:
        return acc
    if acc is None:
        acc = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost": 0.0}
    for k in ("prompt_tokens", "completion_tokens", "cached_tokens"):
        acc[k] = (acc.get(k) or 0) + (new.get(k) or 0)
    acc["cost"] = (acc.get("cost") or 0.0) + (new.get("cost") or 0.0)
    if new.get("provider"):
        acc["provider"] = new["provider"]
    # Keep the most recent generation_id — used as the cost-fetch fallback.
    if new.get("generation_id"):
        acc["generation_id"] = new["generation_id"]
    return acc


@dataclass
class StreamResult:
    content: str = ""
    reasoning: str = ""
    usage: dict | None = None
    tool_executions: list[dict] = field(default_factory=list)
    search_images: list[dict] = field(default_factory=list)
    failed: bool = False

    def accumulate(self, event_type, data):
        if event_type == "content":
            self.content += data.get("text", "")
        elif event_type == "reasoning":
            self.reasoning += data.get("text", "")
        elif event_type == "usage":
            self.usage = _accumulate_usage(self.usage, data)
        elif event_type == "tool_executing":
            self.tool_executions.append(
                {
                    "id": data.get("id"),
                    "name": data.get("name"),
                    "arguments": data.get("arguments"),
                    "status": "running",
                }
            )
        elif event_type == "tool_result":
            result = data.get("result")
            try:
                result = json.loads(result) if isinstance(result, str) else result
            except json.JSONDecodeError:
                pass
            for execution in self.tool_executions:
                if execution.get("id") == data.get("id"):
                    execution.update({"result": result, "status": data.get("status", "completed")})
                    break
        elif event_type == "search_images":
            incoming = data.get("images") or []
            if not data.get("append"):
                self.search_images = list(incoming)
            else:
                known = {item.get("img_src") for item in self.search_images}
                self.search_images.extend(item for item in incoming if item.get("img_src") not in known)
            self.search_images = self.search_images[:10]

    async def persist(self, save, *, message_id, chat_id, user_id, model):
        if self.content:
            await save(
                message_id,
                chat_id,
                user_id,
                self.content,
                model,
                self.usage,
                reasoning=self.reasoning,
                tool_executions=self.tool_executions,
                search_images=self.search_images,
            )

    async def stream(self, frames, *, prompt, save, message_id, chat_id, user_id):
        """Preserve SSE order, including yielding errors before saving partial output."""
        async for frame in frames:
            event_type, data = _parse_sse_frame(frame)
            self.accumulate(event_type, data)
            if event_type == "error":
                self.failed = True
                if prompt.search_mode and self.content:
                    self.content = append_retrieved_sources(self.content, self.tool_executions, prompt.locale)
                    yield sse_event("content", {"text": self.content})
                yield frame
                await self.persist(save, message_id=message_id, chat_id=chat_id, user_id=user_id, model=prompt.model)
                return
            if not (prompt.search_mode and event_type == "content"):
                yield frame
        if not self.content and self.reasoning:
            self.content = self.reasoning
            self.reasoning = ""
            if not prompt.search_mode:
                yield sse_event("content", {"text": self.content})
        if prompt.search_mode:
            self.content = append_retrieved_sources(self.content, self.tool_executions, prompt.locale)
            if self.content:
                yield sse_event("content", {"text": self.content})
        if self.usage:
            await fetch_generation_cost(prompt.api_key, self.usage)
        await self.persist(save, message_id=message_id, chat_id=chat_id, user_id=user_id, model=prompt.model)
