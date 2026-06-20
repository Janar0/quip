import httpx
import pytest

from quip.providers.openrouter import stream_completion


class _FailingStream:
    async def __aenter__(self):
        raise httpx.ConnectError("[Errno -3] Temporary failure in name resolution")

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FailingClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, *args, **kwargs):
        return _FailingStream()


@pytest.mark.asyncio
async def test_stream_completion_includes_connect_error_reason(monkeypatch):
    monkeypatch.setattr("quip.providers.openrouter.httpx.AsyncClient", _FailingClient)

    chunks = [
        chunk
        async for chunk in stream_completion(
            messages=[{"role": "user", "content": "hello"}],
            model="google/gemini-3-flash-preview",
            api_key="test-key",
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].error
    assert "Cannot connect to OpenRouter API" in chunks[0].error
    assert "Temporary failure in name resolution" in chunks[0].error
