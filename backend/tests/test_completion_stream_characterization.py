"""Characterize stream accumulation and persistence before separating the service."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from quip.core.config import set_setting
from quip.services.streaming import sse_event


def events(response):
    result = []
    for block in response.text.strip().split("\n\n"):
        lines = block.splitlines()
        result.append((lines[0][7:], json.loads(lines[1][6:])))
    return result


@pytest.mark.asyncio
@pytest.mark.parametrize("regenerate", [False, True])
async def test_partial_error_persists_accumulated_tools_images_usage(client, auth_headers, regenerate):
    set_setting("openrouter_api_key", "test-key")
    set_setting("rag_enabled", "false")
    set_setting("search_enabled", "false")

    async def stream(self, **kwargs):
        yield sse_event("content", {"text": "Partial answer"})
        yield sse_event("reasoning", {"text": "Working"})
        yield sse_event("usage", {"prompt_tokens": 2, "completion_tokens": 3, "cost": 0.1})
        yield sse_event("usage", {"prompt_tokens": 5, "completion_tokens": 7, "cost": 0.2})
        yield sse_event("tool_executing", {"id": "tool-1", "name": "search", "arguments": {}})
        yield sse_event("tool_result", {"id": "tool-1", "result": '{"answer": 42}'})
        yield sse_event("search_images", {"images": [{"img_src": "one"}]})
        yield sse_event("search_images", {"images": [{"img_src": "one"}, {"img_src": "two"}], "append": True})
        yield sse_event("error", {"error": "Provider failed"})

    with (
        patch("quip.services.completion.service.StreamOrchestrator.run", new=stream),
        patch("quip.services.completion.service.save_assistant_message", new_callable=AsyncMock) as save,
        patch("quip.services.completion.service.generate_chat_identity", new_callable=AsyncMock) as title,
    ):
        response = await client.post(
            "/api/chat/completions", headers=auth_headers, json={"model": "test/model", "message": "Question"}
        )
        if regenerate:
            chat = events(response)[0][1]
            save.reset_mock()
            response = await client.post(
                "/api/chat/regenerate",
                headers=auth_headers,
                json={"chat_id": chat["chat_id"], "message_id": chat["message_id"]},
            )
        assert response.status_code == 200
        assert events(response)[-1] == ("error", {"error": "Provider failed"})
        assert all(kind != "done" for kind, _ in events(response))
        save.assert_awaited_once()
        assert save.call_args.args[3] == "Partial answer"
        assert save.call_args.args[5]["prompt_tokens"] == 7
        assert save.call_args.args[5]["completion_tokens"] == 10
        assert save.call_args.kwargs["reasoning"] == "Working"
        assert save.call_args.kwargs["tool_executions"][0]["result"] == {"answer": 42}
        assert save.call_args.kwargs["search_images"] == [{"img_src": "one"}, {"img_src": "two"}]
        title.assert_not_awaited()
