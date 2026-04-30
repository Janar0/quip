import logging
from typing import Optional

from quip.services.research._stream_loop import _build_runtime_header, _stream
from quip.services.research.types import (
    ORCHESTRATOR_MAX_ROUNDS,
    ResearchEvent,
    ResearchSession,
    StatusCallback,
)
from quip.services.research.tools import ORCHESTRATOR_TOOLS
from quip.services.research.dispatcher import execute_research_tool
from quip.services.tools import AccumulatedToolCall, accumulate_tool_calls
from quip.services.skill_store import get_skill_def as get_skill

logger = logging.getLogger(__name__)


# --- Main orchestrator entry point ---

async def run_deep_research(
    query: str,
    emit: StatusCallback,
    model: str,
    api_key: str = "",
    is_ollama: bool = False,
    ollama_url: str = "",
    locale: Optional[str] = None,
    location: Optional[str] = None,
) -> None:
    """Run the deep research orchestrator.

    The main agent loops over rounds of ``stream_completion``, spawning
    sub-agents for searches, sandbox work, and artifact rendering. Content
    streamed by the main agent is forwarded as regular ``content`` events;
    sub-agent lifecycle is forwarded as ``subagent_*`` events.
    """
    session = ResearchSession(
        query=query,
        emit=emit,
        model=model,
        is_ollama=is_ollama,
        api_key=api_key,
        ollama_url=ollama_url,
        locale=locale,
        location=location,
    )

    coordinator = get_skill("deep_research_coordinator")
    coordinator_body = coordinator.body if coordinator else (
        "You are the Deep Research coordinator. Use spawn_* tools to launch sub-agents in parallel, "
        "then call wait_for_any_result to consume results as they arrive. You can spawn more agents "
        "at any time, including between waits. Write the final answer once all needed results are collected."
    )

    system_prompt = (
        coordinator_body
        + "\n\n"
        + _build_runtime_header(session)
    )

    messages: list[dict] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": query},
    ]

    try:
        for _round in range(ORCHESTRATOR_MAX_ROUNDS):
            if session.cancel_scope.is_set():
                break

            round_content = ""
            accumulated: list[AccumulatedToolCall] = []
            finish_reason: Optional[str] = None

            stream = await _stream(session, messages, ORCHESTRATOR_TOOLS)
            async for chunk in stream:
                if session.cancel_scope.is_set():
                    break
                if chunk.error:
                    await emit(ResearchEvent("error", {"message": chunk.error}))
                    return
                if chunk.reasoning:
                    await emit(ResearchEvent("reasoning", {"text": chunk.reasoning}))
                if chunk.content:
                    round_content += chunk.content
                    await emit(ResearchEvent("content", {"text": chunk.content}))
                if chunk.tool_calls:
                    accumulate_tool_calls(accumulated, chunk.tool_calls)
                if chunk.usage:
                    session.add_usage(chunk.usage)
                if chunk.finish_reason:
                    finish_reason = chunk.finish_reason
                    break

            if not accumulated:
                break

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

            for tc in accumulated:
                result_str = await execute_research_tool(
                    session, tc.function_name, tc.function_arguments
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Final usage event so the SSE handler can persist it.
        await emit(ResearchEvent("usage", {
            "prompt_tokens": session.total_usage.prompt_tokens,
            "completion_tokens": session.total_usage.completion_tokens,
            "cached_tokens": session.total_usage.cached_tokens,
            "cost": session.total_usage.cost,
            "provider": session.total_usage.provider,
            "generation_id": session.total_usage.generation_id,
            "subagent_generations": list(session.subagent_generations),
        }))
    finally:
        # Cancel any still-running sub-agents on exit.
        session.cancel_scope.set()
        for h in session.handles.values():
            if h.status == "running" and not h.task.done():
                h.task.cancel()
                h.status = "cancelled"
        await emit(ResearchEvent("done", {}))
