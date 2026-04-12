"""Tests for web search and scraper services."""
import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from quip.services.config import set_setting
from quip.services.search import web_search, SearchResult
from quip.services.scraper import read_url


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

        results = await web_search("python web framework", max_results=2)

    assert len(results) == 2
    assert results[0].title == "Python Docs"
    assert results[0].url == "https://python.org"
    assert results[1].title == "FastAPI"


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

        results = await web_search("test query", max_results=2)

    assert len(results) == 2
    assert results[0].title == "Result 1"


@pytest.mark.asyncio
async def test_search_provider_routing():
    """web_search dispatches to the correct provider based on setting."""
    set_setting("tavily_api_key", "key")
    set_setting("searxng_url", "http://searx")

    with patch("quip.services.search._tavily_search", new_callable=AsyncMock, return_value=[]) as tavily, \
         patch("quip.services.search._searxng_search", new_callable=AsyncMock, return_value=[]) as searxng:

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

    with patch("quip.services.scraper.httpx.AsyncClient") as MockClient:
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
    with patch("quip.services.scraper._jina_reader", new_callable=AsyncMock, side_effect=Exception("Jina down")), \
         patch("quip.services.scraper._direct_fetch", new_callable=AsyncMock, return_value="Fallback content") as mock_direct:

        result = await read_url("https://example.com")

    assert result == "Fallback content"
    mock_direct.assert_called_once()


# ── Tool execution tests ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_tool_execution():
    """execute_tool_call dispatches web_search correctly."""
    from quip.services.tools import execute_tool_call

    mock_results = [
        SearchResult(title="Result", url="https://example.com", snippet="A snippet", content="Full content")
    ]

    with patch("quip.services.search.web_search", new_callable=AsyncMock, return_value=mock_results):
        result_str = await execute_tool_call(
            None, None, "chat-id",
            "web_search", json.dumps({"query": "test"}),
        )

    result = json.loads(result_str)
    assert "results" in result
    assert len(result["results"]) == 1
    assert result["results"][0]["title"] == "Result"


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
            yield StreamChunk(tool_calls=[
                ToolCallDelta(index=0, id="call_1", function_name="web_search",
                              function_arguments='{"query": "test"}')
            ])
            yield StreamChunk(finish_reason="tool_calls")
        else:
            # Second call: model responds with search results
            yield StreamChunk(content="Based on search results...")
            yield StreamChunk(finish_reason="stop")
            yield StreamChunk(usage=UsageInfo(prompt_tokens=50, completion_tokens=10, cost=0.001))

    mock_results = [SearchResult(title="Test", url="https://test.com", snippet="A result")]

    with patch("quip.routers.completion.openrouter.stream_completion", new=mock_stream), \
         patch("quip.services.search.web_search", new_callable=AsyncMock, return_value=mock_results):
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

    with patch("quip.routers.completion.openrouter.stream_completion", new=capturing_stream):
        res = await client.post(
            "/api/chat/completions",
            headers=auth_headers,
            json={"model": "google/gemini-2.0-flash-001", "message": "Hello"},
        )

    assert res.status_code == 200
    # Tools should be None when both sandbox and search are disabled
    assert captured_kwargs.get("tools") is None
