"""Research-specific worker adapter over the shared ChatRun manager."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from typing import Any

from quip.services.chat_runs import ChatRunManager, ChatRunSpec, RunExecutionContext, RunOutcome, read_run
from quip.services.research.limits import ResearchLimits
from quip.services.research.sources import validated_search_sources
from quip.services.research.types import ResearchEvent


@dataclass(frozen=True)
class ResearchRunSpec:
    run: ChatRunSpec
    query: str
    model: str
    api_key: str = ""
    is_ollama: bool = False
    ollama_url: str = ""
    locale: str | None = None
    location: str | None = None


ResearchRunner = Callable[..., Awaitable[Any]]


class ResearchRunManager:
    def __init__(
        self,
        task_manager: ChatRunManager,
        *,
        runner: ResearchRunner | None = None,
        limits: ResearchLimits | None = None,
    ):
        self.task_manager = task_manager
        self.runner = runner
        self.limits = limits or ResearchLimits.from_config()

    async def start(self, spec: ResearchRunSpec):
        run = replace(spec.run, timeout_seconds=self.limits.max_runtime_seconds)
        state: dict[str, Any] = {
            "progress": [],
            "subagents": {},
            "errors": [],
            "sources": [],
            "usage": {},
        }
        report_errors: list[str] = []

        async def worker(context: RunExecutionContext) -> RunOutcome:
            async def persist_snapshot(patch: dict[str, Any] | None = None) -> dict[str, Any]:
                await context.update_snapshot(**(patch if patch is not None else state))
                persisted = await read_run(
                    self.task_manager.session_factory,
                    run_id=run.run_id,
                    chat_id=run.chat_id,
                    user_id=run.user_id,
                )
                return persisted.get("snapshot", {}) if persisted else {}

            async def publish_snapshot(snapshot: dict[str, Any]) -> None:
                await context.emit({"type": "research_snapshot", "data": {"snapshot": snapshot}})

            initial_snapshot = await persist_snapshot()
            await publish_snapshot(initial_snapshot)

            async def emit(event: ResearchEvent) -> None:
                event_type, data = event.type, event.data or {}
                snapshot_changed = False
                snapshot_patch: dict[str, Any] = {}
                if event_type == "content":
                    await context.append_result(str(data.get("text") or ""))
                elif event_type == "status":
                    progress = list(state["progress"])
                    progress.append(
                        {
                            "phase": str(data.get("phase") or "working")[:80],
                            "detail": str(data.get("detail") or "")[:500],
                            "sub_queries": [str(q)[:500] for q in (data.get("sub_queries") or [])[:12]],
                            "sources_found": data.get("sources_found"),
                        }
                    )
                    state["progress"] = progress[-40:]
                    snapshot_changed = True
                    snapshot_patch = {"progress": state["progress"]}
                elif event_type == "subagent_spawned":
                    agents = dict(state["subagents"])
                    tid = str(data.get("task_id") or "")[:80]
                    if tid:
                        agents[tid] = {
                            "task_id": tid,
                            "kind": str(data.get("kind") or "agent")[:40],
                            "status": "running",
                            "goal": str(data.get("goal") or "")[:300],
                        }
                        state["subagents"] = dict(list(agents.items())[-8:])
                        snapshot_changed = True
                        snapshot_patch = {"subagents": state["subagents"]}
                elif event_type in {"subagent_result", "subagent_error"}:
                    agents = dict(state["subagents"])
                    tid = str(data.get("task_id") or "")[:80]
                    if tid and tid in agents:
                        agents[tid] = {**agents[tid], "status": "error" if event_type.endswith("error") else "done"}
                        state["subagents"] = agents
                        snapshot_changed = True
                        snapshot_patch = {"subagents": agents}
                    if event_type.endswith("error"):
                        message = str(data.get("message") or "A research agent failed")[:1000]
                        report_errors.append(message)
                        state["errors"] = (state["errors"] + [{"message": message}])[-20:]
                        snapshot_changed = True
                        snapshot_patch["errors"] = state["errors"]
                elif event_type == "sources":
                    existing = list(state["sources"])
                    seen = {source.get("url") for source in existing}
                    incoming = data.get("sources", [])
                    for source in incoming[:30] if isinstance(incoming, list) else []:
                        if isinstance(source, dict) and source.get("url") not in seen:
                            existing.append(source)
                            seen.add(source.get("url"))
                    state["sources"] = existing[:30]
                    snapshot_changed = True
                    snapshot_patch = {"sources": state["sources"]}
                elif event_type == "usage":
                    state["usage"] = {
                        key: data.get(key)
                        for key in (
                            "prompt_tokens",
                            "completion_tokens",
                            "cached_tokens",
                            "cost",
                            "provider",
                            "generation_id",
                            "subagent_generations",
                        )
                        if data.get(key) is not None
                    }
                    snapshot_changed = True
                    snapshot_patch = {"usage": state["usage"]}
                elif event_type == "error":
                    message = str(data.get("message") or "Research encountered an error")[:1000]
                    report_errors.append(message)
                    state["errors"] = (state["errors"] + [{"message": message}])[-20:]
                    snapshot_changed = True
                    snapshot_patch = {"errors": state["errors"]}

                snapshot = None
                if snapshot_changed:
                    snapshot = await persist_snapshot(snapshot_patch)
                    if event_type == "sources":
                        event = ResearchEvent("sources", {"sources": snapshot.get("sources", [])})
                    elif event_type == "status" and snapshot.get("progress"):
                        event = ResearchEvent("status", snapshot["progress"][-1])
                await context.emit(event)
                if snapshot is not None:
                    await publish_snapshot(snapshot)

            try:
                if self.runner is None:
                    from quip.services.research.orchestrator import run_deep_research

                    await run_deep_research(
                        query=spec.query,
                        emit=emit,
                        model=spec.model,
                        api_key=spec.api_key,
                        is_ollama=spec.is_ollama,
                        ollama_url=spec.ollama_url,
                        locale=spec.locale,
                        location=spec.location,
                        cancel_event=context.cancel_event,
                        limits=self.limits,
                        steering_reader=context.take_steering,
                    )
                else:
                    result = await self.runner(
                        context,
                        query=spec.query,
                        emit=emit,
                        model=spec.model,
                        limits=self.limits,
                    )
                    if isinstance(result, dict):
                        if result.get("error"):
                            report_errors.append(str(result["error"])[:1000])
                        if result.get("status") in {"partial", "failed"} and result.get("error"):
                            state["errors"] = (state["errors"] + [{"message": result["error"][:1000]}])[-20:]
                            await publish_snapshot(await persist_snapshot({"errors": state["errors"]}))
            except asyncio.CancelledError:
                context.final_outcome = RunOutcome(
                    status="cancelled",
                    usage=state["usage"] or None,
                    subagent_generations=state["usage"].get("subagent_generations", []),
                )
                raise
            except Exception as exc:  # noqa: BLE001
                message = str(exc)[:1000]
                report_errors.append(message)
                state["errors"] = (state["errors"] + [{"message": message}])[-20:]
                await publish_snapshot(await persist_snapshot({"errors": state["errors"]}))
                await context.emit({"type": "error", "data": {"message": message}})

            has_report = bool(context.report.strip())
            status = (
                "partial"
                if report_errors and has_report
                else "failed"
                if report_errors and not has_report
                else "completed"
            )
            return RunOutcome(
                status=status,
                error="; ".join(report_errors[:3])[:4000] if report_errors else None,
                usage=state["usage"] or None,
                subagent_generations=state["usage"].get("subagent_generations", []),
            )

        return await self.task_manager.start(run, worker)


def collect_search_sources(result_json: str) -> list[dict[str, str]]:
    return validated_search_sources(result_json)
