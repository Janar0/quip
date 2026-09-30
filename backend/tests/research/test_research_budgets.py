import asyncio
import json

import pytest

from quip.providers.types import StreamChunk, ToolCallDelta, UsageInfo
from quip.services.research import _stream_loop, dispatcher, orchestrator, sub_agents
from quip.services.research.limits import ResearchLimits
from quip.services.research.types import ResearchLimitReached, ResearchSession, SubAgentHandle


async def _collect(_event):
    return None


@pytest.mark.asyncio
async def test_child_spawn_cap_prevents_more_subagent_tasks(monkeypatch):
    session = ResearchSession(
        query="q",
        emit=_collect,
        model="mock",
        is_ollama=False,
        api_key="",
        ollama_url="",
        max_child_agents=1,
    )

    async def fake_search(session, task_id, goal, max_queries):
        session.handles[task_id].status = "done"

    monkeypatch.setattr(dispatcher, "_run_search_sub_agent", fake_search)
    first = json.loads(await dispatcher.execute_research_tool(
        session, "spawn_search_agent", '{"goal":"first"}'
    ))
    second = json.loads(await dispatcher.execute_research_tool(
        session, "spawn_search_agent", '{"goal":"second"}'
    ))
    await asyncio.gather(*(h.task for h in session.handles.values()))

    assert first["status"] == "running"
    assert second["error"] == "research child-agent limit exhausted"
    assert len(session.handles) == 1


@pytest.mark.asyncio
async def test_cost_limit_blocks_provider_call(monkeypatch):
    session = ResearchSession(
        query="q",
        emit=_collect,
        model="mock",
        is_ollama=False,
        api_key="",
        ollama_url="",
        max_cost_usd=0,
    )
    calls = 0

    def stream_completion(**_kwargs):
        nonlocal calls
        calls += 1
        async def empty_stream():
            if False:
                yield None
        return empty_stream()

    monkeypatch.setattr(_stream_loop.openrouter, "stream_completion", stream_completion)
    with pytest.raises(ResearchLimitReached, match="cost limit"):
        await _stream_loop._stream(session, [], [])
    assert calls == 0


@pytest.mark.asyncio
async def test_cancel_blocks_new_provider_calls(monkeypatch):
    session = ResearchSession(
        query="q",
        emit=_collect,
        model="mock",
        is_ollama=False,
        api_key="",
        ollama_url="",
    )
    session.cancel_scope.set()
    calls = 0

    def stream_completion(**_kwargs):
        nonlocal calls
        calls += 1
        async def empty_stream():
            if False:
                yield None
        return empty_stream()

    monkeypatch.setattr(_stream_loop.openrouter, "stream_completion", stream_completion)
    with pytest.raises(asyncio.CancelledError):
        await _stream_loop._stream(session, [], [])
    assert calls == 0


@pytest.mark.asyncio
async def test_parallel_provider_calls_are_admitted_against_updated_known_cost(monkeypatch):
    session = ResearchSession(
        query="q", emit=_collect, model="mock", is_ollama=False, api_key="", ollama_url="",
        max_cost_usd=1.0,
    )
    session.total_usage.cost = 0.95
    provider_calls = 0

    def fake_stream_completion(**_kwargs):
        nonlocal provider_calls
        provider_calls += 1

        async def stream():
            await asyncio.sleep(0)
            yield StreamChunk(usage=UsageInfo(cost=0.10), finish_reason="stop")

        return stream()

    monkeypatch.setattr(_stream_loop.openrouter, "stream_completion", fake_stream_completion)
    outcomes = await asyncio.gather(*(
        sub_agents._run_sub_stream_loop(
            session, f"agent-{index}", "system", "goal", [], 1, "subagent_progress",
        )
        for index in range(3)
    ), return_exceptions=True)

    assert provider_calls == 1
    assert session.total_usage.cost == pytest.approx(1.05)
    assert sum(isinstance(result, ResearchLimitReached) for result in outcomes) == 2


@pytest.mark.asyncio
async def test_orchestrator_uses_configured_round_limit(monkeypatch):
    provider_calls = 0

    async def fake_stream(_session, _messages, _tools):
        nonlocal provider_calls
        provider_calls += 1

        async def stream():
            yield StreamChunk(
                tool_calls=[ToolCallDelta(id=f"call-{provider_calls}", function_name="list_agents", function_arguments="{}")],
                finish_reason="tool_calls",
            )

        return stream()

    monkeypatch.setattr(orchestrator, "_stream", fake_stream)
    await orchestrator.run_deep_research(
        "q", _collect, "mock", limits=ResearchLimits(max_orchestrator_rounds=2),
    )

    assert provider_calls == 2


@pytest.mark.asyncio
async def test_search_subagent_uses_configured_session_search_budget(monkeypatch):
    session = ResearchSession(
        query="q", emit=_collect, model="mock", is_ollama=False, api_key="", ollama_url="",
        max_web_searches=1,
    )
    task = asyncio.current_task()
    assert task is not None
    session.handles["search-test"] = SubAgentHandle(task_id="search-test", kind="search", task=task)
    admissions = []

    async def fake_substream(
        _session, _task_id, _body, _goal, *, on_tool_call, **_kwargs,
    ):
        admissions.append(await on_tool_call("web_search", {}))
        admissions.append(await on_tool_call("web_search", {}))
        return "{}", UsageInfo()

    monkeypatch.setattr(sub_agents, "_run_sub_stream_loop", fake_substream)
    await sub_agents._run_search_sub_agent(session, "search-test", "goal", max_queries=10)

    assert admissions[0] is None
    assert json.loads(admissions[1])["error"] == "session web_search budget exhausted"
    assert session.web_search_count == 1


@pytest.mark.asyncio
async def test_known_cost_exhaustion_prevents_starting_web_search(monkeypatch):
    session = ResearchSession(
        query="q", emit=_collect, model="mock", is_ollama=False, api_key="", ollama_url="",
        max_cost_usd=1.0,
    )
    session.total_usage.cost = 1.0
    task = asyncio.current_task()
    assert task is not None
    session.handles["search-test"] = SubAgentHandle(task_id="search-test", kind="search", task=task)
    admissions = []

    async def fake_substream(_session, _task_id, _body, _goal, *, on_tool_call, **_kwargs):
        admissions.append(await on_tool_call("web_search", {}))
        return "{}", UsageInfo()

    monkeypatch.setattr(sub_agents, "_run_sub_stream_loop", fake_substream)
    await sub_agents._run_search_sub_agent(session, "search-test", "goal", max_queries=10)

    assert json.loads(admissions[0])["error"] == "research known-cost limit reached"
    assert session.web_search_count == 0
