import pytest

import quip.services.completion.service as completion_service


@pytest.mark.asyncio
async def test_selected_model_stream_passes_explicit_tools_through_quip_seam(monkeypatch):
    model_id = "openrouter/luna-catalog-entry"
    explicit_tools = [{"type": "function", "function": {"name": "read_url"}}]
    captured = {}

    class OrchestratorFixture:
        def __init__(self, **kwargs):
            captured["constructor"] = kwargs

        async def stream_with_tools(self, tools):
            captured["tools"] = tools
            yield ("finish", {"reason": "stop"})

    monkeypatch.setattr(completion_service, "_resolve_model", lambda selected: selected)
    monkeypatch.setattr(completion_service, "get_cached_model", lambda selected: {
        "id": selected, "supports_tools": True, "context_length": 32_000,
    })
    monkeypatch.setattr(completion_service, "get_setting", lambda key, default="": {
        "openrouter_api_key": "fixture-only-key",
        "ollama_url": "http://localhost:11434",
    }.get(key, default))
    monkeypatch.setattr(completion_service, "StreamOrchestrator", OrchestratorFixture)

    events = [event async for event in completion_service.CompletionService.stream_selected_model(
        [{"role": "user", "content": "bounded task"}],
        model_id,
        tools=explicit_tools,
        max_tokens=100_000,
    )]

    assert events == [("finish", {"reason": "stop"})]
    assert captured["constructor"]["model"] == model_id
    assert captured["constructor"]["api_key"] == "fixture-only-key"
    assert captured["constructor"]["max_tokens"] == 1_200
    assert captured["constructor"]["tool_gating_enabled"] is False
    assert captured["constructor"]["sandbox_available"] is False
    assert captured["tools"] is explicit_tools
