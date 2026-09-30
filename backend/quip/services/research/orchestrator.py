import asyncio
import logging
import re
from typing import Optional

from quip.services.research._stream_loop import _build_runtime_header, _stream
from quip.services.research.types import (
    ResearchEvent,
    ResearchLimitReached,
    ResearchSession,
    StatusCallback,
)
from quip.services.research.limits import ResearchLimits
from quip.services.research.tools import ORCHESTRATOR_TOOLS
from quip.services.research.dispatcher import execute_research_tool
from quip.services.tools import AccumulatedToolCall, accumulate_tool_calls
from quip.services.skill_store import get_skill_def as get_skill

logger = logging.getLogger(__name__)

_ARTIFACT_RE = re.compile(r"<artifact[^>]*>[\s\S]*?</artifact>")

def _extract_artifacts(content: str) -> list[str]:
    """Return list of artifact tag blocks found in content."""
    return _ARTIFACT_RE.findall(content)


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
    cancel_event=None,
    limits: ResearchLimits | None = None,
    steering_reader=None,
) -> None:
    """Run the deep research orchestrator.

    The main agent loops over rounds of ``stream_completion``, spawning
    sub-agents for searches, sandbox work, and artifact rendering. Content
    streamed by the main agent is forwarded as regular ``content`` events;
    sub-agent lifecycle is forwarded as ``subagent_*`` events.
    """
    limits = limits or ResearchLimits.from_config()
    session = ResearchSession(
        query=query,
        emit=emit,
        model=model,
        is_ollama=is_ollama,
        api_key=api_key,
        ollama_url=ollama_url,
        locale=locale,
        location=location,
        max_child_agents=limits.max_child_agents,
        max_concurrent_agents=limits.max_concurrent_agents,
        max_runtime_seconds=limits.max_runtime_seconds,
        max_cost_usd=limits.max_cost_usd,
        max_orchestrator_rounds=limits.max_orchestrator_rounds,
        max_subagent_rounds=limits.max_subagent_rounds,
        max_web_searches=limits.max_web_searches,
        steering_reader=steering_reader,
    )
    if cancel_event is not None:
        session.cancel_scope = cancel_event
    await emit(ResearchEvent("status", {
        "phase": "decomposing",
        "detail": "Analyzing question for research plan..."
    }))

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
        for _round in range(session.max_orchestrator_rounds):
            if session.cancel_scope.is_set():
                break

            if session.steering_reader:
                for item in await session.steering_reader():
                    instruction = str(item.get("instruction", "")).strip()[:2000]
                    if instruction:
                        messages.append({
                            "role": "user",
                            "content": "Additional user direction for this research task: " + instruction,
                        })
                        await emit(ResearchEvent("steering_applied", {"id": item.get("id")}))

            round_content = ""
            accumulated: list[AccumulatedToolCall] = []
            async with session.admit_provider_call():
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
                        for art in _extract_artifacts(chunk.content):
                            await emit(ResearchEvent("artifact", {"tag": art}))
                    if chunk.tool_calls:
                        accumulate_tool_calls(accumulated, chunk.tool_calls)
                    if chunk.usage:
                        session.add_usage(chunk.usage)
                    if chunk.finish_reason:
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
                if session.cancel_scope.is_set():
                    break
                result_str = await execute_research_tool(
                    session, tc.function_name, tc.function_arguments
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

        # Force one final synthesis round if the last message was a tool result
        # (LLM may have gotten stuck calling wait_for_any_result after all agents done).
        if messages and messages[-1]["role"] == "tool" and session.handles:
            alive = [h for h in session.handles.values() if h.status == "running"]
            if not alive:
                messages.append({
                    "role": "user",
                    "content": (
                        "FINAL INSTRUCTION: All sub-agents have completed. You have all the results above. "
                        "The user's original question was: " + query + "\n\n"
                        "You MUST now write the final answer. Do NOT call any tools — "
                        "tools are disabled for this round. Write a comprehensive answer "
                        "based on the sub-agent results, with inline citations and a Sources section."
                    ),
                })
                await emit(ResearchEvent("status", {
                    "phase": "synthesizing",
                    "detail": "Writing the final research report..."
                }))
                # Disable tools so the model CANNOT call wait_for_any_result again
                async with session.admit_provider_call():
                    stream = await _stream(session, messages, [])
                    async for chunk in stream:
                        if chunk.error:
                            await emit(ResearchEvent("error", {"message": chunk.error}))
                            break
                        if chunk.content:
                            await emit(ResearchEvent("content", {"text": chunk.content}))
                            for art in _extract_artifacts(chunk.content):
                                await emit(ResearchEvent("artifact", {"tag": art}))
                        if chunk.reasoning:
                            await emit(ResearchEvent("reasoning", {"text": chunk.reasoning}))
                        if chunk.usage:
                            session.add_usage(chunk.usage)

    except ResearchLimitReached as exc:
        await emit(ResearchEvent("error", {"message": str(exc)}))
    finally:
        # Aggregate usage is persisted by the task manager, once per ChatRun.
        await emit(ResearchEvent("usage", {
            "prompt_tokens": session.total_usage.prompt_tokens,
            "completion_tokens": session.total_usage.completion_tokens,
            "cached_tokens": session.total_usage.cached_tokens,
            "cost": session.total_usage.cost,
            "provider": session.total_usage.provider,
            "generation_id": session.total_usage.generation_id,
            "subagent_generations": list(session.subagent_generations),
        }))
        # Cancel any still-running sub-agents on exit.
        session.cancel_scope.set()
        children = []
        for h in session.handles.values():
            if h.status == "running" and not h.task.done():
                h.task.cancel()
                h.status = "cancelled"
                children.append(h.task)
        if children:
            await asyncio.gather(*children, return_exceptions=True)
        await emit(ResearchEvent("done", {}))
