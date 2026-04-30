import asyncio
import json
import logging

from quip.services.research.types import ResearchEvent, ResearchSession, SubAgentHandle
from quip.services.research.sub_agents import (
    _run_artifact_sub_agent,
    _run_sandbox_sub_agent,
    _run_search_sub_agent,
)
from quip.services.skill_store import get_skill_def as get_skill

logger = logging.getLogger(__name__)


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
            "task_id": tid, "kind": "search", "agent_type": "search", "goal": goal,
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
            "task_id": tid, "kind": "sandbox", "agent_type": "sandbox", "task": task_desc,
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
            "task_id": tid, "kind": "artifact", "agent_type": "artifact", "artifact_kind": kind,
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
