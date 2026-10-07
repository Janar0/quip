import asyncio
import json
from uuid import UUID

import pytest

from quip.models.chat import Chat
from quip.models.voice import VoiceCall
from quip.services.voice import tools


@pytest.mark.asyncio
async def test_durable_cancel_before_tool_registration_prevents_external_work(
    client, auth_headers, db_session, monkeypatch
):
    created = await client.post("/api/chats", headers=auth_headers, json={"title": "Cancel race"})
    chat = await db_session.get(Chat, UUID(created.json()["id"]))
    call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model="fixture", status="active")
    db_session.add(call)
    await db_session.commit()
    reservation_committed, release = asyncio.Event(), asyncio.Event()
    calls = []
    original_commit_reservation = tools._commit_voice_tool_reservation

    class RemoteProcessRegistry(dict):
        def __setitem__(self, _key, _value):
            # The cancel request may reach another server process.
            return None

    monkeypatch.setattr(tools, "_active_voice_tool_tasks", RemoteProcessRegistry())

    async def paused_reservation(db):
        await original_commit_reservation(db)
        reservation_committed.set()
        await asyncio.wait_for(release.wait(), 3)

    async def fake_work(name, args):
        calls.append((name, args))
        return {"status": "completed", "error_code": None, "result": {"content": "fixture"}}

    monkeypatch.setattr(tools, "_commit_voice_tool_reservation", paused_reservation)
    monkeypatch.setattr(tools, "run_voice_web_tool", fake_work)
    running = asyncio.create_task(
        client.post(
            f"/api/voice/calls/{call.id}/tools",
            headers=auth_headers,
            json={
                "provider_call_id": "cancel-before-work",
                "name": "read_url",
                "arguments": json.dumps({"url": "https://example.org"}),
            },
        )
    )
    await asyncio.wait_for(reservation_committed.wait(), 3)
    cancelled = await client.post(
        f"/api/voice/calls/{call.id}/tools/cancel-before-work/cancel",
        headers=auth_headers,
    )
    assert cancelled.status_code == 200
    release.set()
    result = await running
    assert not calls
    assert result.json()["status"] == "cancelled"
