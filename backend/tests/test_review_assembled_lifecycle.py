import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_chat_run_finish_persistence import file_factory as file_factory_fixture  # noqa: F401

from quip.core.config import set_setting
from quip.database import get_db
from quip.models.chat import Chat
from quip.models.voice import VoiceCall
from quip.providers.types import StreamChunk, UsageInfo
from quip.services.chat_runs import read_run


@pytest.mark.asyncio
async def test_assembled_lifespan_shares_research_and_luna_runner_and_persists_results(
    client, file_factory_fixture, monkeypatch  # noqa: F811
):
    import quip.database as database
    import quip.main as main
    import quip.routers.models as models
    import quip.services.skill_store as skill_store
    from quip.services.completion.stream import StreamOrchestrator

    original_skill_cache = dict(skill_store._skills_cache)

    async def owned_test_db():
        async with file_factory_fixture() as db:
            yield db

    main.app.dependency_overrides[get_db] = owned_test_db
    monkeypatch.setenv('AUTO_MIGRATE', 'false')
    monkeypatch.setattr(main, 'load_settings', AsyncMock())
    monkeypatch.setattr(main, 'run_migration_if_needed', AsyncMock())
    monkeypatch.setattr(database, 'async_session', file_factory_fixture)
    monkeypatch.setattr(skill_store, 'async_session', file_factory_fixture)
    dispose = AsyncMock()
    monkeypatch.setattr(main, 'engine', SimpleNamespace(dispose=dispose))
    telegram = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())
    monkeypatch.setattr(main, 'TelegramBotService', lambda: telegram)

    async def quiet_cleanup():
        await asyncio.Event().wait()

    monkeypatch.setattr(main, 'sandbox_cleanup_loop', quiet_cleanup)
    model_id = 'fixture/luna-current-catalog'
    monkeypatch.setitem(models._cache, 'openrouter', (time.time(), [{
        'id': model_id, 'name': 'Luna Fixture', 'provider': 'openrouter',
        'context_length': 32000, 'supports_tools': True,
        'pricing': {'prompt': '0', 'completion': '0'},
    }]))
    for key, value in {
        'research_runner_mode': 'single_process', 'research_enabled': 'true',
        'openrouter_api_key': 'fixture-only-key', 'rag_enabled': 'false',
        'sandbox_enabled': 'false', 'tool_gating_enabled': 'false',
    }.items():
        set_setting(key, value)

    registered = await client.post('/api/auth/register', json={
        'email': 'assembled@fixture.dev', 'username': 'assembled',
        'name': 'Assembled review', 'password': 'password123',
        'bootstrap_token': 'test-bootstrap-token',
    })
    assert registered.status_code == 201
    headers = {'Authorization': f"Bearer {registered.json()['access_token']}"}
    created = await client.post('/api/chats', headers=headers, json={'title': 'Assembled review'})
    assert created.status_code == 201, created.text
    chat_id = UUID(created.json()['id'])
    async with file_factory_fixture() as db:
        chat = await db.get(Chat, chat_id)
        user_id = chat.user_id
        call = VoiceCall(user_id=user_id, chat_id=chat_id, model='qwen-audio-3.1-realtime-plus', status='active')
        db.add(call)
        await db.commit()
        call_id = call.id

    research_entered, release_research = asyncio.Event(), asyncio.Event()
    luna_entered, release_luna = asyncio.Event(), asyncio.Event()
    provider_observations = []

    async def fixture_research(context, **_kwargs):
        await context.append_result('Research partial retained.')
        research_entered.set()
        await release_research.wait()
        return {'status': 'completed'}

    def fixture_provider(orchestrator, tools):
        provider_observations.append((orchestrator.model, orchestrator.max_tokens, tools))

        async def stream():
            luna_entered.set()
            await release_luna.wait()
            yield StreamChunk(content='Luna final from the actual completion seam.', finish_reason='stop')
            yield StreamChunk(usage=UsageInfo(prompt_tokens=10, completion_tokens=8, provider='openrouter'))

        return stream()

    monkeypatch.setattr(StreamOrchestrator, '_call_provider', fixture_provider)

    async def wait_terminal(run_id):
        while True:
            state = await read_run(file_factory_fixture, run_id=run_id, chat_id=chat_id, user_id=user_id)
            if state and state['status'] in {'completed', 'cancelled', 'failed', 'partial', 'interrupted'}:
                return state
            await asyncio.sleep(0.01)

    request_task = None
    manager = None
    try:
        async with main.lifespan(main.app):
            manager = main.app.state.chat_run_manager
            assert manager.runner_mode == 'single_process'
            assert main.app.state.research_run_manager.task_manager is manager
            main.app.state.research_run_manager.runner = fixture_research

            request_task = asyncio.create_task(client.post('/api/chat/completions', headers=headers, json={
                'chat_id': str(chat_id), 'model': model_id, 'message': 'Research this', 'mode_hint': 'research',
            }))
            await asyncio.wait_for(research_entered.wait(), 5)
            request_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await request_task
            assert len(manager._tasks) == 1
            research_run_id = next(iter(manager._tasks))

            started = await client.post(f'/api/voice/calls/{call_id}/tasks', headers=headers, json={
                'provider_call_id': 'assembled-handoff', 'goal': 'Return the latest evidence',
            })
            assert started.status_code == 202, started.text
            luna_run_id = UUID(started.json()['task_id'])
            await asyncio.wait_for(luna_entered.wait(), 5)
            assert set(manager._tasks) == {research_run_id, luna_run_id}

            ended = await client.post(f'/api/voice/calls/{call_id}/end', headers=headers)
            assert ended.status_code == 200
            luna_before_end = await read_run(file_factory_fixture, run_id=luna_run_id, chat_id=chat_id, user_id=user_id)
            assert luna_before_end['status'] == 'running'
            assert not luna_before_end['cancel_requested']
            release_luna.set()
            luna_final = await asyncio.wait_for(wait_terminal(luna_run_id), 5)
            assert luna_final['status'] == 'completed', luna_final
            assert luna_final['message']['content'] == 'Luna final from the actual completion seam.'
            assert luna_final['task_kind'] == 'voice_delegation'
            assert provider_observations[0][:2] == (model_id, 1200)
            assert {tool['function']['name'] for tool in provider_observations[0][2]} == {'read_url', 'web_search'}

            stopped = await client.post(f'/api/chats/{chat_id}/runs/{research_run_id}/cancel', headers=headers)
            assert stopped.status_code == 200
            research_final = await asyncio.wait_for(wait_terminal(research_run_id), 5)
            assert research_final['status'] == 'cancelled'
            assert research_final['message']['content'] == 'Research partial retained.'

        assert manager._closing
        assert not manager._tasks
        telegram.start.assert_awaited_once()
        telegram.stop.assert_awaited_once()
        dispose.assert_awaited_once()
    finally:
        release_research.set()
        release_luna.set()
        if request_task and not request_task.done():
            request_task.cancel()
            await asyncio.gather(request_task, return_exceptions=True)
        skill_store._skills_cache.clear()
        skill_store._skills_cache.update(original_skill_cache)
