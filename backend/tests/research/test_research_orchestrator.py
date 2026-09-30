import asyncio

import pytest

from quip.providers.openrouter import StreamChunk, ToolCallDelta, UsageInfo
from quip.services.research import orchestrator
from quip.services.research.types import SubAgentHandle


async def _stream_chunks(*chunks: StreamChunk):
    for chunk in chunks:
        yield chunk


@pytest.mark.asyncio
async def test_final_synthesis_provider_error_is_reported_after_partial_text(monkeypatch):
    stream_calls = 0

    async def fake_stream(_session, _messages, tools):
        nonlocal stream_calls
        stream_calls += 1
        if stream_calls == 1:
            return _stream_chunks(
                StreamChunk(
                    tool_calls=[
                        ToolCallDelta(
                            index=0,
                            id="call-search",
                            function_name="spawn_search_agent",
                            function_arguments='{"goal":"research question"}',
                        )
                    ],
                    finish_reason="tool_calls",
                )
            )
        if tools:
            return _stream_chunks(StreamChunk(finish_reason="stop"))
        return _stream_chunks(
            StreamChunk(
                content="Partial report",
                usage=UsageInfo(prompt_tokens=7, completion_tokens=3, cost=0.02),
            ),
            StreamChunk(error="final synthesis provider failed"),
        )

    async def fake_execute(session, _name, _arguments):
        task = asyncio.create_task(asyncio.sleep(0))
        await task
        session.handles["search-test"] = SubAgentHandle(
            task_id="search-test",
            kind="search",
            task=task,
            status="done",
            result={"summary": "mock search result"},
        )
        return '{"task_id":"search-test","status":"done"}'

    events = []

    async def emit(event):
        events.append(event)

    monkeypatch.setattr(orchestrator, "_stream", fake_stream)
    monkeypatch.setattr(orchestrator, "execute_research_tool", fake_execute)
    monkeypatch.setattr(orchestrator, "get_skill", lambda _name: None)

    await orchestrator.run_deep_research("research question", emit, model="mock-model")

    assert [event.data["text"] for event in events if event.type == "content"] == ["Partial report"]
    assert [event.data["message"] for event in events if event.type == "error"] == ["final synthesis provider failed"]
    usage = next(event.data for event in events if event.type == "usage")
    assert usage["prompt_tokens"] == 7
    assert usage["completion_tokens"] == 3
    assert events[-1].type == "done"
    assert stream_calls == 3
