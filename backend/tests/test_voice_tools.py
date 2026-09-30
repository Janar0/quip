import json
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from quip.core import config
from quip.models.chat import Chat, Message
from quip.models.user import User
from quip.models.voice import VoiceCall, VoiceToolCall


async def _active_call(client, auth_headers, db_session):
    chat_response = await client.post("/api/chats", headers=auth_headers, json={"title": "Voice tools"})
    assert chat_response.status_code == 201
    chat_id = UUID(chat_response.json()["id"])
    user = await db_session.scalar(select(User).where(User.email == "test@quip.dev"))
    call = VoiceCall(
        id=uuid4(),
        user_id=user.id,
        chat_id=chat_id,
        provider="qwen",
        model="catalog-model-fixture",
        status="active",
    )
    db_session.add(call)
    await db_session.commit()
    return call


@pytest.mark.asyncio
async def test_voice_tool_rejects_unknown_tool_and_extra_arguments(client, auth_headers, db_session):
    call = await _active_call(client, auth_headers, db_session)
    unknown = await client.post(
        f"/api/voice/calls/{call.id}/tools",
        headers=auth_headers,
        json={"provider_call_id": "call-unknown", "name": "sandbox_execute", "arguments": "{}"},
    )
    extra = await client.post(
        f"/api/voice/calls/{call.id}/tools",
        headers=auth_headers,
        json={"provider_call_id": "call-extra", "name": "web_search", "arguments": json.dumps({"query": "weather", "user_id": "other"})},
    )

    assert unknown.status_code == 422
    assert extra.status_code == 422
    assert await db_session.scalar(select(VoiceToolCall).where(VoiceToolCall.voice_call_id == call.id)) is None


@pytest.mark.asyncio
async def test_voice_search_obeys_quip_permission_and_returns_bounded_replayable_result(
    client, auth_headers, db_session, monkeypatch
):
    from quip.services import search
    from quip.services import skill_store

    call = await _active_call(client, auth_headers, db_session)
    monkeypatch.setitem(config._settings, "search_enabled", "true")
    monkeypatch.setattr(skill_store, "get_skill", lambda _name: SimpleNamespace(enabled=True, is_internal=False))
    requests = []

    async def fake_web_search(query, max_results=5):
        requests.append((query, max_results))
        return ([SimpleNamespace(title="Museum", url="https://museum.example/hours", snippet="Open 10-6", content="Open 10-6")], [])

    monkeypatch.setattr(search, "web_search", fake_web_search)
    body = {
        "provider_call_id": "call-search-1",
        "name": "web_search",
        "arguments": json.dumps({"query": "museum hours tomorrow"}),
    }
    first = await client.post(f"/api/voice/calls/{call.id}/tools", headers=auth_headers, json=body)
    replay = await client.post(f"/api/voice/calls/{call.id}/tools", headers=auth_headers, json=body)
    await db_session.refresh(call)

    assert first.status_code == replay.status_code == 200
    assert replay.json()["replayed"] is True
    assert requests == [("museum hours tomorrow", 5)]
    assert first.json()["result"]["results"][0]["title"] == "Museum"
    assert len(json.dumps(first.json()["result"])) < 10_000
    assert call.client_usage == {}
    tool_message = await db_session.scalar(select(Message).where(Message.chat_id == call.chat_id))
    assert tool_message.role == "tool"
    assert tool_message.meta["source"] == "qwen_voice_tool"


@pytest.mark.asyncio
async def test_voice_search_is_denied_when_global_gate_is_off(client, auth_headers, db_session, monkeypatch):
    from quip.services import search
    from quip.services import skill_store

    call = await _active_call(client, auth_headers, db_session)
    monkeypatch.setitem(config._settings, "search_enabled", "false")
    monkeypatch.setattr(skill_store, "get_skill", lambda _name: SimpleNamespace(enabled=True, is_internal=False))

    async def never_search(*_args, **_kwargs):
        raise AssertionError("the web provider is gated off")

    monkeypatch.setattr(search, "web_search", never_search)
    response = await client.post(
        f"/api/voice/calls/{call.id}/tools",
        headers=auth_headers,
        json={"provider_call_id": "call-search-off", "name": "web_search", "arguments": "{\"query\":\"news\"}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Web search is disabled"


@pytest.mark.asyncio
async def test_voice_tool_conflicting_replay_and_parallel_call_are_rejected(client, auth_headers, db_session, monkeypatch):
    from quip.services import search
    from quip.services import skill_store

    call = await _active_call(client, auth_headers, db_session)
    monkeypatch.setitem(config._settings, "search_enabled", "true")
    monkeypatch.setattr(skill_store, "get_skill", lambda _name: SimpleNamespace(enabled=True, is_internal=False))
    started = False

    async def waiting_search(query, max_results=5):
        nonlocal started
        started = True
        return ([SimpleNamespace(title=query, url="https://search.example/", snippet="result", content="result")], [])

    monkeypatch.setattr(search, "web_search", waiting_search)
    body = {"provider_call_id": "call-same", "name": "web_search", "arguments": "{\"query\":\"one\"}"}
    first = await client.post(f"/api/voice/calls/{call.id}/tools", headers=auth_headers, json=body)
    conflict = await client.post(
        f"/api/voice/calls/{call.id}/tools",
        headers=auth_headers,
        json={**body, "arguments": "{\"query\":\"different\"}"},
    )

    assert first.status_code == 200 and started
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Tool call ID was reused with different arguments"


@pytest.mark.asyncio
async def test_voice_tool_hides_calls_owned_by_another_user(client, auth_headers, db_session):
    other_id, chat_id, call_id = uuid4(), uuid4(), uuid4()
    db_session.add(User(
        id=other_id,
        email="tools-owner@quip.dev",
        username="tools-owner",
        name="Tools Owner",
        role="user",
        is_active=True,
    ))
    db_session.add(Chat(id=chat_id, user_id=other_id, title="Private tool chat"))
    db_session.add(VoiceCall(
        id=call_id,
        user_id=other_id,
        chat_id=chat_id,
        provider="qwen",
        model="catalog-model-fixture",
        status="active",
    ))
    await db_session.commit()
    response = await client.post(
        f"/api/voice/calls/{call_id}/tools",
        headers=auth_headers,
        json={"provider_call_id": "call-private", "name": "read_url", "arguments": "{\"url\":\"https://example.org\"}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Voice call not found"
