import asyncio
import json
import logging
from typing import Optional

from quip.providers.openrouter import UsageInfo
from quip.services.research._stream_loop import (
    _build_runtime_header,
    _run_sub_stream_loop,
    _stream,
)
from quip.services.research.types import (
    ResearchEvent,
    ResearchSession,
    SESSION_WEB_SEARCH_BUDGET,
    SUB_AGENT_MAX_ROUNDS,
)
from quip.services.tools import (
    LOAD_SKILL_TOOL,
    READ_URL_TOOL,
    SEARCH_TOOLS,
    SANDBOX_TOOLS,
)
from quip.services.skill_store import get_skill_def as get_skill

logger = logging.getLogger(__name__)


# --- Sub-agent runners ---

async def _run_search_sub_agent(
    session: ResearchSession,
    task_id: str,
    goal: str,
    max_queries: int,
) -> None:
    try:
        skill = get_skill("search_sub_agent")
        body = skill.body if skill else (
            "You are a search sub-agent. Use web_search and read_url to research the goal. "
            "Return a JSON object with 'summary' and 'sources' fields."
        )
        queries_used = 0

        async def _enforce_budget(name: str, args: dict) -> Optional[str]:
            nonlocal queries_used
            if name != "web_search":
                return None
            if session.web_search_count >= SESSION_WEB_SEARCH_BUDGET:
                return json.dumps({"error": "session web_search budget exhausted"})
            if queries_used >= max_queries:
                return json.dumps({"error": "sub-agent max_queries exhausted"})
            session.web_search_count += 1
            queries_used += 1
            return None

        content, usage = await _run_sub_stream_loop(
            session, task_id, body, goal,
            tools=[LOAD_SKILL_TOOL, READ_URL_TOOL] + SEARCH_TOOLS,
            max_rounds=SUB_AGENT_MAX_ROUNDS,
            progress_event_type="subagent_progress",
            on_tool_call=_enforce_budget,
        )
        result = {"summary": content, "queries_used": queries_used}
        session.handles[task_id].status = "done"
        session.handles[task_id].result = result
        session.handles[task_id].usage = usage
        session.add_usage(usage)
        await session.result_queue.put((task_id, result))
        await session.emit(ResearchEvent("subagent_result", {
            "task_id": task_id, "kind": "search", "result": result,
        }))
    except asyncio.CancelledError:
        session.handles[task_id].status = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("search sub-agent %s failed", task_id)
        session.handles[task_id].status = "error"
        session.handles[task_id].result = {"error": str(e)}
        await session.result_queue.put((task_id, {"error": str(e)}))
        await session.emit(ResearchEvent("subagent_error", {
            "task_id": task_id, "message": str(e),
        }))


async def _run_sandbox_sub_agent(
    session: ResearchSession,
    task_id: str,
    task_description: str,
) -> None:
    try:
        skill = get_skill("sandbox_sub_agent")
        body = skill.body if skill else (
            "You are a sandbox sub-agent. Use sandbox_execute and related tools to complete the task. "
            "Return the final result as JSON with 'summary' and any file paths."
        )
        content, usage = await _run_sub_stream_loop(
            session, task_id, body, task_description,
            tools=[LOAD_SKILL_TOOL] + SANDBOX_TOOLS,
            max_rounds=SUB_AGENT_MAX_ROUNDS,
            progress_event_type="subagent_progress",
        )
        result = {"summary": content}
        session.handles[task_id].status = "done"
        session.handles[task_id].result = result
        session.handles[task_id].usage = usage
        session.add_usage(usage)
        await session.result_queue.put((task_id, result))
        await session.emit(ResearchEvent("subagent_result", {
            "task_id": task_id, "kind": "sandbox", "result": result,
        }))
    except asyncio.CancelledError:
        session.handles[task_id].status = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("sandbox sub-agent %s failed", task_id)
        session.handles[task_id].status = "error"
        session.handles[task_id].result = {"error": str(e)}
        await session.result_queue.put((task_id, {"error": str(e)}))
        await session.emit(ResearchEvent("subagent_error", {
            "task_id": task_id, "message": str(e),
        }))


async def _run_artifact_sub_agent(
    session: ResearchSession,
    task_id: str,
    kind: str,
    spec: str,
) -> None:
    try:
        artifact_skill_name = f"artifact_{kind}"
        skill = get_skill(artifact_skill_name)
        sub_skill = get_skill("artifact_sub_agent")
        intro = sub_skill.body if sub_skill else (
            "You are an artifact sub-agent. Emit exactly one <artifact> tag that answers the spec. "
            "No prose before or after."
        )
        body = intro
        if skill:
            body = body + "\n\n" + skill.body
        messages = [
            {"role": "system", "content": body + "\n\n" + _build_runtime_header(session)},
            {"role": "user", "content": spec},
        ]

        full_content = ""
        sub_usage = UsageInfo()
        stream = await _stream(session, messages, None)
        async for chunk in stream:
            if session.cancel_scope.is_set():
                break
            if chunk.error:
                raise RuntimeError(chunk.error)
            if chunk.content:
                full_content += chunk.content
                await session.emit(ResearchEvent("subagent_progress", {
                    "task_id": task_id, "delta": chunk.content,
                }))
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

        result = {"artifact": full_content, "kind": kind}
        session.handles[task_id].status = "done"
        session.handles[task_id].result = result
        session.handles[task_id].usage = sub_usage
        session.add_usage(sub_usage)
        await session.result_queue.put((task_id, result))
        await session.emit(ResearchEvent("subagent_result", {
            "task_id": task_id, "kind": "artifact", "result": result,
        }))
    except asyncio.CancelledError:
        session.handles[task_id].status = "cancelled"
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("artifact sub-agent %s failed", task_id)
        session.handles[task_id].status = "error"
        session.handles[task_id].result = {"error": str(e)}
        await session.result_queue.put((task_id, {"error": str(e)}))
        await session.emit(ResearchEvent("subagent_error", {
            "task_id": task_id, "message": str(e),
        }))
