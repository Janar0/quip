import json
import logging
from typing import Awaitable, Callable, Optional

from quip.providers import openrouter, ollama
from quip.providers.openrouter import UsageInfo

from quip.services.tools import (
    AccumulatedToolCall,
    accumulate_tool_calls,
    execute_tool_call,
)
from quip.services.sandbox import sandbox_manager

logger = logging.getLogger(__name__)


async def _stream(session, messages, tools):
    """Provider-agnostic streaming wrapper."""
    if session.is_ollama:
        ollama_model = session.model.removeprefix("ollama/")
        return ollama.stream_completion(
            messages=messages, model=ollama_model, base_url=session.ollama_url, tools=tools,
        )
    return openrouter.stream_completion(
        messages=messages, model=session.model, api_key=session.api_key, tools=tools,
    )


def _build_runtime_header(session) -> str:
    from datetime import datetime, timezone
    lines = [f"Current date: {datetime.now(timezone.utc).date().isoformat()}."]
    if session.locale:
        lines.append(
            f"User interface language: {session.locale}. Answer in this language unless the user writes in another."
        )
    if session.location:
        lines.append(
            f"Approximate user location: {session.location}. Use local units, currency, and conventions when relevant."
        )
    return "\n".join(lines)


async def _run_sub_stream_loop(
    session,
    task_id: str,
    system_body: str,
    user_goal: str,
    tools: list[dict],
    max_rounds: int,
    progress_event_type: str,
    on_tool_call: Optional[Callable[[str, dict], Awaitable[Optional[str]]]] = None,
) -> tuple[str, UsageInfo]:
    """Run a nested stream_completion loop for a sub-agent.

    Streams content into ``progress_event_type`` SSE events so the UI can show
    per-sub-agent progress. Returns (full_content, usage). ``on_tool_call`` can
    intercept tool calls (e.g. to enforce the session web_search budget).
    """
    from quip.services.research.types import ResearchEvent

    messages = [
        {"role": "system", "content": system_body + "\n\n" + _build_runtime_header(session)},
        {"role": "user", "content": user_goal},
    ]
    full_content = ""
    sub_usage = UsageInfo()
    sandbox = None

    for _round in range(max_rounds):
        if session.cancel_scope.is_set():
            break

        round_content = ""
        accumulated: list[AccumulatedToolCall] = []

        stream = await _stream(session, messages, tools)
        async for chunk in stream:
            if session.cancel_scope.is_set():
                break
            if chunk.error:
                raise RuntimeError(chunk.error)
            if chunk.content:
                round_content += chunk.content
                await session.emit(ResearchEvent(progress_event_type, {
                    "task_id": task_id, "delta": chunk.content,
                }))
            if chunk.tool_calls:
                accumulate_tool_calls(accumulated, chunk.tool_calls)
            if chunk.usage:
                sub_usage.prompt_tokens += chunk.usage.prompt_tokens
                sub_usage.completion_tokens += chunk.usage.completion_tokens
                sub_usage.cached_tokens += chunk.usage.cached_tokens
                sub_usage.cost += chunk.usage.cost or 0.0
                if chunk.usage.generation_id:
                    sub_usage.generation_id = chunk.usage.generation_id
                if chunk.usage.provider:
                    sub_usage.provider = chunk.usage.provider
            if chunk.finish_reason:
                break

        full_content += round_content

        if not accumulated:
            break

        # Append the assistant turn with tool calls, then execute them.
        messages.append({
            "role": "assistant",
            "content": round_content or "",
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function_name, "arguments": tc.function_arguments},
                }
                for tc in accumulated
            ],
        })

        # Lazy sandbox init for sandbox sub-agents.
        _SANDBOX_TOOL_NAMES = {"sandbox_execute", "sandbox_install", "sandbox_write_file", "sandbox_read_file", "sandbox_list_files"}
        needs_sandbox = any(tc.function_name in _SANDBOX_TOOL_NAMES for tc in accumulated)

        for tc in accumulated:
            try:
                args = json.loads(tc.function_arguments) if tc.function_arguments else {}
            except json.JSONDecodeError:
                args = {}

            override: Optional[str] = None
            if on_tool_call is not None:
                override = await on_tool_call(tc.function_name, args)

            if override is not None:
                result_str = override
            else:
                if needs_sandbox and sandbox is None and sandbox_manager.available:
                    try:
                        from quip.database import async_session
                        async with async_session() as sandbox_db:
                            # Research sub-agent sandbox is keyed by task_id so it doesn't
                            # collide with the user's main chat sandbox.
                            sandbox = await sandbox_manager.get_or_create(0, sandbox_db)
                            await sandbox_manager.ensure_chat_dir(sandbox, task_id)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("research sub-agent sandbox init failed: %s", e)
                try:
                    result_str = await execute_tool_call(
                        sandbox_manager, sandbox, task_id,
                        tc.function_name, tc.function_arguments,
                        loaded_skills=session.loaded_skills,
                    )
                except Exception as e:  # noqa: BLE001
                    result_str = json.dumps({"error": f"{type(e).__name__}: {e}"})

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    return full_content, sub_usage
