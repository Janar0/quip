"""Tests for admin default_model setting, /api/models exposure, and prompt caching."""
import pytest
from unittest.mock import AsyncMock, patch

from quip.providers.openrouter import _inject_cache_control, _should_add_cache_control


@pytest.fixture(autouse=True)
def mock_save_settings():
    """save_settings() uses the global async_session (different engine than test DB).
    Patch it to a no-op — settings are already updated in memory by set_setting()."""
    with patch("quip.routers.admin.save_settings", new_callable=AsyncMock):
        yield


# ── Admin settings ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_default_model_initially_null(client, auth_headers):
    res = await client.get("/api/admin/settings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["default_model"] is None


@pytest.mark.asyncio
async def test_admin_default_model_set_and_get(client, auth_headers):
    res = await client.put(
        "/api/admin/settings",
        json={"default_model": "anthropic/claude-sonnet-4"},
        headers=auth_headers,
    )
    assert res.status_code == 200

    res = await client.get("/api/admin/settings", headers=auth_headers)
    assert res.json()["default_model"] == "anthropic/claude-sonnet-4"


@pytest.mark.asyncio
async def test_admin_default_model_clear(client, auth_headers):
    await client.put(
        "/api/admin/settings",
        json={"default_model": "anthropic/claude-sonnet-4"},
        headers=auth_headers,
    )
    await client.put(
        "/api/admin/settings",
        json={"default_model": ""},
        headers=auth_headers,
    )
    res = await client.get("/api/admin/settings", headers=auth_headers)
    assert res.json()["default_model"] is None


# ── /api/models ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_models_endpoint_default_model_null(client, auth_headers):
    res = await client.get("/api/models", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "default_model" in data
    assert data["default_model"] is None


@pytest.mark.asyncio
async def test_models_endpoint_reflects_admin_default(client, auth_headers):
    await client.put(
        "/api/admin/settings",
        json={"default_model": "anthropic/claude-haiku-4-5"},
        headers=auth_headers,
    )
    res = await client.get("/api/models", headers=auth_headers)
    assert res.json()["default_model"] == "anthropic/claude-haiku-4-5"


# ── Prompt caching ────────────────────────────────────────────────────────────


def test_cache_control_detection():
    assert _should_add_cache_control("anthropic/claude-sonnet-4") is True
    assert _should_add_cache_control("anthropic/claude-haiku-4-5") is True
    assert _should_add_cache_control("openai/gpt-4o") is False
    assert _should_add_cache_control("ollama/llama3") is False


def test_inject_marks_system_message():
    msgs = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Question"},
    ]
    result = _inject_cache_control(msgs)
    sys_content = result[0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[0]["cache_control"] == {"type": "ephemeral"}


def test_inject_marks_second_to_last():
    msgs = [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi"},
        {"role": "user", "content": "Question"},
    ]
    result = _inject_cache_control(msgs)
    penultimate = result[-2]["content"]
    assert isinstance(penultimate, list)
    assert penultimate[0]["cache_control"] == {"type": "ephemeral"}
    # Last message untouched
    assert result[-1]["content"] == "Question"


def test_inject_short_conversation_no_second_mark():
    """< 3 messages: only system marked, no second-to-last."""
    msgs = [
        {"role": "system", "content": "Be concise."},
        {"role": "user", "content": "Hi"},
    ]
    result = _inject_cache_control(msgs)
    assert isinstance(result[0]["content"], list)
    assert result[1]["content"] == "Hi"


def test_inject_no_system_message():
    msgs = [
        {"role": "user", "content": "First"},
        {"role": "assistant", "content": "Reply"},
        {"role": "user", "content": "Follow-up"},
    ]
    result = _inject_cache_control(msgs)
    assert result[0]["content"] == "First"
    penultimate = result[-2]["content"]
    assert isinstance(penultimate, list)
    assert penultimate[0]["cache_control"] == {"type": "ephemeral"}


def test_inject_does_not_mutate_original():
    msgs = [{"role": "system", "content": "You are helpful."}, {"role": "user", "content": "Hi"}]
    original_content = msgs[0]["content"]
    _inject_cache_control(msgs)
    assert msgs[0]["content"] == original_content
