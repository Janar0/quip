import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from quip.models.chat import Chat, ChatRun, Message
from quip.models.user import User
from quip.services.chat_runs import (
    ChatRunManager,
    ChatRunSpec,
    RunOutcome,
    enqueue_run_steering,
    read_run,
)


async def make_run(db_session, *, status="queued", task_kind="research"):
    user = User(email=f"{uuid4()}@test.dev", username=f"u-{uuid4().hex[:12]}", name="Tester")
    db_session.add(user)
    await db_session.flush()
    chat = Chat(user_id=user.id, title="Research test")
    db_session.add(chat)
    await db_session.flush()
    message = Message(chat_id=chat.id, role="assistant", content="", model="mock")
    db_session.add(message)
    await db_session.flush()
    run = ChatRun(
        chat_id=chat.id,
        user_id=user.id,
        assistant_message_id=message.id,
        status=status,
        model="mock",
        run_metadata={
            "schema_version": 1,
            "task_kind": task_kind,
            "revision": 0,
            "context_version": 1,
            "cancel_requested": False,
            "steering": [],
            "snapshot": {},
        },
    )
    db_session.add(run)
    await db_session.commit()
    return ChatRunSpec(
        run_id=run.id,
        chat_id=chat.id,
        user_id=user.id,
        assistant_message_id=message.id,
        task_kind=task_kind,
    )


async def wait_for_terminal(db_session, run_id, timeout=2.0):
    async def wait():
        while True:
            db_session.expire_all()
            run = await db_session.get(ChatRun, run_id)
            if run and run.status in {"completed", "partial", "failed", "cancelled", "interrupted"}:
                return run
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(wait(), timeout)


@pytest.mark.asyncio
async def test_disconnect_detaches_only_the_subscriber(db_session):
    spec = await make_run(db_session)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def worker(context):
        nonlocal calls
        calls += 1
        entered.set()
        await context.append_result("Saved after the browser leaves.")
        await release.wait()
        return RunOutcome(status="completed")

    manager = ChatRunManager(session_factory, runner_mode="single_process")
    subscription = await manager.start(spec, worker)
    await asyncio.wait_for(entered.wait(), 1)
    await subscription.aclose()
    release.set()
    await wait_for_terminal(db_session, spec.run_id)

    persisted = await read_run(
        session_factory,
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    )
    assert calls == 1
    assert persisted["status"] == "completed"
    assert persisted["message"]["content"] == "Saved after the browser leaves."
    await manager.close()


@pytest.mark.asyncio
async def test_partial_result_sources_and_progress_are_persisted(db_session):
    spec = await make_run(db_session)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def worker(context):
        await context.update_snapshot(
            progress=[{"phase": "searching", "detail": "Collecting sources"}],
            sources=[{"title": "Example", "url": "https://example.org/report"}],
            errors=[{"message": "One search agent failed"}],
        )
        await context.append_result("A useful partial report with a citation.")
        return RunOutcome(status="partial", error="One sub-agent failed")

    manager = ChatRunManager(session_factory, runner_mode="single_process")
    subscription = await manager.start(spec, worker)
    async for _ in subscription:
        pass

    persisted = await read_run(
        session_factory,
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    )
    assert persisted["status"] == "partial"
    assert persisted["snapshot"]["progress"][-1]["phase"] == "searching"
    assert persisted["snapshot"]["sources"][0]["url"] == "https://example.org/report"
    assert persisted["message"]["content"].startswith("A useful partial report")
    await manager.close()


@pytest.mark.asyncio
async def test_cancel_stops_worker_and_terminal_state_cannot_be_overwritten(db_session):
    spec = await make_run(db_session)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    started = asyncio.Event()
    later_step_calls = 0

    async def worker(context):
        nonlocal later_step_calls
        await context.append_result("Partial work before Stop.")
        started.set()
        await context.cancel_event.wait()
        if not context.cancel_event.is_set():
            later_step_calls += 1
        return RunOutcome(status="completed")

    manager = ChatRunManager(session_factory, runner_mode="single_process")
    subscription = await manager.start(spec, worker)
    await asyncio.wait_for(started.wait(), 1)
    assert await manager.request_cancel(
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    ) is True
    await subscription.aclose()
    run = await wait_for_terminal(db_session, spec.run_id)
    assert run.status == "cancelled"
    assert later_step_calls == 0
    assert (await db_session.get(Message, spec.assistant_message_id)).content == "Partial work before Stop."
    assert await manager.request_cancel(
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    ) is False
    await manager.close()


@pytest.mark.asyncio
async def test_stop_routed_through_another_manager_cancels_durable_run(db_session):
    spec = await make_run(db_session)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    started = asyncio.Event()
    after_stop_calls = 0

    async def worker(context):
        nonlocal after_stop_calls
        await context.append_result("Retain this before remote Stop.")
        started.set()
        await asyncio.Event().wait()
        after_stop_calls += 1

    runner_manager = ChatRunManager(session_factory, runner_mode="single_process")
    api_manager = ChatRunManager(session_factory, runner_mode="single_process")
    subscription = await runner_manager.start(spec, worker)
    await asyncio.wait_for(started.wait(), 1)
    assert await api_manager.request_cancel(
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    ) is True
    run = await wait_for_terminal(db_session, spec.run_id)
    assert run.status == "cancelled"
    assert after_stop_calls == 0
    assert (await db_session.get(Message, spec.assistant_message_id)).content == "Retain this before remote Stop."
    await subscription.aclose()
    await api_manager.close()
    await runner_manager.close()


@pytest.mark.asyncio
async def test_queued_run_deadline_includes_waiting_for_concurrency_slot(db_session):
    first_spec = await make_run(db_session)
    second_spec = replace(await make_run(db_session), timeout_seconds=1)
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_worker_calls = 0

    async def first_worker(_context):
        first_started.set()
        await release_first.wait()

    async def second_worker(_context):
        nonlocal second_worker_calls
        second_worker_calls += 1

    manager = ChatRunManager(session_factory, runner_mode="single_process", max_concurrent_runs=1)
    first_subscription = await manager.start(first_spec, first_worker)
    await asyncio.wait_for(first_started.wait(), 1)
    second_subscription = await manager.start(second_spec, second_worker)
    failed = await wait_for_terminal(db_session, second_spec.run_id, timeout=2)
    assert failed.status == "failed"
    assert "time limit" in failed.error
    assert second_worker_calls == 0
    release_first.set()
    async for _ in first_subscription:
        pass
    await second_subscription.aclose()
    await manager.close()


@pytest.mark.asyncio
async def test_startup_interruption_marks_active_without_replay(db_session):
    spec = await make_run(db_session, status="running")
    run = await db_session.get(ChatRun, spec.run_id)
    metadata = dict(run.run_metadata)
    metadata.update({
        "runner_owner_id": "crashed-owner",
        "runner_heartbeat_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
    })
    run.run_metadata = metadata
    await db_session.commit()
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    calls = 0

    async def worker(context):
        nonlocal calls
        calls += 1
        return RunOutcome(status="completed")

    manager = ChatRunManager(session_factory, runner_mode="disabled")
    await manager.recover_startup()
    db_session.expire_all()
    run = await db_session.get(ChatRun, spec.run_id)
    assert run.status == "interrupted"
    assert run.finished_at is not None
    assert calls == 0
    await manager.close()


@pytest.mark.asyncio
async def test_startup_recovery_does_not_interrupt_ordinary_chat_runs(db_session):
    research_spec = await make_run(db_session, status="running", task_kind="research")
    chat_spec = await make_run(db_session, status="running", task_kind="chat")
    research = await db_session.get(ChatRun, research_spec.run_id)
    metadata = dict(research.run_metadata)
    metadata.update({
        "runner_owner_id": "crashed-owner",
        "runner_heartbeat_at": (datetime.now(UTC) - timedelta(minutes=2)).isoformat(),
    })
    research.run_metadata = metadata
    await db_session.commit()
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    manager = ChatRunManager(session_factory, runner_mode="disabled")
    await manager.recover_startup()
    db_session.expire_all()
    research = await db_session.get(ChatRun, research_spec.run_id)
    ordinary = await db_session.get(ChatRun, chat_spec.run_id)
    assert research.status == "interrupted"
    assert ordinary.status == "running"
    await manager.close()


@pytest.mark.asyncio
async def test_disabled_recovery_preserves_fresh_and_legacy_runs(db_session):
    stale_spec = await make_run(db_session, status="running")
    fresh_spec = await make_run(db_session, status="running")
    legacy_spec = await make_run(db_session, status="running")
    orphaned_queued = await make_run(db_session, status="queued")
    fresh_queued = await make_run(db_session, status="queued")
    now = datetime.now(UTC)
    for spec, owner, heartbeat in (
        (stale_spec, "stale-owner", now - timedelta(minutes=2)),
        (fresh_spec, "live-owner", now),
    ):
        run = await db_session.get(ChatRun, spec.run_id)
        metadata = dict(run.run_metadata)
        metadata.update({"runner_owner_id": owner, "runner_heartbeat_at": heartbeat.isoformat()})
        run.run_metadata = metadata
    queued_orphan = await db_session.get(ChatRun, orphaned_queued.run_id)
    queued_orphan.created_at = now - timedelta(minutes=2)
    await db_session.commit()

    manager = ChatRunManager(async_sessionmaker(db_session.bind), runner_mode="disabled")
    await manager.recover_startup()
    db_session.expire_all()

    stale = await db_session.get(ChatRun, stale_spec.run_id)
    fresh = await db_session.get(ChatRun, fresh_spec.run_id)
    legacy = await db_session.get(ChatRun, legacy_spec.run_id)
    orphaned = await db_session.get(ChatRun, orphaned_queued.run_id)
    queued = await db_session.get(ChatRun, fresh_queued.run_id)
    assert stale.status == "interrupted"
    assert fresh.status == "running"
    assert legacy.status == "running"
    assert orphaned.status == "interrupted"
    assert queued.status == "queued"
    await manager.close()


@pytest.mark.asyncio
async def test_started_run_owns_a_renewed_live_lease_observed_by_disabled_runner(db_session, monkeypatch):
    import quip.services.chat_runs as chat_runs

    monkeypatch.setattr(chat_runs, "RUNNER_LEASE_TTL_SECONDS", 0.75)
    monkeypatch.setattr(chat_runs, "RUNNER_HEARTBEAT_INTERVAL_SECONDS", 0.05)
    spec = await make_run(db_session)
    factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    started = asyncio.Event()

    async def worker(_context):
        started.set()
        await asyncio.Event().wait()

    owner = ChatRunManager(factory, runner_mode="single_process")
    observer = ChatRunManager(factory, runner_mode="disabled")
    subscription = await owner.start(spec, worker)
    try:
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.sleep(1.1)
        await observer.recover_startup()
        db_session.expire_all()
        run = await db_session.get(ChatRun, spec.run_id)
        metadata = run.run_metadata
        heartbeat = datetime.fromisoformat(metadata["runner_heartbeat_at"])
        assert run.status == "running"
        assert metadata["runner_owner_id"]
        assert (datetime.now(UTC) - heartbeat).total_seconds() < 30
    finally:
        assert await owner.request_cancel(run_id=spec.run_id, chat_id=spec.chat_id, user_id=spec.user_id)
        await subscription.aclose()
        await owner.close()
        await observer.close()


@pytest.mark.asyncio
async def test_steering_is_bounded_and_scoped_to_active_owner_chat(db_session):
    spec = await make_run(db_session, status="running")
    session_factory = async_sessionmaker(db_session.bind, expire_on_commit=False)
    for i in range(5):
        result = await enqueue_run_steering(
            session_factory,
            run_id=spec.run_id,
            chat_id=spec.chat_id,
            user_id=spec.user_id,
            instruction=f"Refine the report, step {i}.",
        )
        assert result["accepted"] is (i < 4)

    persisted = await read_run(
        session_factory,
        run_id=spec.run_id,
        chat_id=spec.chat_id,
        user_id=spec.user_id,
    )
    assert persisted["context_version"] == 5
    assert len(persisted["steering"]) == 4
    assert await enqueue_run_steering(
        session_factory,
        run_id=spec.run_id,
        chat_id=uuid4(),
        user_id=spec.user_id,
        instruction="Must not cross chat ownership.",
    ) == {"accepted": False}


@pytest.mark.asyncio
async def test_disabled_runner_fails_closed(db_session):
    spec = await make_run(db_session)
    manager = ChatRunManager(async_sessionmaker(db_session.bind), runner_mode="disabled")
    with pytest.raises(RuntimeError, match="disabled"):
        await manager.start(spec, lambda _ctx: asyncio.sleep(0))
