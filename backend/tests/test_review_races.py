import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql.dml import Update
from test_chat_runs import make_run

from quip.models.chat import ChatRun
from quip.services.chat_runs import (
    _finish_run,
    _refresh_runner_lease,
    read_run,
    request_run_cancel,
    update_run_snapshot,
)


def blocked_factory(bind, entered, release):
    class BlockedSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "chat_runs":
                entered.set()
                await release.wait()
            return await super().execute(statement, *args, **kwargs)

    return async_sessionmaker(bind, class_=BlockedSession, expire_on_commit=False)


async def state(factory, spec):
    return await read_run(factory, run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)


@pytest.mark.asyncio
async def test_snapshot_updates_keep_both_concurrent_fields(db_session):
    spec = await make_run(db_session, status="running")
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    slow = asyncio.create_task(
        update_run_snapshot(
            blocked_factory(db_session.bind, entered, release),
            run_id=spec.run_id,
            patch={"sources": [{"url": "https://example.org", "title": "real source"}]},
        )
    )
    await entered.wait()
    await update_run_snapshot(factory, run_id=spec.run_id, patch={"errors": [{"message": "agent failed"}]})
    release.set()
    await slow
    actual = await state(factory, spec)
    assert actual["snapshot"].get("errors") == [{"message": "agent failed"}]
    assert actual["revision"] == 2


@pytest.mark.asyncio
async def test_heartbeat_keeps_new_snapshot_and_revision(db_session):
    spec = await make_run(db_session, status="running")
    run = await db_session.get(ChatRun, spec.run_id)
    run.run_metadata = {**run.run_metadata, "runner_owner_id": "live-owner"}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()
    slow = asyncio.create_task(
        _refresh_runner_lease(
            blocked_factory(db_session.bind, entered, release), run_id=spec.run_id, owner_id="live-owner"
        )
    )
    await entered.wait()
    await update_run_snapshot(factory, run_id=spec.run_id, patch={"errors": [{"message": "visible failure"}]})
    release.set()
    await slow
    actual = await state(factory, spec)
    assert actual["snapshot"].get("errors") == [{"message": "visible failure"}]
    assert actual["revision"] == 1


@pytest.mark.asyncio
async def test_finish_honors_remote_stop_accepted_before_terminal_write(db_session):
    spec = await make_run(db_session, status="running")
    run = await db_session.get(ChatRun, spec.run_id)
    run.run_metadata = {**run.run_metadata, "runner_owner_id": "live-owner"}
    await db_session.commit()
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entered, release = asyncio.Event(), asyncio.Event()

    class BlockedGetSession(AsyncSession):
        async def get(self, *args, **kwargs):
            result = await super().get(*args, **kwargs)
            entered.set()
            await release.wait()
            return result

    slow_factory = async_sessionmaker(db_session.bind, class_=BlockedGetSession, expire_on_commit=False)
    slow = asyncio.create_task(
        _finish_run(
            slow_factory,
            run_id=spec.run_id,
            status="completed",
            error=None,
            runner_owner_id="live-owner",
        )
    )
    await entered.wait()
    accepted = await request_run_cancel(
        factory,
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    )
    release.set()
    await slow
    actual = await state(factory, spec)
    assert accepted
    assert actual["status"] == "cancelled"
    assert actual["cancel_requested"] is True
