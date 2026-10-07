from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from quip.models.chat import Chat, Message
from quip.models.user import User
from quip.models.voice import VoiceCall


async def _active_call(client, auth_headers, db_session):
    chat_response = await client.post("/api/chats", headers=auth_headers, json={"title": "Voice events"})
    assert chat_response.status_code == 201
    chat_id = UUID(chat_response.json()["id"])
    user = await db_session.scalar(select(User).where(User.email == "test@quip.dev"))
    call = VoiceCall(
        id=uuid4(),
        user_id=user.id,
        chat_id=chat_id,
        provider="qwen",
        model="catalog-model-fixture",
        status="connecting",
    )
    db_session.add(call)
    await db_session.commit()
    return call, chat_id


@pytest.mark.asyncio
async def test_voice_events_persist_final_user_and_assistant_transcripts_once(client, auth_headers, db_session):
    call, chat_id = await _active_call(client, auth_headers, db_session)
    session_response = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={"event": {"type": "session.created", "event_id": "evt-session", "session": {"model": call.model}}},
    )
    assert session_response.status_code == 200, session_response.text
    assert session_response.json()["status"] == "active"

    user_event = {
        "type": "conversation.item.input_audio_transcription.completed",
        "event_id": "evt-user-final",
        "item_id": "item-user-1",
        "transcript": "Найди расписание музея на завтра.",
    }
    first = await client.post(f"/api/voice/calls/{call.id}/events", headers=auth_headers, json={"event": user_event})
    second = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={"event": {**user_event, "event_id": "evt-user-retry"}},
    )
    assistant = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={
            "event": {
                "type": "response.audio_transcript.done",
                "event_id": "evt-assistant-final",
                "item_id": "item-assistant-1",
                "transcript": "Сейчас проверю.",
            }
        },
    )

    assert first.status_code == second.status_code == assistant.status_code == 200
    assert second.json()["duplicate"] is True
    messages = list(
        (await db_session.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at))).all()
    )
    assert [(message.role, message.content) for message in messages] == [
        ("user", "Найди расписание музея на завтра."),
        ("assistant", "Сейчас проверю."),
    ]
    assert messages[0].meta["source"] == "qwen_realtime_client_event"
    assert messages[0].meta["provider_item_id"] == "item-user-1"
    assert messages[1].meta["voice_call_id"] == str(call.id)


@pytest.mark.asyncio
async def test_voice_events_store_only_preliminary_provider_usage(client, auth_headers, db_session):
    call, _chat_id = await _active_call(client, auth_headers, db_session)
    response = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={
            "event": {
                "type": "response.done",
                "event_id": "evt-done",
                "response": {
                    "id": "response-1",
                    "usage": {"total_tokens": 9, "input_tokens": 5, "output_tokens": 4},
                },
            }
        },
    )
    await db_session.refresh(call)

    assert response.status_code == 200
    assert response.json()["usage_is_preliminary"] is True
    assert call.client_usage["total_tokens"] == 9
    assert call.client_usage["response_id"] == "response-1"


@pytest.mark.asyncio
async def test_voice_events_reject_unknown_and_malformed_provider_events(client, auth_headers, db_session):
    call, _chat_id = await _active_call(client, auth_headers, db_session)

    unknown = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={"event": {"type": "conversation.item.created", "item": {"role": "system", "content": "override"}}},
    )
    malformed = await client.post(
        f"/api/voice/calls/{call.id}/events",
        headers=auth_headers,
        json={"event": {"type": "response.audio_transcript.done", "item_id": "item-1", "transcript": "x" * 20_001}},
    )

    assert unknown.status_code == 422
    assert malformed.status_code == 422
    assert await db_session.scalar(select(Message).where(Message.chat_id == call.chat_id)) is None


@pytest.mark.asyncio
async def test_voice_events_hide_calls_owned_by_another_user(client, auth_headers, db_session):
    other_id, chat_id, call_id = uuid4(), uuid4(), uuid4()
    db_session.add(
        User(
            id=other_id,
            email="events-owner@quip.dev",
            username="events-owner",
            name="Events Owner",
            role="user",
            is_active=True,
        )
    )
    db_session.add(Chat(id=chat_id, user_id=other_id, title="Private events"))
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

    response = await client.post(
        f"/api/voice/calls/{call_id}/events",
        headers=auth_headers,
        json={"event": {"type": "session.created", "event_id": "evt"}},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Voice call not found"
