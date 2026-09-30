"""End-to-end mocked coverage for deterministic search sources and budgets."""
import base64
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest

from quip.core.config import set_setting
from quip.providers.openrouter import StreamChunk, ToolCallDelta, UsageInfo
from quip.services.search import SearchResponse, SearchResult


def _configure_search_completion():
    set_setting("openrouter_api_key", "test-key")
    set_setting("search_enabled", "true")
    set_setting("search_provider", "tavily")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")


def _event_payloads(body: str, event_name: str) -> list[dict]:
    payloads = []
    for frame in body.split("\n\n"):
        lines = frame.splitlines()
        if not lines or lines[0] != f"event: {event_name}":
            continue
        data = next((line[6:] for line in lines[1:] if line.startswith("data: ")), None)
        if data is not None:
            payloads.append(json.loads(data))
    return payloads


def _save_with_request_session():
    from quip.database import get_db
    from quip.main import app

    db_override = app.dependency_overrides[get_db]

    @asynccontextmanager
    async def save_session():
        session_generator = db_override()
        try:
            yield await anext(session_generator)
        finally:
            await session_generator.aclose()

    return save_session


@pytest.mark.asyncio
async def test_search_mode_caps_tool_calls_and_persists_deduplicated_retrieved_sources(
    client, auth_headers
):
    _configure_search_completion()
    requested_tools = [
        ("web_search", {"query": f"search angle {n}"}) for n in range(1, 7)
    ] + [
        ("read_url", {"url": f"https://example.test/page-{n}"}) for n in range(1, 4)
    ]
    malicious_source_title = (
        '[click](https://evil.example) <img src=x onerror=alert(1)> \\ **bold**'
    )
    title_token = base64.urlsafe_b64encode(
        malicious_source_title.encode("utf-8")
    ).decode("ascii").rstrip("=")
    answer = (
        "## Answer\nThe result is supported by [1]. "
        "Keep this ordinary link: https://support.example.test/guide.\n\n"
        "```md\n## Sources\n[1] Code example - https://code.example.test/reference\n```\n\n"
        "## Sources\n[1] Invented page - https://evil.example.test/fake\n\n"
        "This trailing explanation must remain after the invented source is removed."
    )
    provider_calls = 0
    provider_tools = []

    async def mock_stream(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        provider_tools.append(kwargs.get("tools") or [])
        if provider_calls == 1:
            yield StreamChunk(tool_calls=[
                ToolCallDelta(
                    index=index,
                    id=f"tool-{index}",
                    function_name=name,
                    function_arguments=json.dumps(arguments),
                )
                for index, (name, arguments) in enumerate(requested_tools)
            ])
            yield StreamChunk(finish_reason="tool_calls")
        else:
            yield StreamChunk(content=answer)
            yield StreamChunk(finish_reason="stop")
            yield StreamChunk(
                usage=UsageInfo(
                    prompt_tokens=50, completion_tokens=10, cost=0.001
                )
            )

    search_response = SearchResponse(
        [
            SearchResult(
                title=malicious_source_title,
                url="https://Example.com/source#section",
                snippet="Retrieved evidence",
            ),
            SearchResult(
                title="Duplicate page",
                url="https://example.com:443/source",
                snippet="Duplicate retrieval",
            ),
            SearchResult(
                title="Unsafe protocol",
                url="javascript:alert(1)",
                snippet="Must not become a source",
            ),
            SearchResult(
                title="Malformed URL",
                url="https:///missing-host",
                snippet="Must not become a source",
            ),
            SearchResult(
                title="",
                url="https://second.example.test/docs",
                snippet="Second retrieved source",
            ),
        ],
        [],
        warning="Image lookup was unavailable.",
    )
    mock_search = AsyncMock(return_value=search_response)
    mock_page_read = AsyncMock(return_value="Page text")
    save_session = _save_with_request_session()

    with patch(
        "quip.services.completion.stream.openrouter.stream_completion",
        new=mock_stream,
    ), patch("quip.services.search.web_search", new=mock_search), patch(
        "quip.services.scraper._jina_reader", new=mock_page_read
    ), patch(
        "quip.services.messages_persist.async_session", new=save_session
    ):
        response = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={
                "model": "google/gemini-2.0-flash-001",
                "message": "Search current sources",
                "mode_hint": "search",
            },
        )

    assert response.status_code == 200
    assert provider_calls == 2
    assert provider_tools[1] == []
    assert mock_search.await_count == 5
    assert mock_page_read.await_count == 2

    chat_id = _event_payloads(response.text, "chat")[0]["chat_id"]
    content_events = _event_payloads(response.text, "content")
    streamed_answer = "".join(event["text"] for event in content_events)
    assert "The result is supported by [1]" in streamed_answer
    assert "https://support.example.test/guide" in streamed_answer
    assert "https://evil.example.test/fake" not in streamed_answer
    assert "javascript:alert(1)" not in streamed_answer
    assert "This trailing explanation must remain" in streamed_answer
    assert "## Sources\n[1] Code example - https://code.example.test/reference" in streamed_answer
    assert streamed_answer.count("**Sources:**") == 1
    assert f"[1] quip-source-v1:{title_token} - https://Example.com/source#section" in streamed_answer
    assert "[2] quip-source-v1:c2Vjb25kLmV4YW1wbGUudGVzdA - https://second.example.test/docs" in streamed_answer
    assert streamed_answer.count("quip-source-v1:") == 2

    tool_events = _event_payloads(response.text, "tool_result")
    assert len(tool_events) == 9
    assert sum(event["status"] == "completed" for event in tool_events) == 7
    assert sum(event["status"] == "error" for event in tool_events) == 2

    saved = await client.get(f"/api/chats/{chat_id}", headers=auth_headers)
    assert saved.status_code == 200
    assistant = next(
        message for message in saved.json()["messages"]
        if message["role"] == "assistant"
    )
    assert assistant["content"] == streamed_answer
    assert assistant["content"].count("**Sources:**") == 1
    assert "https://evil.example.test/fake" not in assistant["content"]
    assert "This trailing explanation must remain" in assistant["content"]
    assert len(assistant["tool_calls"]) == 9
    search_calls = [
        call for call in assistant["tool_calls"] if call["name"] == "web_search"
    ]
    read_calls = [
        call for call in assistant["tool_calls"] if call["name"] == "read_url"
    ]
    assert sum(call["status"] == "completed" for call in search_calls) == 5
    assert sum(call["status"] == "completed" for call in read_calls) == 2
    assert sum(call["status"] == "error" for call in search_calls) == 1
    assert sum(call["status"] == "error" for call in read_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("search_response", "tool_status"),
    [
        (SearchResponse([], [], error="Tavily search is unavailable."), "error"),
        (SearchResponse([], []), "completed"),
    ],
    ids=["error", "no-results"],
)
async def test_search_error_removes_model_authored_sources_when_no_real_sources_exist(
    client, auth_headers, search_response, tool_status
):
    _configure_search_completion()
    provider_calls = 0
    answer = (
        "Search was unavailable, so I could not verify current information.\n\n"
        "**Sources:**\n[1] Invented page - https://evil.example.test/fake\n\n"
        "This ordinary explanation must remain. Keep this link: https://support.example.test/guide."
    )

    async def mock_stream(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls == 1:
            yield StreamChunk(tool_calls=[
                ToolCallDelta(
                    index=0,
                    id="failed-search",
                    function_name="web_search",
                    function_arguments=json.dumps({"query": "current information"}),
                )
            ])
            yield StreamChunk(finish_reason="tool_calls")
        else:
            yield StreamChunk(content=answer)
            yield StreamChunk(finish_reason="stop")
            yield StreamChunk(
                usage=UsageInfo(
                    prompt_tokens=30, completion_tokens=10, cost=0.001
                )
            )

    mock_search = AsyncMock(return_value=search_response)
    save_session = _save_with_request_session()

    with patch(
        "quip.services.completion.stream.openrouter.stream_completion",
        new=mock_stream,
    ), patch("quip.services.search.web_search", new=mock_search), patch(
        "quip.services.messages_persist.async_session", new=save_session
    ):
        response = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={
                "model": "google/gemini-2.0-flash-001",
                "message": "Find a current source",
                "mode_hint": "search",
            },
        )

    assert response.status_code == 200
    streamed_answer = "".join(
        event["text"] for event in _event_payloads(response.text, "content")
    )
    assert "Search was unavailable" in streamed_answer
    assert "Sources" not in streamed_answer
    assert "https://evil.example.test/fake" not in streamed_answer
    assert "This ordinary explanation must remain." in streamed_answer
    assert "https://support.example.test/guide" in streamed_answer

    chat_id = _event_payloads(response.text, "chat")[0]["chat_id"]
    saved = await client.get(f"/api/chats/{chat_id}", headers=auth_headers)
    assistant = next(
        message for message in saved.json()["messages"]
        if message["role"] == "assistant"
    )
    assert assistant["content"] == streamed_answer
    assert "Sources" not in assistant["content"]
    assert assistant["tool_calls"][0]["status"] == tool_status
    expected_result_status = "error" if search_response.error else "no_results"
    assert assistant["tool_calls"][0]["result"]["status"] == expected_result_status


@pytest.mark.asyncio
async def test_ordinary_chat_keeps_its_authored_sources_content_unchanged(
    client, auth_headers
):
    _configure_search_completion()
    answer = (
        "Regular answer with https://docs.example.test/reference.\n\n"
        "---\n**Sources:**\n"
        "[1] User-provided reference - https://docs.example.test/reference"
    )

    async def mock_stream(**kwargs):
        yield StreamChunk(content=answer)
        yield StreamChunk(finish_reason="stop")
        yield StreamChunk(
            usage=UsageInfo(prompt_tokens=20, completion_tokens=8, cost=0.001)
        )

    with patch(
        "quip.services.completion.stream.openrouter.stream_completion",
        new=mock_stream,
    ):
        response = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={
                "model": "google/gemini-2.0-flash-001",
                "message": "Summarize my reference",
            },
        )

    assert response.status_code == 200
    streamed_answer = "".join(
        event["text"] for event in _event_payloads(response.text, "content")
    )
    assert streamed_answer == answer
