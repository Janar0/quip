import asyncio
import json
from copy import deepcopy
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core import config
from quip.models.budget import Budget
from quip.models.chat import Chat
from quip.models.usage import UsageLog
from quip.models.user import User
from quip.models.voice import VoiceCall, VoiceToolCall
from quip.providers.types import ToolCallDelta
from quip.services.voice import tasks, tools


def configure_voice(monkeypatch):
    for key, value in {
        'qwen_voice_enabled': 'true',
        'qwen_realtime_endpoint': 'https://realtime.example.test/v1/realtime',
        'qwen_realtime_api_key': 'fake-key',
        'qwen_realtime_model': 'fixture-model',
    }.items():
        monkeypatch.setitem(config._settings, key, value)


async def setup_chat(client, auth_headers, db_session):
    response = await client.post('/api/chats', headers=auth_headers, json={'title': 'Review'})
    chat_id = UUID(response.json()['id'])
    return await db_session.get(Chat, chat_id)


@pytest.mark.asyncio
async def test_voice_start_respects_exhausted_known_budget(client, auth_headers, db_session, app_session_factory, monkeypatch):
    from quip.routers import voice
    from quip.services.completion import service

    configure_voice(monkeypatch)
    chat = await setup_chat(client, auth_headers, db_session)
    user = await db_session.get(User, chat.user_id)
    db_session.add(Budget(user_id=user.id, period='daily', limit_usd=1))
    db_session.add(UsageLog(user_id=user.id, chat_id=chat.id, model='fixture', provider='openrouter', cost=2))
    await db_session.commit()
    monkeypatch.setattr(service, 'async_session', app_session_factory)
    with pytest.raises(HTTPException) as rejected:
        await service._check_budget(user, db_session)
    assert rejected.value.status_code == 429
    exchanges = []

    async def exchange(*_args):
        exchanges.append(True)
        return 'v=0\r\n'

    monkeypatch.setattr(voice, 'exchange_sdp', exchange)
    response = await client.post('/api/voice/calls', headers=auth_headers, json={'chat_id': str(chat.id), 'sdp': 'v=0', 'type': 'offer'})
    print('BUDGET', response.status_code, 'provider_exchanges', len(exchanges))
    assert response.status_code == 429
    assert not exchanges


@pytest.mark.asyncio
async def test_concurrent_voice_tools_preserve_one_pending_limit(client, auth_headers, db_session, monkeypatch):
    chat = await setup_chat(client, auth_headers, db_session)
    call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model='fixture', status='active')
    db_session.add(call)
    await db_session.commit()
    active = 0
    max_active = 0

    async def fake_tool(*_args):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        return {'status': 'completed', 'error_code': None, 'result': {'content': 'fixture'}}

    monkeypatch.setattr(tools, 'run_voice_web_tool', fake_tool)
    responses = await asyncio.gather(*[
        client.post(f'/api/voice/calls/{call.id}/tools', headers=auth_headers, json={
            'provider_call_id': f'provider-{i}', 'name': 'read_url', 'arguments': json.dumps({'url': 'https://example.org'})
        }) for i in range(2)
    ])
    print('TOOL_ADMISSION', [response.status_code for response in responses], 'max_active', max_active)
    assert max_active == 1


@pytest.mark.asyncio
async def test_atomic_voice_tool_and_search_ceilings_at_last_slot(client, auth_headers, db_session, monkeypatch):
    chat = await setup_chat(client, auth_headers, db_session)
    total_call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model='fixture', status='active')
    db_session.add(total_call)
    await db_session.flush()
    db_session.add_all([
        VoiceToolCall(
            voice_call_id=total_call.id, provider_call_id=f'total-{index}', function_name='read_url',
            arguments_hash='x' * 64, status='completed', admission_slot=index,
        )
        for index in range(9)
    ])
    await db_session.commit()
    monkeypatch.setattr(tools, '_check_search_gate', lambda: asyncio.sleep(0))

    async def fake_tool(*_args):
        await asyncio.sleep(0.03)
        return {'status': 'completed', 'error_code': None, 'result': {'content': 'fixture'}}

    monkeypatch.setattr(tools, 'run_voice_web_tool', fake_tool)
    total_responses = await asyncio.gather(*[
        client.post(f'/api/voice/calls/{total_call.id}/tools', headers=auth_headers, json={
            'provider_call_id': f'last-total-{index}', 'name': 'read_url', 'arguments': json.dumps({'url': 'https://example.org'})
        }) for index in range(2)
    ])
    total_call.status = 'ended'
    await db_session.commit()
    search_call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model='fixture', status='active')
    db_session.add(search_call)
    await db_session.flush()
    db_session.add_all([
        VoiceToolCall(
            voice_call_id=search_call.id, provider_call_id=f'search-{index}', function_name='web_search',
            arguments_hash='x' * 64, status='completed', admission_slot=index, search_slot=index,
        )
        for index in range(4)
    ])
    await db_session.commit()
    search_responses = await asyncio.gather(*[
        client.post(f'/api/voice/calls/{search_call.id}/tools', headers=auth_headers, json={
            'provider_call_id': f'last-search-{index}', 'name': 'web_search', 'arguments': json.dumps({'query': 'fixture query'})
        }) for index in range(2)
    ])
    observed = {
        'total_slots': sorted(response.status_code for response in total_responses),
        'search_slots': sorted(response.status_code for response in search_responses),
    }
    print('TOOL_LIMIT_RACES', observed)
    assert observed == {'total_slots': [200, 429], 'search_slots': [200, 429]}


@pytest.mark.asyncio
async def test_concurrent_voice_start_preserves_one_active_call(client, auth_headers, db_session, monkeypatch):
    from quip.routers import voice

    configure_voice(monkeypatch)
    chat = await setup_chat(client, auth_headers, db_session)
    original_execute = AsyncSession.execute
    admissions = 0
    both_read = asyncio.Event()

    async def barrier_execute(self, statement, *args, **kwargs):
        nonlocal admissions
        result = await original_execute(self, statement, *args, **kwargs)
        if statement.column_descriptions[0].get('entity') is VoiceCall:
            admissions += 1
            if admissions == 2:
                both_read.set()
            await asyncio.wait_for(both_read.wait(), 3)
        return result

    monkeypatch.setattr(AsyncSession, 'execute', barrier_execute)
    exchanges = []

    async def exchange(*_args):
        exchanges.append(True)
        return 'v=0\r\n'

    monkeypatch.setattr(voice, 'exchange_sdp', exchange)
    responses = await asyncio.gather(*[
        client.post('/api/voice/calls', headers=auth_headers, json={'chat_id': str(chat.id), 'sdp': 'v=0', 'type': 'offer'}) for _ in range(2)
    ])
    print('CALL_ADMISSION', [response.status_code for response in responses], 'provider_exchanges', len(exchanges))
    assert len(exchanges) == 1


@pytest.mark.asyncio
async def test_luna_each_completion_preserves_context_cap(monkeypatch):
    seen = []

    async def build_context(*_args):
        return [{'role': 'system', 'content': 'fixture'}, {'role': 'user', 'content': 'fixture goal'}], 1

    class FakeCompletion:
        @staticmethod
        async def stream_selected_model(messages, *_args, **_kwargs):
            seen.append(deepcopy(messages))
            if len(seen) <= 4:
                yield ('tool_calls', [ToolCallDelta(index=0, id=f'tool-{len(seen)}', function_name='read_url', function_arguments='{"url":"https://example.org"}')])
            else:
                yield 'event: content\ndata: {"text":"Done"}\n\n'

    async def fake_tool(*_args):
        return {'status': 'completed', 'result': {'content': 'x' * 7900}}

    class Execution:
        cancel_event = asyncio.Event()

        async def take_steering(self):
            return []

        async def update_snapshot(self, **_kwargs):
            pass

        async def emit(self, *_args):
            pass

        async def append_result(self, *_args):
            pass

        async def flush_result(self):
            pass

    monkeypatch.setattr(tasks, '_build_task_messages', build_context)
    monkeypatch.setattr(tasks, 'CompletionService', FakeCompletion)
    monkeypatch.setattr(tasks, 'run_voice_web_tool', fake_tool)
    spec = tasks.ChatRunSpec(run_id=uuid4(), chat_id=uuid4(), user_id=uuid4(), assistant_message_id=uuid4(), task_kind='voice_delegation')
    await tasks.run_luna_task(Execution(), spec=spec, model_id='fixture-luna', goal='Read pages')
    estimates = [sum(tasks.estimate_tokens(message.get('content', '')) for message in messages) for messages in seen]
    print('LUNA_CONTEXT_ESTIMATES', estimates)
    assert max(estimates) <= tasks.MAX_CONTEXT_TOKENS


@pytest.mark.asyncio
async def test_accepted_finalization_steering_is_not_ignored(client, auth_headers, db_session, app_session_factory, monkeypatch):
    from quip.main import app
    from quip.models.chat import ChatRun
    from quip.services.chat_runs import ChatRunManager, RunExecutionContext, read_run

    chat = await setup_chat(client, auth_headers, db_session)
    call = VoiceCall(user_id=chat.user_id, chat_id=chat.id, model='fixture', status='active')
    db_session.add(call)
    await db_session.commit()
    monkeypatch.setattr(tasks, 'get_cached_models', lambda: [{'id': 'fixture/luna', 'name': 'Luna', 'provider': 'openrouter', 'supports_tools': True}])
    monkeypatch.setitem(config._settings, 'openrouter_api_key', 'fake-key')

    async def build_context(*_args):
        clarifications = _args[-1]
        return [{'role': 'user', 'content': 'Old goal\n' + '\n'.join(clarifications)}], 1

    completion_calls = []

    class FakeCompletion:
        @staticmethod
        async def stream_selected_model(*_args, **_kwargs):
            completion_calls.append(_args[0])
            response = "Old unsteered answer" if len(completion_calls) == 1 else "Updated answer after clarification"
            yield f'event: content\ndata: {{"text":{json.dumps(response)}}}\n\n'

    monkeypatch.setattr(tasks, '_build_task_messages', build_context)
    monkeypatch.setattr(tasks, 'CompletionService', FakeCompletion)
    finalizing = asyncio.Event()
    release = asyncio.Event()
    original_append = RunExecutionContext.append_result

    async def paused_append(self, text):
        finalizing.set()
        await asyncio.wait_for(release.wait(), 3)
        await original_append(self, text)

    monkeypatch.setattr(RunExecutionContext, 'append_result', paused_append)
    manager = ChatRunManager(app_session_factory, runner_mode='single_process')
    app.state.chat_run_manager = manager
    try:
        started = await client.post(f'/api/voice/calls/{call.id}/tasks', headers=auth_headers, json={'provider_call_id': 'delegate-review', 'goal': 'Old goal'})
        task_id = UUID(started.json()['task_id'])
        await asyncio.wait_for(finalizing.wait(), 3)
        current = await read_run(app_session_factory, run_id=task_id, chat_id=chat.id, user_id=chat.user_id)
        steered = await client.post(f'/api/voice/calls/{call.id}/tasks/{task_id}/steer', headers=auth_headers, json={
            'expected_revision': current['revision'], 'idempotency_key': 'late-review', 'instruction': 'Use the NEW goal instead',
        })
        assert steered.status_code == 200, steered.text
        release.set()
        await asyncio.gather(*list(manager._tasks.values()))
        result = await read_run(app_session_factory, run_id=task_id, chat_id=chat.id, user_id=chat.user_id)
        async with app_session_factory() as verify_db:
            run = await verify_db.get(ChatRun, task_id)
            pending = run.run_metadata['steering']
        print('LATE_STEERING', 'accepted', steered.status_code, 'status', result['status'], 'content', result['message']['content'], 'unconsumed', len(pending))
        assert not (result['status'] == 'completed' and pending)
        assert len(completion_calls) == 2
        assert result['message']['content'] == "Updated answer after clarification"
        assert any("NEW goal" in message[0]["content"] for message in completion_calls[1:])
    finally:
        release.set()
        await manager.close()
        del app.state.chat_run_manager


@pytest.mark.asyncio
async def test_older_relevant_fact_remains_retrievable(client, auth_headers, db_session):
    from datetime import UTC, datetime, timedelta

    from quip.models.chat import Message
    from quip.services.voice.context import VoiceContextService

    chat = await setup_chat(client, auth_headers, db_session)
    user = await db_session.get(User, chat.user_id)
    start = datetime.now(UTC) - timedelta(days=1)
    db_session.add(Message(chat_id=chat.id, role='user', content='Important decision: the approved codename is Amber Heron.', created_at=start))
    db_session.add_all([Message(chat_id=chat.id, role='user', content=f'Unrelated ordinary turn {i}', created_at=start + timedelta(seconds=i + 1)) for i in range(500)])
    await db_session.commit()
    packet = await VoiceContextService().build_task_context(db_session, user, chat, 'What was the approved codename Amber Heron?')
    carried = packet.summary + '\n' + '\n'.join(item.text for item in (*packet.recent, *packet.retrieved))
    print('OLDER_FACT', 'source_fact_found', 'Amber Heron' in carried, 'retrieved', len(packet.retrieved))
    assert 'Amber Heron' in carried
