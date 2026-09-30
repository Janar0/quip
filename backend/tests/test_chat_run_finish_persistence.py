import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_chat_runs import make_run

from quip.database import Base
from quip.services import chat_runs
from quip.services.chat_runs import ChatRunManager, RunOutcome, read_run


@pytest.fixture
async def file_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'finish-failure.db'}", connect_args={"timeout": 5})

    @event.listens_for(engine.sync_engine, "connect")
    def configure(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.asyncio
async def test_completed_handshake_does_not_report_success_after_both_message_writes_fail(file_factory):
    async with file_factory() as db:
        spec = await make_run(db)
    failures = []

    engine = file_factory.kw['bind'].sync_engine
    def fail_message_update(_connection, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().lower().startswith('update messages'):
            failures.append(True)
            raise OperationalError('UPDATE messages', {}, RuntimeError('local simulated message write failure'))
    event.listen(engine, 'before_cursor_execute', fail_message_update)
    manager = ChatRunManager(file_factory, runner_mode='single_process')
    final_text = 'This completed answer must survive reload.'

    async def worker(context):
        context.report = final_text
        decision = await context.try_finish(expected_context_version=1, status='completed', error=None)
        assert decision.accepted
        return RunOutcome(status='completed')

    subscription = await manager.start(spec, worker)
    try:
        events = [event async for event in subscription]
        result = await read_run(file_factory, run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)
        assert len(failures) >= 2
        assert result['status'] in {'failed', 'partial'}
        assert result['error']
        assert result['message']['content'] != final_text
        assert any(item['type'] == 'error' for item in events)
        assert any(item['type'] == 'run_status' and item['data']['status'] in {'failed', 'partial'} for item in events)
    finally:
        await manager.close()
        event.remove(engine, 'before_cursor_execute', fail_message_update)


@pytest.mark.asyncio
async def test_finalization_failure_does_not_leave_uncancellable_running_orphan(file_factory, monkeypatch):
    async with file_factory() as db:
        spec = await make_run(db)
    manager = ChatRunManager(file_factory, runner_mode='single_process')

    async def worker(context):
        context.report = 'Persist this work.'
        decision = await context.try_finish(expected_context_version=1, status='completed', error=None)
        assert decision.accepted
        return RunOutcome(status='completed')

    async def fail_terminal_commit(*args, **kwargs):
        raise OperationalError('UPDATE chat_runs', {}, RuntimeError('local simulated terminal write failure'))

    recover_finalization = chat_runs._recover_failed_run_finalization
    recovery_attempts = 0

    async def fail_first_recovery(*args, **kwargs):
        nonlocal recovery_attempts
        recovery_attempts += 1
        if recovery_attempts == 1:
            raise OperationalError('UPDATE chat_runs', {}, RuntimeError('local simulated recovery write failure'))
        return await recover_finalization(*args, **kwargs)

    monkeypatch.setattr(chat_runs, '_finish_run', fail_terminal_commit)
    monkeypatch.setattr(chat_runs, '_recover_failed_run_finalization', fail_first_recovery)
    subscription = await manager.start(spec, worker)
    try:
        events = [event async for event in subscription]
        pending = await read_run(file_factory, run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)
        assert pending['status'] == 'running'
        assert pending['message']['content'] == 'Persist this work.'
        assert await manager.request_cancel(
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        ) is True
        result = await read_run(file_factory, run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)
        assert result['status'] == 'cancelled'
        assert result['error']
        assert manager._tasks == {}
        assert any(item['type'] == 'error' for item in events)
        assert recovery_attempts == 2
    finally:
        await manager.close()
