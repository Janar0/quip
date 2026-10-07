import pytest
from test_chat_run_finish_persistence import file_factory  # noqa: F401
from test_chat_runs import make_run

from quip.services import chat_runs
from quip.services.chat_runs import ChatRunManager, RunOutcome, read_run


@pytest.mark.asyncio
async def test_stop_can_retry_when_storage_recovers_after_the_first_stop(file_factory, monkeypatch):  # noqa: F811
    async with file_factory() as db:
        spec = await make_run(db)
    manager = ChatRunManager(file_factory, runner_mode="single_process")
    normal_finish = chat_runs._finish_run
    normal_recover = chat_runs._recover_failed_run_finalization

    async def unavailable(*_args, **_kwargs):
        raise OSError("simulated persistent terminal-storage failure")

    monkeypatch.setattr(chat_runs, "_finish_run", unavailable)
    monkeypatch.setattr(chat_runs, "_recover_failed_run_finalization", unavailable)

    async def worker(context):
        context.report = "Keep this report."
        decision = await context.try_finish(expected_context_version=1, status="completed", error=None)
        assert decision.accepted
        return RunOutcome(status="completed")

    subscription = await manager.start(spec, worker)
    try:
        events = [event async for event in subscription]
        assert any(event["type"] == "error" for event in events)
        first_stop = await manager.request_cancel(
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert first_stop
        before_recovery = await read_run(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert before_recovery["status"] == "cancelling"
        assert manager._tasks == {}
        assert spec.run_id in manager._finalization_failures
        assert not await chat_runs.request_run_cancel(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert not await chat_runs.request_run_cancel(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
            allow_finalization_retry_owner_id="another-runner",
        )
        monkeypatch.setattr(chat_runs, "_finish_run", normal_finish)
        monkeypatch.setattr(chat_runs, "_recover_failed_run_finalization", normal_recover)
        second_stop = await manager.request_cancel(
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        after_recovery = await read_run(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert second_stop
        assert after_recovery["status"] == "cancelled"
        assert manager._tasks == {}
        assert spec.run_id not in manager._finalization_failures
    finally:
        await manager.close()
