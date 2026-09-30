import asyncio
import json
import logging

from quip.services.research.types import (
    ResearchEvent,
    ResearchLimitReached,
    ResearchSession,
    SubAgentHandle,
)
from quip.services.research.sub_agents import (
    _run_artifact_sub_agent,
    _run_sandbox_sub_agent,
    _run_search_sub_agent,
)
from quip.services.skill_store import get_skill_def as get_skill

logger = logging.getLogger(__name__)


def _spawn_bounded(session: ResearchSession, factory):
    async def run():
        async with session.child_slots:
            await factory()

    return asyncio.create_task(run())


async def _child_limit_error(session: ResearchSession) -> str | None:
    try:
        session.ensure_can_start_call()
    except ResearchLimitReached as exc:
        await session.emit(ResearchEvent("error", {"message": str(exc)}))
        return str(exc)
    if not session.reserve_child():
        message = "research child-agent limit exhausted"
        await session.emit(ResearchEvent("error", {"message": message}))
        return message
    return None


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
        limit_error = await _child_limit_error(session)
        if limit_error:
            return json.dumps({"error": limit_error})
        try:
            max_queries = int(args.get("max_queries", 30))
        except (TypeError, ValueError):
            max_queries = 30
        max_queries = max(1, min(max_queries, session.max_web_searches))
        tid = session.next_task_id("search")
        task = _spawn_bounded(session, lambda: _run_search_sub_agent(session, tid, goal, max_queries))
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="search", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "search", "agent_type": "search", "goal": goal,
        }))
        await session.emit(ResearchEvent("status", {
            "phase": "searching",
            "detail": "Searching web sources...",
            "sub_queries": [goal],
        }))
        return json.dumps({"task_id": tid, "status": "running"})

    if name == "spawn_sandbox_agent":
        task_desc = args.get("task", "")
        if not task_desc:
            return json.dumps({"error": "task required"})
        limit_error = await _child_limit_error(session)
        if limit_error:
            return json.dumps({"error": limit_error})
        tid = session.next_task_id("sandbox")
        task = _spawn_bounded(session, lambda: _run_sandbox_sub_agent(session, tid, task_desc))
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="sandbox", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "sandbox", "agent_type": "sandbox",
            "goal": task_desc,
        }))
        return json.dumps({"task_id": tid, "status": "running"})

    if name == "spawn_artifact_agent":
        kind = args.get("kind", "")
        spec = args.get("spec", "")
        if not kind or not spec:
            return json.dumps({"error": "kind and spec required"})
        limit_error = await _child_limit_error(session)
        if limit_error:
            return json.dumps({"error": limit_error})
        tid = session.next_task_id("artifact")
        task = _spawn_bounded(session, lambda: _run_artifact_sub_agent(session, tid, kind, spec))
        session.handles[tid] = SubAgentHandle(task_id=tid, kind="artifact", task=task)
        await session.emit(ResearchEvent("subagent_spawned", {
            "task_id": tid, "kind": "artifact", "agent_type": "artifact",
            "goal": f"{kind}: {spec[:80]}",
            "artifact_kind": kind,
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
