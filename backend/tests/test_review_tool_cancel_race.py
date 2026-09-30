import asyncio
import json
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Chat
from quip.models.voice import VoiceCall, VoiceToolCall
from quip.services.voice import tools


@pytest.mark.asyncio
async def test_cancel_accepted_before_tool_task_registration_prevents_external_work(client, auth_headers, db_session, monkeypatch):
    created = await client.post('/api/chats', headers=auth_headers, json={'title':'Cancel race'})
    chat = await db_session.get(Chat, UUID(created.json()['id']))
    call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model='fixture', status='active')
    db_session.add(call)
    await db_session.commit()
    registered, release = asyncio.Event(), asyncio.Event()
    original_get = AsyncSession.get
    calls = []

    class RemoteProcessRegistry(dict):
        def __setitem__(self, _key, _value):
            # The cancel request may reach another server process.
            return None

    monkeypatch.setattr(tools, "_active_voice_tool_tasks", RemoteProcessRegistry())

    async def paused_get(self, model, ident, *args, **kwargs):
        result = await original_get(self, model, ident, *args, **kwargs)
        if model is VoiceToolCall:
            registered.set()
            await asyncio.wait_for(release.wait(), 3)
        return result

    async def fake_work(name, args):
        calls.append((name,args))
        return {'status':'completed','error_code':None,'result':{'content':'fixture'}}

    monkeypatch.setattr(AsyncSession,'get',paused_get)
    monkeypatch.setattr(tools,'run_voice_web_tool',fake_work)
    running=asyncio.create_task(client.post(f'/api/voice/calls/{call.id}/tools',headers=auth_headers,json={
        'provider_call_id':'cancel-before-work','name':'read_url','arguments':json.dumps({'url':'https://example.org'}),
    }))
    await asyncio.wait_for(registered.wait(),3)
    cancelled=await client.post(f'/api/voice/calls/{call.id}/tools/cancel-before-work/cancel',headers=auth_headers)
    assert cancelled.status_code==200
    release.set()
    result=await running
    assert not calls
    assert result.json()["status"] == "cancelled"
