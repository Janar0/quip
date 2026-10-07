import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.sql.dml import Update
from test_chat_runs import make_run

from quip.database import Base
from quip.models.chat import ChatRun
from quip.services.chat_runs import (
    ChatRunManager,
    RunExecutionContext,
    RunOutcome,
    _finish_run,
    enqueue_run_steering,
    interrupt_active_runs,
    read_run,
    request_run_cancel,
)


@pytest.fixture
async def file_factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'review.db'}", connect_args={"timeout": 5})

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


@pytest.mark.parametrize("terminal_status", ["completed", "partial", "failed", "cancelled", "interrupted"])
@pytest.mark.asyncio
async def test_recovery_cannot_overwrite_terminal_run_after_conflict_retry(file_factory, terminal_status):
    async with file_factory() as db:
        spec = await make_run(db, status="running")
        run = await db.get(ChatRun, spec.run_id)
        run.run_metadata = {
            **run.run_metadata,
            "runner_owner_id": "late-owner",
            "runner_heartbeat_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
        }
        await db.commit()
    entered, release = asyncio.Event(), asyncio.Event()
    first_update = True

    class DelayedRecovery(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            nonlocal first_update
            if isinstance(statement, Update) and statement.table.name == "chat_runs" and first_update:
                first_update = False
                entered.set()
                await asyncio.wait_for(release.wait(), 3)
            return await super().execute(statement, *args, **kwargs)

    recovery_factory = async_sessionmaker(file_factory.kw["bind"], class_=DelayedRecovery, expire_on_commit=False)
    recovery = asyncio.create_task(interrupt_active_runs(recovery_factory))
    await asyncio.wait_for(entered.wait(), 3)
    terminal = await _finish_run(
        file_factory,
        run_id=spec.run_id,
        status=terminal_status,
        error=None,
        runner_owner_id="late-owner",
    )
    assert terminal == terminal_status
    release.set()
    count = await recovery
    result = await read_run(file_factory, run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)
    assert result["status"] == terminal_status
    assert count == 0


@pytest.mark.asyncio
async def test_concurrent_same_manager_starts_claim_one_queued_execution(file_factory):
    async with file_factory() as db:
        occupier = await make_run(db)
        target = await make_run(db)
    reads = 0
    second_target_read = asyncio.Event()

    class BarrierClaim(AsyncSession):
        async def get(self, model, ident, *args, **kwargs):
            nonlocal reads
            result = await super().get(model, ident, *args, **kwargs)
            if model is ChatRun and ident == target.run_id:
                # Let the broken implementation expose both pre-claim reads.
                # A serialized start reaches this read only once; it proceeds
                # after a short bounded wait and the second caller sees its task.
                reads += 1
                if reads == 1:
                    try:
                        await asyncio.wait_for(second_target_read.wait(), 0.1)
                    except TimeoutError:
                        pass
                elif reads == 2:
                    second_target_read.set()
            return result

    factory = async_sessionmaker(file_factory.kw["bind"], class_=BarrierClaim, expire_on_commit=False)
    manager = ChatRunManager(factory, runner_mode="single_process", max_concurrent_runs=1)
    worker_entered = asyncio.Event()
    worker_release = asyncio.Event()

    async def hold_slot(_context):
        worker_entered.set()
        await worker_release.wait()
        return RunOutcome(status="completed")

    async def target_worker(context):
        context.report = "Useful completed work"
        return RunOutcome(status="completed")

    occupant_subscription = await manager.start(occupier, hold_slot)
    await asyncio.wait_for(worker_entered.wait(), 3)
    subscriptions = []
    try:
        start_barrier = asyncio.Barrier(2)

        async def start_together():
            await start_barrier.wait()
            return await manager.start(target, target_worker)

        subscriptions = await asyncio.gather(start_together(), start_together())
        target_executions = [task for task in asyncio.all_tasks() if task.get_name() == f"chat-run-{target.run_id}"]
        assert len(target_executions) == 1
        worker_release.set()
        await asyncio.gather(*target_executions)
        result = await read_run(file_factory, run_id=target.run_id, chat_id=target.chat_id, user_id=target.user_id)
        assert result["status"] == "completed"
    finally:
        worker_release.set()
        await manager.close()
        for subscription in subscriptions:
            await subscription.aclose()
        await occupant_subscription.aclose()


@pytest.mark.asyncio
async def test_finish_handshake_returns_steering_accepted_after_workers_last_check(file_factory):
    async with file_factory() as db:
        spec = await make_run(db)
    manager = ChatRunManager(file_factory, runner_mode="single_process")
    checked, continue_to_finish = asyncio.Event(), asyncio.Event()
    finish_accepted, allow_return = asyncio.Event(), asyncio.Event()

    async def worker(context):
        assert await context.take_steering() == []
        context.report = "Report before last-minute steering."
        checked.set()
        await continue_to_finish.wait()

        decision = await context.try_finish(
            expected_context_version=spec.context_version,
            status="completed",
            error=None,
        )
        assert decision.accepted is False
        assert len(decision.steering) == 1
        assert decision.steering[0]["instruction"] == "Include a short limitations section."
        context.report += " Limitations: this is a mocked result."
        await context.flush_result()

        final_decision = await context.try_finish(
            expected_context_version=decision.context_version,
            status="completed",
            error=None,
        )
        assert final_decision.accepted is True
        assert final_decision.status == "completed"
        assert final_decision.steering == []
        finish_accepted.set()
        await allow_return.wait()
        return RunOutcome(status="completed")

    subscription = await manager.start(spec, worker)
    try:
        await asyncio.wait_for(checked.wait(), 3)
        accepted = await enqueue_run_steering(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
            instruction="Include a short limitations section.",
        )
        assert accepted["accepted"] is True
        assert accepted["context_version"] == 2
        continue_to_finish.set()
        await asyncio.wait_for(finish_accepted.wait(), 3)
        rejected = await enqueue_run_steering(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
            instruction="This arrives after finish admission closed.",
        )
        assert rejected["accepted"] is False
        assert (
            await request_run_cancel(
                file_factory,
                run_id=spec.run_id,
                chat_id=spec.chat_id,
                user_id=spec.user_id,
            )
            is False
        )
        allow_return.set()
        async for _ in subscription:
            pass

        result = await read_run(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert result["status"] == "completed"
        assert result["context_version"] == 2
        assert (
            result["message"]["content"] == "Report before last-minute steering. Limitations: this is a mocked result."
        )
        assert result["steering"] == []
    finally:
        continue_to_finish.set()
        allow_return.set()
        await manager.close()
        await subscription.aclose()


@pytest.mark.asyncio
async def test_finish_handshake_preserves_an_accepted_stop(file_factory):
    async with file_factory() as db:
        spec = await make_run(db)
    manager = ChatRunManager(file_factory, runner_mode="single_process")
    try:
        async with file_factory() as db:
            run = await db.get(ChatRun, spec.run_id)
            run.run_metadata = {**run.run_metadata, "runner_owner_id": manager._owner_id}
            await db.commit()
        assert (
            await request_run_cancel(
                file_factory,
                run_id=spec.run_id,
                chat_id=spec.chat_id,
                user_id=spec.user_id,
            )
            is True
        )

        context = RunExecutionContext(manager, spec, asyncio.Event())
        context.report = "Keep this partial report after Stop."
        await context.flush_result()
        decision = await context.try_finish(
            expected_context_version=spec.context_version,
            status="completed",
            error=None,
        )
        assert decision.accepted is True
        assert decision.status == "cancelled"
        assert (
            await _finish_run(
                file_factory,
                run_id=spec.run_id,
                status="completed",
                error=None,
                runner_owner_id=manager._owner_id,
            )
        ) == "cancelled"
        result = await read_run(
            file_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
        )
        assert result["status"] == "cancelled"
        assert result["message"]["content"] == "Keep this partial report after Stop."
    finally:
        await manager.close()


@pytest.mark.parametrize(
    "regression_name",
    [
        "test_snapshot_updates_keep_both_concurrent_fields",
        "test_heartbeat_keeps_new_snapshot_and_revision",
        "test_finish_honors_remote_stop_accepted_before_terminal_write",
    ],
)
@pytest.mark.asyncio
async def test_original_metadata_regression_on_file_backed_database(file_factory, regression_name):
    import test_review_races

    async with file_factory() as db:
        await getattr(test_review_races, regression_name)(db)
