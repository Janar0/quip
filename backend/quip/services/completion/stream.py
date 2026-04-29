"""SSE streaming orchestrator for chat completions."""
import asyncio
import logging
from collections.abc import AsyncGenerator

from quip.providers import openrouter, ollama
from quip.services.streaming import (
    sse_event,
    TextCoalescer,
    is_ollama_model,
)
from quip.services.tools import accumulate_tool_calls
from quip.services.completion.prompt import PromptBuilder
from quip.services.completion.tool_executor import ToolExecutor
from quip.services.research import run_deep_research, ResearchEvent

logger = logging.getLogger(__name__)


class StreamOrchestrator:
    """Manages the SSE streaming loop for a single completion turn."""

    def __init__(
        self,
        messages: list[dict],
        model: str,
        base_url: str,
        api_key: str,
        tool_gating_enabled: bool,
        search_enabled: bool,
        search_mode: bool,
        sandbox_available: bool,
        loaded_skills: set[str],
    ):
        self.messages = messages
        self.model = model
        self.is_ollama = is_ollama_model(model)
        self.base_url = base_url
        self.api_key = api_key
        self.tool_gating_enabled = tool_gating_enabled
        self.search_enabled = search_enabled
        self.search_mode = search_mode
        self.sandbox_available = sandbox_available
        self.loaded_skills = loaded_skills

    def _build_tools(self) -> list[dict]:
        return PromptBuilder.build_tools(
            tool_gating_enabled=self.tool_gating_enabled,
            loaded_skills=self.loaded_skills,
            search_mode=self.search_mode,
            search_enabled=self.search_enabled,
            sandbox_available=self.sandbox_available,
        )

    def _call_provider(self, tools: list[dict]):
        if self.is_ollama:
            ollama_model = self.model.removeprefix("ollama/")
            return ollama.stream_completion(
                messages=self.messages,
                model=ollama_model,
                base_url=self.base_url,
                tools=tools,
            )
        return openrouter.stream_completion(
            messages=self.messages,
            model=self.model,
            api_key=self.api_key,
            tools=tools,
        )

    async def _stream_chunks(self, tools: list[dict]) -> AsyncGenerator[str | tuple, None]:
        """Stream one round of provider response. Yields SSE strings or (event, data) tuples."""
        coalescer = TextCoalescer()
        stream = self._call_provider(tools)

        async for chunk in stream:
            if chunk.error:
                for ev in coalescer.flush():
                    yield ev
                yield ("error", {"message": chunk.error})
                return

            if chunk.reasoning:
                coalescer.add(reasoning=chunk.reasoning)

            if chunk.content:
                coalescer.add(content=chunk.content)

            if chunk.content or chunk.reasoning:
                for ev in coalescer.maybe_flush():
                    yield ev

            if chunk.tool_calls:
                yield ("tool_calls", chunk.tool_calls)

            if chunk.model:
                yield ("model_update", {"model": chunk.model})

            if chunk.finish_reason:
                for ev in coalescer.flush():
                    yield ev
                yield ("finish", {"reason": chunk.finish_reason})

            if chunk.usage:
                for ev in coalescer.flush():
                    yield ev
                yield ("usage", chunk.usage)

        for ev in coalescer.flush():
            yield ev

    async def run(
        self,
        chat_id: str,
        user_id,
        max_rounds: int = 12,
    ) -> AsyncGenerator[str, None]:
        """Main streaming loop. Yields SSE-formatted strings."""
        sandbox = None
        accumulated_images: dict[str, dict] = {}
        accumulated_sources: list[dict] = []
        emitted_image_count = 0

        for _round_num in range(max_rounds):
            tools = self._build_tools()
            accumulated_tool_calls = []

            async for item in self._stream_chunks(tools):
                if isinstance(item, str):
                    yield item
                    continue

                ev_type, data = item

                if ev_type == "error":
                    yield sse_event(ev_type, data)
                    return

                if ev_type == "model_update":
                    continue

                if ev_type == "tool_calls":
                    accumulate_tool_calls(accumulated_tool_calls, data)
                    continue

                if ev_type == "usage":
                    yield sse_event("usage", {
                        "prompt_tokens": data.prompt_tokens,
                        "completion_tokens": data.completion_tokens,
                        "cached_tokens": data.cached_tokens,
                        "cost": data.cost,
                        "provider": data.provider,
                    })
                    continue

                if ev_type == "finish":
                    yield sse_event(ev_type, data)
                    continue

            # No tool calls — complete
            if not accumulated_tool_calls:
                break

            # Build assistant API message with tool_calls
            assistant_api_msg: dict = {"role": "assistant"}
            assistant_api_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function_name,
                        "arguments": tc.function_arguments,
                    },
                }
                for tc in accumulated_tool_calls
            ]
            self.messages.append(assistant_api_msg)

            # Emit all tool_executing events
            for tc in accumulated_tool_calls:
                yield sse_event(
                    "tool_executing",
                    {
                        "id": tc.id,
                        "name": tc.function_name,
                        "arguments": tc.function_arguments,
                    },
                )

            # Execute tool calls
            sandbox, tool_results = await ToolExecutor.execute(
                accumulated_tool_calls,
                sandbox,
                chat_id,
                self.loaded_skills,
                user_id,
            )

            # Emit tool_results and build tool messages
            for tc, (name, parsed, raw) in zip(
                accumulated_tool_calls, tool_results
            ):
                is_error = bool(
                    parsed.get("error") or parsed.get("exit_code", 0) != 0
                )
                status = "error" if is_error else "completed"
                yield sse_event(
                    "tool_result",
                    {
                        "id": tc.id,
                        "name": name,
                        "result": raw,
                        "status": status,
                    },
                )
                self.messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": raw}
                )

            # Accumulate search data for image grid / sources
            if self.search_mode:
                accumulated_images, accumulated_sources = (
                    ToolExecutor.accumulate_search_data(
                        tool_results, accumulated_images, accumulated_sources
                    )
                )
                new_imgs = list(accumulated_images.values())[
                    emitted_image_count:10
                ]
                if new_imgs:
                    yield sse_event(
                        "search_images", {"images": new_imgs, "append": True}
                    )
                    emitted_image_count = min(len(accumulated_images), 10)

        # Emit final image grid
        if self.search_mode and accumulated_images:
            top = list(accumulated_images.values())[:10]
            if top:
                yield sse_event("search_images", {"images": top})

    @staticmethod
    async def run_deep_research_stream(
        query: str,
        model: str,
        api_key: str,
        ollama_url: str,
        locale: str | None,
        location: str | None,
        is_ollama: bool,
    ) -> AsyncGenerator[str, None]:
        """Deep research mode: coordinator agent spawns sub-agents."""
        queue: asyncio.Queue[ResearchEvent] = asyncio.Queue()

        async def _emit(event: ResearchEvent) -> None:
            await queue.put(event)

        research_kwargs: dict = {
            "query": query,
            "emit": _emit,
            "model": model,
            "is_ollama": is_ollama,
            "locale": locale,
            "location": location,
        }
        if is_ollama:
            research_kwargs["ollama_url"] = ollama_url
        else:
            research_kwargs["api_key"] = api_key

        task = asyncio.create_task(run_deep_research(**research_kwargs))

        def _relay(event: ResearchEvent) -> str | None:
            t = event.type
            if t in ("content", "reasoning", "error", "finish"):
                return sse_event(t, event.data)
            if t == "status":
                return sse_event("research_status", event.data)
            if t == "usage":
                return sse_event("usage", event.data)
            if t in (
                "subagent_spawned",
                "subagent_progress",
                "subagent_result",
                "subagent_error",
            ):
                return sse_event(t, event.data)
            return None

        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=0.1)
                except asyncio.TimeoutError:
                    if task.done():
                        while not queue.empty():
                            event = queue.get_nowait()
                            relayed = _relay(event)
                            if relayed:
                                yield relayed
                        break
                    continue

                if event.type == "done":
                    break

                relayed = _relay(event)
                if relayed:
                    yield relayed

            if task.done() and task.exception():
                logger.error("Deep research task failed: %s", task.exception())
                yield sse_event("error", {"message": str(task.exception())})
        except Exception as e:
            logger.error("Deep research stream error: %s", e)
            yield sse_event("error", {"message": str(e)})

    async def cost_fetch(self, last_usage) -> None:
        """Fetch generation cost if not provided in stream."""
        await fetch_generation_cost(self.is_ollama, self.api_key, last_usage)


async def fetch_generation_cost(is_ollama: bool, api_key: str, last_usage) -> None:
    """Fetch generation cost from OpenRouter if not already in stream."""
    if is_ollama:
        return
    if isinstance(last_usage, dict):
        gen_id = last_usage.get("generation_id")
        has_cost = last_usage.get("cost")
    else:
        gen_id = getattr(last_usage, "generation_id", None)
        has_cost = getattr(last_usage, "cost", None)
    if not last_usage or not gen_id or has_cost:
        return
    try:
        gen = await openrouter.get_generation(gen_id, api_key)
        if gen:
            if isinstance(last_usage, dict):
                last_usage["cost"] = gen.get("total_cost", 0.0) or 0.0
                if gen.get("native_tokens_prompt"):
                    last_usage["prompt_tokens"] = last_usage.get("prompt_tokens") or gen["native_tokens_prompt"]
                if gen.get("native_tokens_completion"):
                    last_usage["completion_tokens"] = last_usage.get("completion_tokens") or gen["native_tokens_completion"]
                last_usage["cached_tokens"] = last_usage.get("cached_tokens") or gen.get("native_tokens_cached", 0)
                last_usage["provider"] = last_usage.get("provider") or gen.get("provider_name", "")
            else:
                last_usage.cost = gen.get("total_cost", 0.0) or 0.0
                if gen.get("native_tokens_prompt"):
                    last_usage.prompt_tokens = last_usage.prompt_tokens or gen["native_tokens_prompt"]
                if gen.get("native_tokens_completion"):
                    last_usage.completion_tokens = last_usage.completion_tokens or gen["native_tokens_completion"]
                last_usage.cached_tokens = last_usage.cached_tokens or gen.get("native_tokens_cached", 0)
                last_usage.provider = last_usage.provider or gen.get("provider_name", "")
    except Exception:
        pass