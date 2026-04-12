"""Deep Research orchestrator.

The main agent ("coordinator") streams a tool-using conversation with the
model. Instead of calling search/read tools directly, it spawns **sub-agents**
via `spawn_search_agent`, `spawn_sandbox_agent`, and `spawn_artifact_agent`.
Each spawn returns a ``task_id`` immediately; sub-agents run as
``asyncio.Task`` objects and push their results into a shared queue. The
coordinator blocks on ``wait_for_any_result`` to consume the next finished
sub-agent — but can keep spawning new ones mid-wait, so parallel work is not
bounded by any particular sub-agent finishing first.

Sub-agents receive a narrow tool list (``SEARCH_TOOLS`` / ``SANDBOX_TOOLS``)
and do **not** get the ``spawn_*`` tools — this is the recursion guard. They
cannot spawn grand-children; if they try, the dispatcher returns
``{"error": "unknown tool"}``.
"""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from quip.providers import openrouter, ollama
from quip.providers.openrouter import UsageInfo
from quip.services.skills import get_skill
from quip.services.tools import (
    LOAD_SKILL_TOOL,
    SEARCH_TOOLS,
    SANDBOX_TOOLS,
    AccumulatedToolCall,
    accumulate_tool_calls,
    execute_tool_call,
)
from quip.services.sandbox import sandbox_manager

logger = logging.getLogger(__name__)


# --- Orchestrator limits ---
ORCHESTRATOR_MAX_ROUNDS = 20
SUB_AGENT_MAX_ROUNDS = 15
SESSION_WEB_SEARCH_BUDGET = 100


# --- Spawn tool specs ---

SPAWN_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_search_agent",
        "description": (
            "Launch a search sub-agent to research a goal. Returns a task_id immediately; "
            "the sub-agent runs in parallel and pushes its result into the shared queue. "
            "Use wait_for_any_result to consume results as they arrive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The research goal in one or two sentences.",
                },
                "max_queries": {
                    "type": "integer",
                    "default": 30,
                    "description": "Soft budget for web_search calls inside this sub-agent.",
                },
            },
            "required": ["goal"],
        },
    },
}

SPAWN_SANDBOX_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_sandbox_agent",
        "description": (
            "Launch a sandbox sub-agent to run code / build charts / process data. "
            "Returns a task_id immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What the sub-agent should compute or produce, including any input values.",
                },
            },
            "required": ["task"],
        },
    },
}

SPAWN_ARTIFACT_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_artifact_agent",
        "description": (
            "Launch a single-turn artifact sub-agent that renders a plot / chart / table / "
            "mermaid / svg / html artifact from a short spec. Returns the artifact tag as the result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["plot", "chart", "table", "mermaid", "svg", "html", "code"],
                    "description": "Artifact type.",
                },
                "spec": {
                    "type": "string",
                    "description": "Plain-language or structured spec describing what to render.",
                },
            },
            "required": ["kind", "spec"],
        },
    },
}

WAIT_FOR_ANY_RESULT_TOOL = {
    "type": "function",
    "function": {
        "name": "wait_for_any_result",
        "description": (
            "Block until the next pending sub-agent finishes and return its result. "
            "Does not block the event loop."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

COLLECT_AGENT_RESULT_TOOL = {
    "type": "function",
    "function": {
        "name": "collect_agent_result",
        "description": "Non-blocking snapshot of a specific sub-agent's status and result.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
}

LIST_AGENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_agents",
        "description": "List all sub-agents in this research session with their status.",
        "parameters": {"type": "object", "properties": {}},
    },
}

ORCHESTRATOR_TOOLS = [
    LOAD_SKILL_TOOL,
    SPAWN_SEARCH_TOOL,
    SPAWN_SANDBOX_TOOL,
    SPAWN_ARTIFACT_TOOL,
    WAIT_FOR_ANY_RESULT_TOOL,
    COLLECT_AGENT_RESULT_TOOL,
    LIST_AGENTS_TOOL,
]


# --- Events ---

@dataclass
class ResearchEvent:
    """Queued event — either a status update or a content chunk."""
    type: str
    data: dict = field(default_factory=dict)


StatusCallback = Callable[[ResearchEvent], Awaitable[None]]


# --- Session state ---

@dataclass
class SubAgentHandle:
    task_id: str
    kind: str  # "search" | "sandbox" | "artifact"
    task: asyncio.Task
    status: str = "running"  # running | done | error | cancelled
    result: Optional[dict] = None
    usage: Optional[UsageInfo] = None
    started_at: float = field(default_factory=time.monotonic)


@dataclass
class ResearchSession:
    query: str
    emit: StatusCallback
    model: str
    is_ollama: bool
    api_key: str
    ollama_url: str
    locale: Optional[str] = None
    location: Optional[str] = None

    handles: dict[str, SubAgentHandle] = field(default_factory=dict)
    result_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_scope: asyncio.Event = field(default_factory=asyncio.Event)
    total_usage: UsageInfo = field(default_factory=UsageInfo)
    subagent_generations: list[str] = field(default_factory=list)
    web_search_count: int = 0
    loaded_skills: set[str] = field(default_factory=set)

    def next_task_id(self, kind: str) -> str:
        return f"{kind}-{uuid.uuid4().hex[:8]}"

    def add_usage(self, u: Optional[UsageInfo]) -> None:
        if not u:
            return
        self.total_usage.prompt_tokens += u.prompt_tokens
        self.total_usage.completion_tokens += u.completion_tokens
        self.total_usage.cached_tokens += u.cached_tokens
        self.total_usage.cost += u.cost or 0.0
        if u.generation_id:
            self.subagent_generations.append(u.generation_id)
        if u.provider and not self.total_usage.provider:
            self.total_usage.provider = u.provider


# --- Helpers ---

async def _stream(session: ResearchSession, messages: list[dict], tools: Optional[list[dict]]):
    """Provider-agnostic streaming wrapper."""
    if session.is_ollama:
        ollama_model = session.model.removeprefix("ollama/")
        return ollama.stream_completion(
            messages=messages, model=ollama_model, base_url=session.ollama_url, tools=tools,
        )
    return openrouter.stream_completion(
        messages=messages, model=session.model, api_key=session.api_key, tools=tools,
    )


def _build_runtime_header(session: ResearchSession) -> str:
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
    session: ResearchSession,
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
            tools=[LOAD_SKILL_TOOL] + SEARCH_TOOLS,
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


# --- Research tool dispatcher ---

async def execute_research_tool(session: ResearchSession, name: str, arguments_json: str) -> str:
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return json.dumps({"error": f"invalid JSON arguments: {arguments_json[:200]}"})

    if name == "load_skill":
        skill = get_skill(args.get("name", ""))
        if not skill:
            return json.dumps({"error": f"unknown skill: {args.get('name', '')}"})
        if args.get("name") in session.loaded_skills:
            return json.dumps({"skill": skill.name, "already_loaded": True})
        session.loaded_skills.add(skill.name)
        return json.dumps({"skill": skill.name, "instructions": skill.body})

    if name == "spawn_search_agent":
        goal = args.get("goal", "")
        if not goal:
            return json.dumps({"error": "goal required"})
        tid = session.next_task_id("search")
        task = asyncio.create_task(
            _run_search_sub_agent(session, tid, goal, int(args.get("max_queries", 30)))
        )
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="search", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "search", "goal": goal,
        }))
        return json.dumps({"task_id": tid, "status": "running"})

    if name == "spawn_sandbox_agent":
        task_desc = args.get("task", "")
        if not task_desc:
            return json.dumps({"error": "task required"})
        tid = session.next_task_id("sandbox")
        task = asyncio.create_task(_run_sandbox_sub_agent(session, tid, task_desc))
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="sandbox", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "sandbox", "task": task_desc,
        }))
        return json.dumps({"task_id": tid, "status": "running"})

    if name == "spawn_artifact_agent":
        kind = args.get("kind", "")
        spec = args.get("spec", "")
        if not kind or not spec:
            return json.dumps({"error": "kind and spec required"})
        tid = session.next_task_id("artifact")
        task = asyncio.create_task(_run_artifact_sub_agent(session, tid, kind, spec))
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="artifact", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "artifact", "artifact_kind": kind,
        }))
        return json.dumps({"task_id": tid, "status": "running"})

    if name == "wait_for_any_result":
        # Drop already-consumed items so we only return newly finished ones.
        pending = [h for h in session.handles.values() if h.status == "running"]
        if not pending and session.result_queue.empty():
            return json.dumps({"error": "no pending sub-agents"})
        task_id, result = await session.result_queue.get()
        status = session.handles[task_id].status if task_id in session.handles else "unknown"
        return json.dumps({"task_id": task_id, "status": status, "result": result})

    if name == "collect_agent_result":
        tid = args.get("task_id", "")
        h = session.handles.get(tid)
        if not h:
            return json.dumps({"error": f"unknown task_id: {tid}"})
        return json.dumps({"task_id": h.task_id, "status": h.status, "result": h.result})

    if name == "list_agents":
        return json.dumps({
            "agents": [
                {"task_id": h.task_id, "kind": h.kind, "status": h.status}
                for h in session.handles.values()
            ],
        })

    return json.dumps({"error": f"unknown orchestrator tool: {name}"})


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
