"""Tests for web search and scraper services."""

import json
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from quip.core.config import set_setting
from quip.services.scraper import read_url
from quip.services.search import SearchResponse, SearchResult, web_search

# ── Search provider tests ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tavily_search():
    """Tavily provider returns parsed SearchResults."""
    set_setting("search_provider", "tavily")
    set_setting("tavily_api_key", "test-key")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Python Docs", "url": "https://python.org", "content": "The official Python site."},
            {"title": "FastAPI", "url": "https://fastapi.tiangolo.com", "content": "Modern web framework."},
        ]
    }

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("python web framework", max_results=2)

    assert len(response.results) == 2
    assert response.results[0].title == "Python Docs"
    assert response.results[0].url == "https://python.org"
    assert response.results[1].title == "FastAPI"
    assert response.images == []
    assert response.status == "success"


@pytest.mark.asyncio
async def test_searxng_search():
    """SearXNG provider returns parsed SearchResults."""
    set_setting("search_provider", "searxng")
    set_setting("searxng_url", "http://localhost:8080")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Result 1", "url": "https://example.com/1", "content": "Snippet one"},
            {"title": "Result 2", "url": "https://example.com/2", "content": "Snippet two"},
            {"title": "Result 3", "url": "https://example.com/3", "content": "Snippet three"},
        ]
    }

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("test query", max_results=2)

    assert len(response.results) == 2
    assert response.results[0].title == "Result 1"
    assert response.images == []
    assert response.status == "success"


@pytest.mark.asyncio
async def test_search_provider_routing():
    """web_search dispatches to the correct provider based on setting."""
    set_setting("tavily_api_key", "key")
    set_setting("searxng_url", "http://searx")

    empty_response = SearchResponse([], [])
    with (
        patch("quip.services.search._tavily_search", new_callable=AsyncMock, return_value=empty_response) as tavily,
        patch("quip.services.search._searxng_search", new_callable=AsyncMock, return_value=empty_response) as searxng,
    ):
        set_setting("search_provider", "tavily")
        await web_search("test")
        tavily.assert_called_once()
        searxng.assert_not_called()

        tavily.reset_mock()
        searxng.reset_mock()

        set_setting("search_provider", "searxng")
        await web_search("test")
        searxng.assert_called_once()
        tavily.assert_not_called()


# ── Scraper tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jina_reader():
    """Jina Reader returns markdown content, truncated to limit."""
    content = "# Hello World\n\nThis is a test page with lots of content." * 100

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_response.text = content

    with (
        patch(
            "quip.services.url_security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ),
        patch("quip.services.scraper.httpx.AsyncClient") as MockClient,
    ):
        instance = AsyncMock()
        instance.get.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = await read_url("https://example.com", max_chars=500)

    assert len(result) <= 520  # 500 + truncation message
    assert "truncated" in result


@pytest.mark.asyncio
async def test_jina_fallback():
    """When Jina fails, falls back to direct fetch."""
    with (
        patch(
            "quip.services.url_security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ),
        patch("quip.services.scraper._jina_reader", new_callable=AsyncMock, side_effect=Exception("Jina down")),
        patch(
            "quip.services.scraper._direct_fetch", new_callable=AsyncMock, return_value="Fallback content"
        ) as mock_direct,
    ):
        result = await read_url("https://example.com")

    assert result == "Fallback content"
    mock_direct.assert_called_once()


@pytest.mark.asyncio
async def test_read_url_double_failure_is_reported_as_tool_error():
    """Both failed page readers must reach the model as an error, not page content."""
    from quip.services.tools import execute_tool_call

    with (
        patch(
            "quip.services.scraper._jina_reader", new_callable=AsyncMock, side_effect=RuntimeError("Jina unavailable")
        ),
        patch(
            "quip.services.scraper._direct_fetch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("origin unavailable"),
        ),
    ):
        raw = await execute_tool_call(
            None, None, "chat-id", "read_url", json.dumps({"url": "https://example.com/article"})
        )

    result = json.loads(raw)
    assert "error" in result
    assert "content" not in result


# ── Tool execution tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_tool_execution():
    """execute_tool_call dispatches web_search correctly."""
    from quip.services.tools import execute_tool_call

    mock_results = [
        SearchResult(title="Result", url="https://example.com", snippet="A snippet", content="Full content")
    ]

    with patch(
        "quip.services.search.web_search", new_callable=AsyncMock, return_value=SearchResponse(mock_results, [])
    ):
        result_str = await execute_tool_call(
            None,
            None,
            "chat-id",
            "web_search",
            json.dumps({"query": "test"}),
        )

    result = json.loads(result_str)
    assert "results" in result
    assert result["status"] == "success"
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Result"


@pytest.mark.asyncio
async def test_tavily_empty_result_is_explicit_no_results():
    """An empty provider response must not become a fake source row."""
    set_setting("search_provider", "tavily")
    set_setting("tavily_api_key", "test-key")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"results": []}

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.return_value = mock_response
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("unique empty query for regression")

    assert response.status == "no_results"
    assert response.results == []
    assert response.images == []


@pytest.mark.asyncio
async def test_tavily_provider_failure_is_an_error():
    """Provider outages must be distinguishable from a successful empty search."""
    set_setting("search_provider", "tavily")
    set_setting("tavily_api_key", "test-key")

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post.side_effect = RuntimeError("mock provider outage")
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("unique provider error query")

    assert response.status == "error"
    assert response.error
    assert response.results == []


@pytest.mark.asyncio
async def test_searxng_image_failure_preserves_text_results_as_partial():
    """A failed image request should not erase successful text sources."""
    set_setting("search_provider", "searxng")
    set_setting("searxng_url", "http://localhost:8080")

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"title": "Source", "url": "https://example.com/source", "content": "Evidence"},
        ]
    }

    async def mock_get(_url, params):
        if params.get("categories") == "images":
            raise RuntimeError("mock image outage")
        return mock_response

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.side_effect = mock_get
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("unique partial search query")

    assert response.status == "partial"
    assert response.results[0].url == "https://example.com/source"
    assert response.warning


@pytest.mark.asyncio
async def test_searxng_text_failure_is_not_reported_as_empty_success():
    """A failed text request must stay an outage even if image lookup succeeds."""
    set_setting("search_provider", "searxng")
    set_setting("searxng_url", "http://localhost:8080")

    image_response = MagicMock()
    image_response.raise_for_status = MagicMock()
    image_response.json.return_value = {
        "results": [
            {
                "img_src": "https://images.example.com/picture.jpg",
                "url": "https://example.com/page",
                "title": "Picture",
            }
        ]
    }

    async def mock_get(_url, params):
        if params.get("categories") == "images":
            return image_response
        raise RuntimeError("mock text outage")

    with patch("quip.services.search.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.get.side_effect = mock_get
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        response = await web_search("unique text outage query")

    assert response.status == "error"
    assert response.error
    assert response.results == []
    assert len(response.images) == 1


@pytest.mark.asyncio
async def test_search_tool_execution_keeps_failure_metadata():
    """The model and search progress UI need explicit failure metadata."""
    from quip.services.tools import execute_tool_call

    search_response = SimpleNamespace(
        status="error",
        results=[],
        images=[],
        error="Tavily search is unavailable.",
        warning=None,
    )
    with patch("quip.services.search.web_search", new_callable=AsyncMock, return_value=search_response):
        result_str = await execute_tool_call(None, None, "chat-id", "web_search", json.dumps({"query": "test"}))

    result = json.loads(result_str)
    assert result["status"] == "error"
    assert result["error"] == "Tavily search is unavailable."
    assert result["results"] == []


@pytest.mark.asyncio
async def test_search_tool_execution_does_not_emit_fake_empty_source():
    """An empty search should expose an honest status without a fake source row."""
    from quip.services.tools import execute_tool_call

    search_response = SimpleNamespace(
        status="no_results",
        results=[],
        images=[],
        error=None,
        warning=None,
    )
    with patch("quip.services.search.web_search", new_callable=AsyncMock, return_value=search_response):
        result_str = await execute_tool_call(
            None, None, "chat-id", "web_search", json.dumps({"query": "nothing found"})
        )

    result = json.loads(result_str)
    assert result["status"] == "no_results"
    assert result["results"] == []
    assert "message" in result


def test_search_disabled_omits_search_tool_and_disclaims_web_retrieval():
    """Search-off requests cannot call search or claim current web verification."""
    from quip.services.completion.prompt import PromptBuilder

    tools = PromptBuilder.build_tools(
        tool_gating_enabled=False,
        loaded_skills=set(),
        search_mode=True,
        search_enabled=False,
        sandbox_available=False,
    )
    prompt = PromptBuilder.build(
        tool_gating_enabled=False,
        locale=None,
        location=None,
        search_enabled=False,
        search_mode=True,
        sandbox_available=False,
    )

    tool_names = [tool["function"]["name"] for tool in tools]
    assert "web_search" not in tool_names
    assert "Web search is disabled" in prompt
    assert "Do not claim or imply that you searched" in prompt


# ── Integration tests ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_completion_with_search(client, auth_headers):
    """Search tools appear in provider call when search_enabled=true."""
    from quip.providers.openrouter import StreamChunk, ToolCallDelta, UsageInfo

    set_setting("openrouter_api_key", "test-key")
    set_setting("search_enabled", "true")
    set_setting("search_provider", "tavily")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    call_count = 0

    async def mock_stream(**kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: model decides to search
            yield StreamChunk(
                tool_calls=[
                    ToolCallDelta(
                        index=0, id="call_1", function_name="web_search", function_arguments='{"query": "test"}'
                    )
                ]
            )
            yield StreamChunk(finish_reason="tool_calls")
        else:
            # Second call: model responds with search results
            yield StreamChunk(content="Based on search results...")
            yield StreamChunk(finish_reason="stop")
            yield StreamChunk(usage=UsageInfo(prompt_tokens=50, completion_tokens=10, cost=0.001))

    mock_results = [SearchResult(title="Test", url="https://test.com", snippet="A result")]

    with (
        patch("quip.services.completion.stream.openrouter.stream_completion", new=mock_stream),
        patch("quip.services.search.web_search", new_callable=AsyncMock, return_value=SearchResponse(mock_results, [])),
    ):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": "google/gemini-2.0-flash-001", "message": "Search for test"},
        )

    assert res.status_code == 200
    assert "tool_executing" in res.text
    assert "tool_result" in res.text
    assert "web_search" in res.text


@pytest.mark.asyncio
async def test_fast_search_completes_five_mocked_queries_and_persists_sources(client, auth_headers):
    """The search-mode request, tool loop, final answer, and saved results stay connected."""
    from contextlib import asynccontextmanager

    from quip.database import get_db
    from quip.main import app
    from quip.providers.openrouter import StreamChunk, ToolCallDelta, UsageInfo

    set_setting("openrouter_api_key", "test-key")
    set_setting("search_enabled", "true")
    set_setting("search_provider", "tavily")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    provider_calls = 0

    async def mock_stream(**kwargs):
        nonlocal provider_calls
        provider_calls += 1
        if provider_calls <= 5:
            yield StreamChunk(
                tool_calls=[
                    ToolCallDelta(
                        index=0,
                        id=f"search_{provider_calls}",
                        function_name="web_search",
                        function_arguments=json.dumps({"query": f"mock angle {provider_calls}"}),
                    )
                ]
            )
            yield StreamChunk(finish_reason="tool_calls")
        elif provider_calls == 6:
            yield StreamChunk(
                tool_calls=[
                    ToolCallDelta(
                        index=0,
                        id="read_failed_page",
                        function_name="read_url",
                        function_arguments=json.dumps({"url": "https://example.com/source"}),
                    )
                ]
            )
            yield StreamChunk(finish_reason="tool_calls")
        else:
            yield StreamChunk(
                content=(
                    "A source-grounded answer. [1]\n\n---\n**Sources:**\n[1] Mock source - https://example.com/source"
                )
            )
            yield StreamChunk(finish_reason="stop")
            yield StreamChunk(usage=UsageInfo(prompt_tokens=50, completion_tokens=10, cost=0.001))

    mock_results = [SearchResult(title="Mock source", url="https://example.com/source", snippet="Mock evidence")]

    test_db_override = app.dependency_overrides[get_db]

    @asynccontextmanager
    async def test_save_session():
        session_generator = test_db_override()
        try:
            yield await anext(session_generator)
        finally:
            await session_generator.aclose()

    with (
        patch(
            "quip.services.url_security.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ),
        patch("quip.services.completion.stream.openrouter.stream_completion", new=mock_stream),
        patch(
            "quip.services.search.web_search", new_callable=AsyncMock, return_value=SearchResponse(mock_results, [])
        ) as mock_search,
        patch(
            "quip.services.scraper._jina_reader", new_callable=AsyncMock, side_effect=RuntimeError("Jina unavailable")
        ),
        patch(
            "quip.services.scraper._direct_fetch",
            new_callable=AsyncMock,
            side_effect=RuntimeError("origin unavailable"),
        ),
        patch("quip.services.messages_persist.async_session", new=test_save_session),
    ):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={
                "model": "google/gemini-2.0-flash-001",
                "message": "Search the web for a multi-angle answer",
                "mode_hint": "search",
            },
        )

    assert res.status_code == 200
    assert provider_calls == 7  # five searches, one page-read failure, and a final answer
    assert mock_search.await_count == 5
    assert "A source-grounded answer." in res.text

    tool_result_events = [
        json.loads(frame.split("data: ", 1)[1])
        for frame in res.text.split("\n\n")
        if frame.startswith("event: tool_result\n")
    ]
    failed_read = next(event for event in tool_result_events if event["id"] == "read_failed_page")
    assert failed_read["status"] == "error"
    assert "Page retrieval failed" in failed_read["result"]

    chat_event = next(
        json.loads(frame.split("data: ", 1)[1]) for frame in res.text.split("\n\n") if frame.startswith("event: chat\n")
    )
    saved = await client.get(f"/api/chats/{chat_event['chat_id']}", headers=auth_headers)
    assert saved.status_code == 200
    assistant = next(m for m in saved.json()["messages"] if m["role"] == "assistant")
    assert "A source-grounded answer." in assistant["content"]
    assert len(assistant["tool_calls"]) == 6
    search_calls = [call for call in assistant["tool_calls"] if call["name"] == "web_search"]
    read_calls = [call for call in assistant["tool_calls"] if call["name"] == "read_url"]
    assert len(search_calls) == 5
    assert all(call["status"] == "completed" for call in search_calls)
    assert all(call["result"]["results"][0]["url"] == "https://example.com/source" for call in search_calls)
    assert len(read_calls) == 1
    assert read_calls[0]["status"] == "error"
    assert "Page retrieval failed" in read_calls[0]["result"]["error"]


@pytest.mark.asyncio
async def test_search_disabled_no_tools(client, auth_headers):
    """When search_enabled=false, search tools are not passed to provider."""
    from quip.providers.openrouter import StreamChunk, UsageInfo

    set_setting("openrouter_api_key", "test-key")
    set_setting("search_enabled", "false")
    set_setting("rag_enabled", "false")
    set_setting("artifacts_enabled", "false")
    set_setting("sandbox_enabled", "false")

    captured_kwargs = {}

    async def capturing_stream(**kwargs):
        captured_kwargs.update(kwargs)
        yield StreamChunk(content="Hello!")
        yield StreamChunk(finish_reason="stop")
        yield StreamChunk(usage=UsageInfo(prompt_tokens=10, completion_tokens=5, cost=0.0001))

    with patch("quip.services.completion.stream.openrouter.stream_completion", new=capturing_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={
                "model": "google/gemini-2.0-flash-001",
                "message": "Find current information",
                "mode_hint": "search",
            },
        )

    assert res.status_code == 200
    # Search tools should NOT be in the tool list when search is disabled
    tool_names = [t.get("function", {}).get("name") for t in (captured_kwargs.get("tools") or [])]
    assert "web_search" not in tool_names
    assert "fast_search" not in tool_names
    system_prompt = captured_kwargs["messages"][0]["content"]
    assert "Web search is disabled" in system_prompt
    assert "Do not claim or imply that you searched" in system_prompt
