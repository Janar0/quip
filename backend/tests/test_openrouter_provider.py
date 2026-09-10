"""Provider behavior against simulated network failures; no key/network required."""

from copy import deepcopy
from unittest.mock import AsyncMock

import httpx
import pytest

from quip.providers import openrouter
from quip.providers.http import send_with_connect_retry


@pytest.fixture
def mock_provider(monkeypatch):
    original_client = httpx.AsyncClient
    monkeypatch.setattr("quip.providers.http.asyncio.sleep", AsyncMock())

    def configure(handler):
        monkeypatch.setattr(
            openrouter.httpx,
            "AsyncClient",
            lambda **kwargs: original_client(
                transport=httpx.MockTransport(handler),
                **kwargs,
            ),
        )

    return configure


async def collect():
    return [
        chunk
        async for chunk in openrouter.stream_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="test/model",
            api_key="test-key",
        )
    ]


async def test_dns_failure_retries_and_explains_backend_network(mock_provider):
    calls = []

    def fail(request):
        calls.append(request)
        raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution", request=request)

    mock_provider(fail)
    chunks = await collect()
    assert len(calls) == 3
    assert len(chunks) == 1
    assert "DNS lookup failed" in chunks[0].error
    assert "backend" in chunks[0].error
    assert "API key error" in chunks[0].error


async def test_transient_connection_failure_recovers(mock_provider):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise httpx.ConnectError("temporary DNS failure", request=request)
        return httpx.Response(200, text='data:{"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n')

    mock_provider(handler)
    assert "".join(c.content for c in await collect()) == "hello"
    assert calls == 3


async def test_null_usage_and_delta_do_not_break_stream(mock_provider):
    mock_provider(
        lambda request: httpx.Response(
            200,
            text=(
                ': keepalive\nevent: message\ndata: {"choices":[{"delta":null}],"usage":null}\n\n'
                'data: {"choices":[],"usage":{"prompt_tokens_details":null,"cost":null}}\n\n'
                'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n'
            ),
        )
    )
    chunks = await collect()
    assert not any(c.error for c in chunks)
    assert "".join(c.content for c in chunks) == "ok"
    assert chunks[0].usage.cost == 0


async def test_no_retry_after_partial_output(mock_provider):
    class BrokenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise httpx.ReadError("connection lost")

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=BrokenStream())

    mock_provider(handler)
    chunks = await collect()
    assert chunks[0].content == "partial"
    assert chunks[-1].error
    assert len(calls) == 1


@pytest.mark.parametrize("status", [401, 429, 503])
async def test_http_failures_are_not_replayed(mock_provider, status):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "rejected"}})

    mock_provider(handler)
    assert (await collect())[0].error == "rejected"
    assert len(calls) == 1


async def test_provider_metadata_failure_does_not_break_settings(mock_provider):
    def fail(request):
        raise httpx.ConnectError("DNS failure", request=request)

    mock_provider(fail)
    assert await openrouter.get_key_info("key") == {}
    assert await openrouter.list_models("key") == []
    assert await openrouter.get_generation("generation", "key") == {}


async def test_connection_timeout_is_retried():
    client = AsyncMock()
    request = httpx.Request("GET", "https://example.test")
    response = httpx.Response(200)
    client.send.side_effect = [httpx.ConnectTimeout("timeout"), response]
    assert await send_with_connect_retry(client, request) is response
    assert client.send.await_count == 2


def test_prompt_cache_does_not_mutate_multimodal_history():
    history = [
        {"role": "system", "content": [{"type": "text", "text": "system"}]},
        {"role": "user", "content": [{"type": "text", "text": "context"}]},
        {"role": "user", "content": "question"},
    ]
    original = deepcopy(history)
    body = openrouter.build_request_body("anthropic/test", history)
    assert history == original
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
