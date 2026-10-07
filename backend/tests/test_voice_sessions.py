from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from quip.core import config
from quip.models.chat import Chat
from quip.models.user import User
from quip.models.voice import VoiceCall


async def _create_chat(client, headers: dict[str, str]) -> UUID:
    response = await client.post("/api/chats", headers=headers, json={"title": "Voice test"})
    assert response.status_code == 201
    return UUID(response.json()["id"])


@pytest.mark.asyncio
async def test_voice_session_requires_authentication(client):
    response = await client.post(
        "/api/voice/calls",
        json={"chat_id": "00000000-0000-0000-0000-000000000001", "sdp": "v=0", "type": "offer"},
    )

    assert response.status_code == 401, response.text
    assert response.json()["detail"] == "Authentication required"


@pytest.mark.asyncio
async def test_voice_capabilities_are_authenticated_and_disable_camera_for_qwen_audio_31(
    client, auth_headers, monkeypatch
):
    monkeypatch.setitem(config._settings, "qwen_realtime_model", "qwen-audio-3.1-realtime-plus")
    monkeypatch.setitem(config._settings, "qwen_realtime_video_enabled", "true")

    # The shared test client may retain the login cookie set while building
    # auth_headers. Clear it so this request actually exercises anonymous auth.
    client.cookies.clear()
    anonymous = await client.get("/api/voice/config")
    assert anonymous.status_code == 401

    response = await client.get("/api/voice/config", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json() == {
        "enabled": False,
        "model": "qwen-audio-3.1-realtime-plus",
        "camera_supported": False,
    }


@pytest.mark.asyncio
async def test_qwen_audio_31_rejects_camera_before_provider_signaling(client, auth_headers, monkeypatch):
    from quip.services.voice import session

    chat_id = await _create_chat(client, auth_headers)
    for key, value in {
        "qwen_voice_enabled": "true",
        "qwen_realtime_endpoint": "https://maas.qwencloudapi.com/api/v1/webrtc/realtime",
        "qwen_realtime_api_key": "test-only-placeholder",
        "qwen_realtime_model": "qwen-audio-3.1-realtime-plus",
        "qwen_realtime_video_enabled": "true",
    }.items():
        monkeypatch.setitem(config._settings, key, value)

    class NeverCalledClient:
        def __init__(self, **_kwargs):
            raise AssertionError("Qwen Audio 3.1 does not document video input")

    monkeypatch.setattr(session.httpx, "AsyncClient", NeverCalledClient)
    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={"chat_id": str(chat_id), "sdp": "v=0", "type": "offer", "camera_enabled": True},
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "Camera input is not supported by the configured realtime model"


@pytest.mark.asyncio
async def test_voice_session_rejects_non_sdp_offer(client, auth_headers, monkeypatch):
    from quip.services.voice import session

    chat_id = await _create_chat(client, auth_headers)
    for key, value in {
        "qwen_voice_enabled": "true",
        "qwen_realtime_endpoint": "https://realtime.example.test/v1/realtime",
        "qwen_realtime_api_key": "server-key",
        "qwen_realtime_model": "catalog-model-fixture",
    }.items():
        monkeypatch.setitem(config._settings, key, value)

    class NeverCalledClient:
        def __init__(self, **_kwargs):
            raise AssertionError("malformed SDP must be rejected before contacting the provider")

    monkeypatch.setattr(session.httpx, "AsyncClient", NeverCalledClient)
    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={"chat_id": str(chat_id), "sdp": "not an SDP offer", "type": "offer"},
    )

    assert response.status_code == 422, response.text


@pytest.mark.asyncio
async def test_voice_session_is_disabled_without_operator_configuration(client, auth_headers):
    chat_id = await _create_chat(client, auth_headers)

    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={"chat_id": str(chat_id), "sdp": "v=0", "type": "offer"},
    )

    assert response.status_code == 503, response.text
    assert response.json()["detail"] == "Voice calling is not configured"


@pytest.mark.asyncio
async def test_voice_sdp_uses_server_key_and_does_not_return_it(client, auth_headers, db_session, monkeypatch):
    from quip.services.voice import session

    chat_id = await _create_chat(client, auth_headers)
    secret = "server-only-qwen-test-key"
    endpoint = "https://maas.qwencloudapi.com/api/v1/webrtc/realtime"
    for key, value in {
        "qwen_voice_enabled": "true",
        "qwen_realtime_endpoint": endpoint,
        "qwen_realtime_api_key": secret,
        "qwen_realtime_model": "qwen-audio-3.1-realtime-plus",
    }.items():
        monkeypatch.setitem(config._settings, key, value)

    captured: dict[str, object] = {}

    class FakeResponse:
        text = "v=0\r\no=provider 1 1 IN IP4 127.0.0.1\r\n"

        @staticmethod
        def raise_for_status():
            return None

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return FakeResponse()

    monkeypatch.setattr(session.httpx, "AsyncClient", FakeClient)
    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={
            "chat_id": str(chat_id),
            "sdp": "v=0\r\no=browser 1 1 IN IP4 127.0.0.1\r\n",
            "type": "offer",
            "camera_enabled": False,
            "endpoint": "https://attacker.invalid/",
            "api_key": "client-forgery",
        },
    )

    assert response.status_code == 200, response.text
    assert captured["url"] == endpoint
    assert captured["params"] == {"model": "qwen-audio-3.1-realtime-plus"}
    assert captured["headers"]["Authorization"] == f"Bearer {secret}"
    assert captured["content"].startswith(b"v=0")
    assert secret not in response.text
    assert "api_key" not in response.json()
    persisted_call = await db_session.scalar(select(VoiceCall).where(VoiceCall.id == UUID(response.json()["call_id"])))
    assert persisted_call is not None
    assert persisted_call.camera_enabled is False


@pytest.mark.asyncio
async def test_voice_session_cannot_target_another_users_chat(client, auth_headers, db_session, monkeypatch):
    from quip.services.voice import session

    for key, value in {
        "qwen_voice_enabled": "true",
        "qwen_realtime_endpoint": "https://realtime.example.test/v1/realtime",
        "qwen_realtime_api_key": "server-key",
        "qwen_realtime_model": "catalog-model-fixture",
    }.items():
        monkeypatch.setitem(config._settings, key, value)
    other_id = uuid4()
    other = User(id=other_id, email="other@quip.dev", username="other", name="Other", role="user", is_active=True)
    other_chat = Chat(user_id=other_id, title="Private chat")
    db_session.add_all([other, other_chat])
    await db_session.commit()

    class NeverCalledClient:
        def __init__(self, **_kwargs):
            raise AssertionError("provider must not be called for another user's chat")

    monkeypatch.setattr(session.httpx, "AsyncClient", NeverCalledClient)
    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={"chat_id": str(other_chat.id), "sdp": "v=0", "type": "offer"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Chat not found"


@pytest.mark.asyncio
async def test_voice_provider_error_is_sanitized_and_session_is_failed(client, auth_headers, db_session, monkeypatch):
    import httpx

    from quip.services.voice import session

    chat_id = await _create_chat(client, auth_headers)
    for key, value in {
        "qwen_voice_enabled": "true",
        "qwen_realtime_endpoint": "https://realtime.example.test/v1/realtime",
        "qwen_realtime_api_key": "server-only-secret",
        "qwen_realtime_model": "catalog-model-fixture",
    }.items():
        monkeypatch.setitem(config._settings, key, value)

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            request = httpx.Request("POST", "https://realtime.example.test/v1/realtime")
            response = httpx.Response(403, request=request, text="server-only-secret upstream-detail")
            raise httpx.HTTPStatusError("server-only-secret upstream-detail", request=request, response=response)

    monkeypatch.setattr(session.httpx, "AsyncClient", FakeClient)
    response = await client.post(
        "/api/voice/calls",
        headers=auth_headers,
        json={"chat_id": str(chat_id), "sdp": "v=0", "type": "offer"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Voice provider could not establish the session"}
    assert "server-only-secret" not in response.text
    failed_call = await db_session.scalar(select(VoiceCall).where(VoiceCall.chat_id == chat_id))
    assert failed_call is not None
    assert failed_call.status == "failed"
    assert failed_call.error_code == "provider_signaling_failed"
    assert failed_call.camera_enabled is False


@pytest.mark.asyncio
async def test_voice_end_hides_call_owned_by_another_user(client, auth_headers, db_session):
    other_id, chat_id, call_id = uuid4(), uuid4(), uuid4()
    db_session.add(
        User(
            id=other_id,
            email="voice-owner@quip.dev",
            username="voice-owner",
            name="Voice Owner",
            role="user",
            is_active=True,
        )
    )
    db_session.add(Chat(id=chat_id, user_id=other_id, title="Private voice chat"))
    db_session.add(
        VoiceCall(
            id=call_id,
            user_id=other_id,
            chat_id=chat_id,
            provider="qwen",
            model="catalog-model-fixture",
            status="active",
        )
    )
    await db_session.commit()

    response = await client.post(f"/api/voice/calls/{call_id}/end", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["detail"] == "Voice call not found"
    persisted = await db_session.get(VoiceCall, call_id)
    assert persisted.status == "active"
