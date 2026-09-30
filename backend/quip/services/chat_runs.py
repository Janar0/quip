"""Shared bounded lifecycle for page-resilient work attached to a ChatRun."""

from __future__ import annotations

import asyncio
import json
import logging
import weakref
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import OperationalError

from quip.models.chat import ChatRun, Message
from quip.services.messages_persist import (
    save_assistant_message,
    update_assistant_message_draft,
)

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("queued", "running", "cancelling")
CANCELLABLE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "interrupted"}
MAX_REPORT_CHARS = 200_000
MAX_SNAPSHOT_BYTES = 48_000
MAX_SOURCE_URL_BYTES = 2_048
MAX_SOURCE_TITLE_BYTES = 512
MAX_STEERING_ITEMS = 4
MAX_STEERING_CHARS = 2_000
SUBSCRIBER_QUEUE_SIZE = 64
RUNNER_LEASE_TTL_SECONDS = 30
RUNNER_HEARTBEAT_INTERVAL_SECONDS = 5
METADATA_WRITE_SEQUENCE_KEY = "_write_sequence"
MAX_METADATA_WRITE_RETRIES = 12
_SENTINEL = object()


@dataclass(frozen=True)
class ChatRunSpec:
    run_id: UUID
    chat_id: UUID
    user_id: UUID
    assistant_message_id: UUID
    task_kind: str
    context_version: int = 1
    timeout_seconds: int = 600


@dataclass
class RunOutcome:
    status: str = "completed"
    error: str | None = None
    usage: dict[str, Any] | None = None
    reasoning: str = ""
    artifacts: list[dict] | None = None
    subagent_generations: list[str] | None = None


@dataclass(frozen=True)
class RunFinishDecision:
    """Atomic worker/manager handshake for closing steering before persistence."""

    accepted: bool
    status: str
    context_version: int
    steering: list[dict[str, Any]]


class RunSubscription:
    def __init__(self, manager: ChatRunManager, run_id: UUID, queue: asyncio.Queue):
        self._manager = manager
        self.run_id = run_id
        self._queue = queue
        self._closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self._queue.get()
        if item is _SENTINEL:
            await self.aclose()
            raise StopAsyncIteration
        return item

    async def aclose(self) -> None:
        if not self._closed:
            self._closed = True
            self._manager._unsubscribe(self.run_id, self._queue)


class RunExecutionContext:
    def __init__(self, manager: ChatRunManager, spec: ChatRunSpec, cancel_event: asyncio.Event):
        self.manager = manager
        self.spec = spec
        self.cancel_event = cancel_event
        self.report = ""
        self.final_outcome: RunOutcome | None = None
        self._last_draft_chars = 0
        self._last_draft_at = 0.0

    async def emit(self, event: Any) -> None:
        if hasattr(event, "type") and hasattr(event, "data"):
            payload = {"type": event.type, "data": event.data}
        else:
            payload = event
        if isinstance(payload, dict) and isinstance(payload.get("type"), str):
            await self.manager._broadcast(self.spec.run_id, payload)

    async def update_snapshot(self, **patch: Any) -> None:
        await update_run_snapshot(self.manager.session_factory, run_id=self.spec.run_id, patch=patch)

    async def append_result(self, text: str) -> None:
        if not text or len(self.report) >= MAX_REPORT_CHARS:
            return
        self.report += text[: MAX_REPORT_CHARS - len(self.report)]
        now = asyncio.get_running_loop().time()
        if len(self.report) - self._last_draft_chars >= 1024 or now - self._last_draft_at >= 1.0:
            await self.flush_result()

    async def flush_result(self, *, require_persisted: bool = False) -> bool | None:
        persisted = await update_assistant_message_draft(
            str(self.spec.assistant_message_id),
            str(self.spec.chat_id),
            content=self.report,
            session_factory=self.manager.session_factory,
            require_persisted=require_persisted,
        )
        self._last_draft_chars = len(self.report)
        self._last_draft_at = asyncio.get_running_loop().time()
        return persisted

    async def take_steering(self) -> list[dict[str, Any]]:
        return await consume_run_steering(
            self.manager.session_factory,
            run_id=self.spec.run_id,
            chat_id=self.spec.chat_id,
            user_id=self.spec.user_id,
        )

    async def try_finish(
        self,
        *,
        expected_context_version: int,
        status: str,
        error: str | None,
    ) -> RunFinishDecision:
        """Close steering admission if no newer accepted instruction is pending.

        On a stale version, pending instructions are drained atomically and
        returned to the worker, which must process them and retry. An accepted
        Stop wins the same compare-and-retry boundary and records cancellation.
        The manager persists the final assistant message before writing the
        terminal ChatRun state.
        """
        return await _try_finish_run(
            self.manager.session_factory,
            run_id=self.spec.run_id,
            chat_id=self.spec.chat_id,
            user_id=self.spec.user_id,
            runner_owner_id=self.manager._owner_id,
            expected_context_version=expected_context_version,
            status=status,
            error=error,
        )


Worker = Callable[[RunExecutionContext], Awaitable[RunOutcome | None]]


def _metadata_write_sequence(metadata: dict[str, Any]) -> int:
    value = metadata.get(METADATA_WRITE_SEQUENCE_KEY)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


async def _mutate_run_metadata(session_factory, *, run_id: UUID, mutate) -> tuple[bool, Any]:
    """Apply one metadata mutation with database-level compare-and-retry.

    SQLite ignores ``FOR UPDATE``. A private sequence in the JSON metadata lets
    every writer compare the version it read in the UPDATE predicate, so racing
    processes retry and merge from the newest document instead of replacing it.
    """
    sequence_column = ChatRun.run_metadata[METADATA_WRITE_SEQUENCE_KEY].as_integer()
    for attempt in range(MAX_METADATA_WRITE_RETRIES):
        try:
            async with session_factory() as db:
                run = await db.get(ChatRun, run_id)
                if run is None:
                    return False, None
                metadata = dict(run.run_metadata or {})
                change = mutate(run, metadata)
                if change is None:
                    return False, None
                next_metadata, values, result_value = change
                if next_metadata is None:
                    return False, result_value

                old_sequence = _metadata_write_sequence(metadata)
                next_metadata = dict(next_metadata)
                next_metadata[METADATA_WRITE_SEQUENCE_KEY] = old_sequence + 1
                expected_sequence = sequence_column == old_sequence
                if old_sequence == 0:
                    # Older rows predate this key; both absent and JSON null are
                    # treated as the initial sequence, but only one writer wins.
                    expected_sequence = or_(expected_sequence, sequence_column.is_(None))
                statement = update(ChatRun).where(
                    ChatRun.id == run_id,
                    ChatRun.status == run.status,
                    expected_sequence,
                ).values(run_metadata=next_metadata, **values)
                updated = await db.execute(statement)
                await db.commit()
                if updated.rowcount == 1:
                    return True, result_value
        except OperationalError:
            if attempt + 1 >= MAX_METADATA_WRITE_RETRIES:
                raise

        if attempt + 1 < MAX_METADATA_WRITE_RETRIES:
            await asyncio.sleep(min(0.005 * (2**attempt), 0.05))

    raise RuntimeError("Chat run metadata stayed busy after bounded retries")


class ChatRunManager:
    """Own task lifetime while exposing detachable, bounded event subscriptions."""

    def __init__(self, session_factory, *, runner_mode: str = "disabled", max_concurrent_runs: int = 2):
        self.session_factory = session_factory
        self.runner_mode = runner_mode
        self.max_concurrent_runs = max(1, min(int(max_concurrent_runs), 8))
        self._semaphore = asyncio.Semaphore(self.max_concurrent_runs)
        self._tasks: dict[UUID, asyncio.Task] = {}
        self._contexts: dict[UUID, RunExecutionContext] = {}
        self._cancel_events: dict[UUID, asyncio.Event] = {}
        self._subscribers: dict[UUID, set[asyncio.Queue]] = {}
        self._start_locks: weakref.WeakValueDictionary[UUID, asyncio.Lock] = weakref.WeakValueDictionary()
        self._transition_locks: dict[UUID, asyncio.Lock] = {}
        self._finalization_failures: dict[UUID, str] = {}
        self._owner_id = uuid4().hex
        self._closing = False

    async def start(self, spec: ChatRunSpec, worker: Worker) -> RunSubscription:
        if self.runner_mode != "single_process":
            raise RuntimeError("Research task runner is disabled")
        start_lock = self._start_locks.get(spec.run_id)
        if start_lock is None:
            start_lock = asyncio.Lock()
            self._start_locks[spec.run_id] = start_lock
        async with start_lock:
            return await self._start_locked(spec, worker)

    async def _start_locked(self, spec: ChatRunSpec, worker: Worker) -> RunSubscription:
        queue: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_SIZE)
        subscribers = self._subscribers.setdefault(spec.run_id, set())
        subscribers.add(queue)

        current = self._tasks.get(spec.run_id)
        if current is not None and not current.done():
            return RunSubscription(self, spec.run_id, queue)

        def claim(run: ChatRun, metadata: dict[str, Any]):
            if (
                run.chat_id != spec.chat_id
                or run.user_id != spec.user_id
                or run.assistant_message_id != spec.assistant_message_id
                or run.status != "queued"
                or bool(metadata.get("cancel_requested"))
            ):
                return None, {}, False
            metadata.setdefault("schema_version", 1)
            metadata.setdefault("task_kind", spec.task_kind)
            metadata.setdefault("revision", 0)
            metadata.setdefault("context_version", spec.context_version)
            metadata.setdefault("cancel_requested", False)
            metadata.setdefault("steering", [])
            metadata.setdefault("snapshot", {})
            existing_owner = metadata.get("runner_owner_id")
            heartbeat = _parse_datetime(metadata.get("runner_heartbeat_at"))
            if (
                existing_owner
                and existing_owner != self._owner_id
                and heartbeat is not None
                and (datetime.now(UTC) - heartbeat).total_seconds() < RUNNER_LEASE_TTL_SECONDS
            ):
                return None, {}, False
            metadata["runner_owner_id"] = self._owner_id
            metadata["runner_heartbeat_at"] = datetime.now(UTC).isoformat()
            return metadata, {}, True

        claimed, _ = await _mutate_run_metadata(
            self.session_factory, run_id=spec.run_id, mutate=claim
        )
        if not claimed:
            self._unsubscribe(spec.run_id, queue)
            raise RuntimeError("Chat run is missing, active, or no longer available")

        cancel_event = asyncio.Event()
        context = RunExecutionContext(self, spec, cancel_event)
        self._contexts[spec.run_id] = context
        self._cancel_events[spec.run_id] = cancel_event
        task = asyncio.create_task(self._execute(spec, context, worker), name=f"chat-run-{spec.run_id}")
        self._tasks[spec.run_id] = task
        return RunSubscription(self, spec.run_id, queue)

    async def _execute(self, spec: ChatRunSpec, context: RunExecutionContext, worker: Worker) -> None:
        outcome = RunOutcome()
        try:
            result = await asyncio.wait_for(
                self._run_with_slot_and_cancel_monitor(spec, context, worker),
                timeout=max(1, spec.timeout_seconds),
            )
            if isinstance(result, RunOutcome):
                outcome = result
        except TimeoutError:
            outcome = context.final_outcome or outcome
            outcome.status = "partial" if context.report.strip() else "failed"
            outcome.error = f"Task exceeded the {spec.timeout_seconds} second time limit"
            await context.emit({"type": "error", "data": {"message": outcome.error}})
        except asyncio.CancelledError:
            outcome = context.final_outcome or outcome
            outcome.status = "interrupted" if self._closing else "cancelled"
            if not self._closing:
                context.cancel_event.set()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat run %s failed", spec.run_id)
            outcome.status = "partial" if context.report.strip() else "failed"
            outcome.error = str(exc)[:4000]
            await context.emit({"type": "error", "data": {"message": "Research task failed"}})
        finally:
            terminal_status: str | None = None
            persistence_error: str | None = None
            try:
                draft_persisted = False
                try:
                    draft_persisted = bool(await context.flush_result(require_persisted=True))
                except Exception:  # noqa: BLE001
                    logger.exception("Could not persist final draft for ChatRun %s", spec.run_id)

                model = None
                model_read_error: Exception | None = None
                try:
                    async with self.session_factory() as db:
                        run = await db.get(ChatRun, spec.run_id)
                        model = run.model if run else None
                except Exception as exc:  # noqa: BLE001
                    model_read_error = exc
                    logger.exception("Could not read model for ChatRun %s", spec.run_id)

                save_attempted = bool(model and (context.report or outcome.usage))
                final_message_saved = False
                if save_attempted:
                    try:
                        final_message_saved = bool(await save_assistant_message(
                            str(spec.assistant_message_id),
                            str(spec.chat_id),
                            spec.user_id,
                            context.report,
                            model,
                            outcome.usage,
                            reasoning=outcome.reasoning,
                            subagent_generations=outcome.subagent_generations,
                            session_factory=self.session_factory,
                            require_persisted=True,
                        ))
                    except Exception:  # noqa: BLE001
                        logger.exception("Could not persist final message for ChatRun %s", spec.run_id)

                if save_attempted and not final_message_saved:
                    persistence_error = "Could not save the final assistant message."
                    if outcome.status not in {"cancelled", "interrupted"}:
                        outcome.status = "partial" if draft_persisted and context.report.strip() else "failed"
                elif not save_attempted and not draft_persisted:
                    persistence_error = "Could not save the final assistant report."
                    if outcome.status not in {"cancelled", "interrupted"}:
                        outcome.status = "failed"
                elif model_read_error is not None:
                    persistence_error = "Could not confirm final assistant message metadata."
                    if outcome.status not in {"cancelled", "interrupted"}:
                        outcome.status = "partial" if draft_persisted and context.report.strip() else "failed"

                if persistence_error:
                    outcome.error = "; ".join(filter(None, (outcome.error, persistence_error)))[:4000]
                    await context.emit({"type": "error", "data": {"message": persistence_error}})

                try:
                    if persistence_error:
                        terminal_status = await _recover_failed_run_finalization(
                            self.session_factory,
                            run_id=spec.run_id,
                            status=outcome.status,
                            error=outcome.error,
                            runner_owner_id=self._owner_id,
                        )
                    else:
                        lock = self._transition_locks.setdefault(spec.run_id, asyncio.Lock())
                        async with lock:
                            terminal_status = await _finish_run(
                                self.session_factory,
                                run_id=spec.run_id,
                                status=outcome.status,
                                error=outcome.error,
                                runner_owner_id=self._owner_id,
                            )
                    if terminal_status not in TERMINAL_STATUSES:
                        raise RuntimeError(f"ChatRun terminal status was not confirmed: {terminal_status}")
                except Exception:  # noqa: BLE001
                    logger.exception("Could not finalize ChatRun %s", spec.run_id)
                    finalization_error = "Could not persist the final task status."
                    outcome.error = "; ".join(filter(None, (outcome.error, finalization_error)))[:4000]
                    recovery_status = outcome.status
                    if recovery_status == "completed":
                        recovery_status = "partial" if (final_message_saved or draft_persisted) and context.report.strip() else "failed"
                    try:
                        terminal_status = await _recover_failed_run_finalization(
                            self.session_factory,
                            run_id=spec.run_id,
                            status=recovery_status,
                            error=outcome.error,
                            runner_owner_id=self._owner_id,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Could not recover failed finalization for ChatRun %s", spec.run_id)
                        terminal_status = None
                    if terminal_status not in TERMINAL_STATUSES:
                        terminal_status = None
                        self._finalization_failures[spec.run_id] = outcome.error
                        await context.emit({
                            "type": "error",
                            "data": {"message": "Task finalization is pending; Stop can retry after storage recovers."},
                        })
                    else:
                        outcome.status = terminal_status
                        await context.emit({"type": "error", "data": {"message": finalization_error}})

                if terminal_status in TERMINAL_STATUSES:
                    await self._broadcast(spec.run_id, {
                        "type": "run_status",
                        "data": {"status": terminal_status, "error": outcome.error},
                    })
            except Exception as exc:  # noqa: BLE001
                logger.exception("Could not finalize ChatRun %s", spec.run_id)
                failure = f"Could not complete task finalization: {exc}"
                self._finalization_failures[spec.run_id] = failure
                try:
                    await context.emit({"type": "error", "data": {"message": failure}})
                except Exception:  # noqa: BLE001
                    logger.exception("Could not broadcast finalization error for ChatRun %s", spec.run_id)
            finally:
                self._signal_subscribers(spec.run_id, _SENTINEL)
                self._contexts.pop(spec.run_id, None)
                self._cancel_events.pop(spec.run_id, None)
                self._tasks.pop(spec.run_id, None)
                self._transition_locks.pop(spec.run_id, None)

    async def _run_with_slot_and_cancel_monitor(
        self, spec: ChatRunSpec, context: RunExecutionContext, worker: Worker
    ) -> RunOutcome | None:
        """Count queueing against the run deadline and observe durable Stop while queued."""
        acquired = False
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while not acquired:
                if context.cancel_event.is_set():
                    return RunOutcome(status="cancelled")
                try:
                    await asyncio.wait_for(self._semaphore.acquire(), timeout=0.5)
                    acquired = True
                except TimeoutError:
                    if loop.time() - last_heartbeat >= RUNNER_HEARTBEAT_INTERVAL_SECONDS:
                        try:
                            still_owner = await _refresh_runner_lease(
                                self.session_factory, run_id=spec.run_id, owner_id=self._owner_id
                            )
                        except Exception:  # noqa: BLE001
                            logger.exception("Could not refresh ChatRun lease %s", spec.run_id)
                        else:
                            if not still_owner:
                                context.cancel_event.set()
                                return RunOutcome(status="cancelled")
                            last_heartbeat = loop.time()
                    if await _run_cancel_requested(
                        self.session_factory,
                        run_id=spec.run_id,
                        chat_id=spec.chat_id,
                        user_id=spec.user_id,
                    ):
                        context.cancel_event.set()
                        return RunOutcome(status="cancelled")

            if context.cancel_event.is_set() or await _run_cancel_requested(
                self.session_factory,
                run_id=spec.run_id,
                chat_id=spec.chat_id,
                user_id=spec.user_id,
            ):
                context.cancel_event.set()
                return RunOutcome(status="cancelled")
            if not await _mark_run_running(self.session_factory, spec.run_id):
                if await _run_cancel_requested(
                    self.session_factory,
                    run_id=spec.run_id,
                    chat_id=spec.chat_id,
                    user_id=spec.user_id,
                ):
                    return RunOutcome(status="cancelled")
                raise RuntimeError("Chat run could not enter the running state")
            return await self._run_worker_with_cancel_monitor(spec, context, worker)
        finally:
            if acquired:
                self._semaphore.release()

    async def _run_worker_with_cancel_monitor(
        self, spec: ChatRunSpec, context: RunExecutionContext, worker: Worker
    ) -> RunOutcome | None:
        """Observe durable cancellation too, including a Stop routed to another worker."""
        task = asyncio.create_task(worker(context))
        loop = asyncio.get_running_loop()
        last_heartbeat = loop.time()
        try:
            while not task.done():
                done, _ = await asyncio.wait({task}, timeout=0.5)
                if done:
                    break
                if loop.time() - last_heartbeat >= RUNNER_HEARTBEAT_INTERVAL_SECONDS:
                    try:
                        still_owner = await _refresh_runner_lease(
                            self.session_factory, run_id=spec.run_id, owner_id=self._owner_id
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Could not refresh ChatRun lease %s", spec.run_id)
                    else:
                        if not still_owner:
                            context.cancel_event.set()
                            task.cancel()
                            break
                        last_heartbeat = loop.time()
                if await _run_cancel_requested(
                    self.session_factory,
                    run_id=spec.run_id,
                    chat_id=spec.chat_id,
                    user_id=spec.user_id,
                ):
                    context.cancel_event.set()
                    task.cancel()
                    break
            try:
                return await task
            except asyncio.CancelledError:
                if context.cancel_event.is_set():
                    return RunOutcome(status="cancelled")
                raise
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def request_cancel(self, *, run_id: UUID, chat_id: UUID, user_id: UUID) -> bool:
        finalization_failure = self._finalization_failures.get(run_id)
        lock = self._transition_locks.setdefault(run_id, asyncio.Lock())
        async with lock:
            accepted = await request_run_cancel(
                self.session_factory,
                run_id=run_id,
                chat_id=chat_id,
                user_id=user_id,
                allow_finalization_retry_owner_id=self._owner_id if finalization_failure else None,
            )
        if accepted:
            event = self._cancel_events.get(run_id)
            if event:
                event.set()
            task = self._tasks.get(run_id)
            if task and not task.done() and not finalization_failure:
                task.cancel()
            if finalization_failure:
                try:
                    try:
                        terminal_status = await _finish_run(
                            self.session_factory,
                            run_id=run_id,
                            status="cancelled",
                            error=finalization_failure,
                            runner_owner_id=self._owner_id,
                        )
                    except Exception:  # noqa: BLE001
                        logger.exception("Could not apply Stop through normal finalization for ChatRun %s", run_id)
                        terminal_status = None
                    if terminal_status not in TERMINAL_STATUSES:
                        terminal_status = await _recover_failed_run_finalization(
                            self.session_factory,
                            run_id=run_id,
                            status="cancelled",
                            error=finalization_failure,
                            runner_owner_id=self._owner_id,
                        )
                    if terminal_status in TERMINAL_STATUSES:
                        self._finalization_failures.pop(run_id, None)
                except Exception:  # noqa: BLE001
                    logger.exception("Could not complete Stop recovery for ChatRun %s", run_id)
        return accepted

    async def close(self) -> None:
        self._closing = True
        tasks = list(self._tasks.values())
        for event in self._cancel_events.values():
            event.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def recover_startup(self) -> int:
        return await interrupt_active_runs(self.session_factory)

    async def _broadcast(self, run_id: UUID, event: dict[str, Any]) -> None:
        self._signal_subscribers(run_id, event)

    def _signal_subscribers(self, run_id: UUID, item: Any) -> None:
        for queue in tuple(self._subscribers.get(run_id, ())):
            if queue.full():
                # SSE is best-effort; durable snapshots are the reconnect path.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(item)
            except asyncio.QueueFull:
                pass

    def _unsubscribe(self, run_id: UUID, queue: asyncio.Queue) -> None:
        queues = self._subscribers.get(run_id)
        if queues:
            queues.discard(queue)
            if not queues:
                self._subscribers.pop(run_id, None)

async def read_run(session_factory, *, run_id: UUID, chat_id: UUID, user_id: UUID) -> dict[str, Any] | None:
    async with session_factory() as db:
        result = await db.execute(
            select(ChatRun).where(
                ChatRun.id == run_id,
                ChatRun.chat_id == chat_id,
                ChatRun.user_id == user_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            return None
        message = await db.get(Message, run.assistant_message_id) if run.assistant_message_id else None
        metadata = dict(run.run_metadata or {})
        return {
            "run_id": str(run.id),
            "task_id": str(run.id),
            "chat_id": str(run.chat_id),
            "status": run.status,
            "revision": int(metadata.get("revision", 0)),
            "context_version": int(metadata.get("context_version", 1)),
            "cancel_requested": bool(metadata.get("cancel_requested", False)),
            "task_kind": metadata.get("task_kind", "chat"),
            "steering": metadata.get("steering", []),
            "snapshot": metadata.get("snapshot", {}),
            "error": run.error,
            "result_message_id": str(run.assistant_message_id) if run.assistant_message_id else None,
            "message": {
                "id": str(message.id),
                "content": message.content or "",
                "artifacts": message.artifacts or [],
            } if message else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }


async def update_run_snapshot(session_factory, *, run_id: UUID, patch: dict[str, Any]) -> bool:
    def merge(run: ChatRun, metadata: dict[str, Any]):
        if run.status not in ACTIVE_STATUSES:
            return None, {}, False
        snapshot = dict(metadata.get("snapshot") or {})
        snapshot.update(patch)
        metadata["snapshot"] = bounded_snapshot(snapshot)
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {}, True

    changed, _ = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=merge)
    return changed


async def request_run_cancel(
    session_factory,
    *,
    run_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    allow_finalization_retry_owner_id: str | None = None,
) -> bool:
    def cancel(run: ChatRun, metadata: dict[str, Any]):
        finish_intent = metadata.get("finish_intent")
        owns_finalization_retry = (
            allow_finalization_retry_owner_id is not None
            and metadata.get("runner_owner_id") == allow_finalization_retry_owner_id
        )
        retrying_failed_finalization = (
            isinstance(finish_intent, dict)
            and owns_finalization_retry
            and finish_intent.get("runner_owner_id") == allow_finalization_retry_owner_id
        )
        retrying_accepted_cancel = (
            owns_finalization_retry
            and run.status == "cancelling"
            and bool(metadata.get("cancel_requested"))
            and not finish_intent
        )
        if (
            run.chat_id != chat_id
            or run.user_id != user_id
            or (run.status not in CANCELLABLE_STATUSES and not retrying_accepted_cancel)
            or (finish_intent and not retrying_failed_finalization)
        ):
            return None, {}, False
        if metadata.get("cancel_requested"):
            if retrying_accepted_cancel:
                return None, {}, True
            return None, {}, False
        if retrying_failed_finalization:
            metadata.pop("finish_intent", None)
        metadata["cancel_requested"] = True
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {"status": "cancelling"}, True

    changed, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=cancel)
    return changed or result is True


async def enqueue_run_steering(
    session_factory,
    *,
    run_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    instruction: str,
) -> dict[str, Any]:
    text = instruction.strip()
    if not text or len(text) > MAX_STEERING_CHARS:
        return {"accepted": False}
    def steer(run: ChatRun, metadata: dict[str, Any]):
        if (
            run.chat_id != chat_id
            or run.user_id != user_id
            or run.status not in ACTIVE_STATUSES
            or metadata.get("finish_intent")
        ):
            return None, {}, {"accepted": False}
        if metadata.get("cancel_requested"):
            return None, {}, {"accepted": False}
        steering = list(metadata.get("steering") or [])
        if len(steering) >= MAX_STEERING_ITEMS:
            return None, {}, {"accepted": False}
        item = {"id": str(uuid4()), "instruction": text}
        steering.append(item)
        metadata["steering"] = steering
        metadata["context_version"] = int(metadata.get("context_version", 1)) + 1
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {}, {"accepted": True, "item": item, "context_version": metadata["context_version"]}

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=steer)
    return result or {"accepted": False}


async def consume_run_steering(session_factory, *, run_id: UUID, chat_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    def consume(run: ChatRun, metadata: dict[str, Any]):
        if (
            run.chat_id != chat_id
            or run.user_id != user_id
            or run.status not in ACTIVE_STATUSES
            or metadata.get("finish_intent")
        ):
            return None, {}, []
        steering = list(metadata.get("steering") or [])
        if not steering:
            return None, {}, []
        metadata["steering"] = []
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {}, steering

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=consume)
    return result or []


async def _mark_run_running(session_factory, run_id: UUID) -> bool:
    async with session_factory() as db:
        updated = await db.execute(
            update(ChatRun)
            .where(ChatRun.id == run_id, ChatRun.status == "queued")
            .values(status="running", started_at=datetime.now(UTC))
        )
        await db.commit()
        return updated.rowcount == 1


async def _try_finish_run(
    session_factory,
    *,
    run_id: UUID,
    chat_id: UUID,
    user_id: UUID,
    runner_owner_id: str,
    expected_context_version: int,
    status: str,
    error: str | None,
) -> RunFinishDecision:
    requested_status = status if status in TERMINAL_STATUSES else "failed"
    saved_error = error[:4000] if error else None

    def prepare_finish(run: ChatRun, metadata: dict[str, Any]):
        context_version = metadata.get("context_version", 1)
        if not isinstance(context_version, int) or isinstance(context_version, bool) or context_version < 1:
            context_version = 1
        finish_intent = metadata.get("finish_intent")
        if (
            run.chat_id != chat_id
            or run.user_id != user_id
            or metadata.get("runner_owner_id") != runner_owner_id
        ):
            return None, {}, RunFinishDecision(False, run.status, context_version, [])
        if run.status not in ACTIVE_STATUSES:
            return None, {}, RunFinishDecision(False, run.status, context_version, [])
        if isinstance(finish_intent, dict) and finish_intent.get("runner_owner_id") == runner_owner_id:
            return None, {}, RunFinishDecision(
                True,
                str(finish_intent.get("status") or requested_status),
                context_version,
                [],
            )

        if metadata.get("cancel_requested"):
            metadata["steering"] = []
            metadata["finish_intent"] = {
                "status": "cancelled",
                "error": None,
                "context_version": context_version,
                "runner_owner_id": runner_owner_id,
            }
            metadata["revision"] = int(metadata.get("revision", 0)) + 1
            return metadata, {}, RunFinishDecision(True, "cancelled", context_version, [])

        steering = list(metadata.get("steering") or [])
        if context_version != expected_context_version or steering:
            if steering:
                metadata["steering"] = []
                metadata["revision"] = int(metadata.get("revision", 0)) + 1
                return metadata, {}, RunFinishDecision(False, run.status, context_version, steering)
            return None, {}, RunFinishDecision(False, run.status, context_version, [])

        metadata["finish_intent"] = {
            "status": requested_status,
            "error": saved_error,
            "context_version": context_version,
            "runner_owner_id": runner_owner_id,
        }
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {}, RunFinishDecision(True, requested_status, context_version, [])

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=prepare_finish)
    return result or RunFinishDecision(False, "interrupted", 1, [])


async def _finish_run(
    session_factory,
    *,
    run_id: UUID,
    status: str,
    error: str | None,
    runner_owner_id: str | None = None,
) -> str | None:
    requested_status = status if status in TERMINAL_STATUSES else "failed"

    def finish(run: ChatRun, metadata: dict[str, Any]):
        if run.status not in ACTIVE_STATUSES:
            return None, {}, run.status
        if runner_owner_id and metadata.get("runner_owner_id") != runner_owner_id:
            return None, {}, run.status
        finish_intent = metadata.get("finish_intent")
        has_finish_intent = (
            isinstance(finish_intent, dict)
            and finish_intent.get("runner_owner_id") == metadata.get("runner_owner_id")
        )
        terminal_status = finish_intent.get("status") if has_finish_intent else requested_status
        if terminal_status not in TERMINAL_STATUSES:
            terminal_status = requested_status
        if metadata.get("cancel_requested") and terminal_status != "interrupted":
            terminal_status = "cancelled"
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return metadata, {
            "status": terminal_status,
            "error": (
                finish_intent.get("error")
                if has_finish_intent
                else error[:4000] if error else None
            ),
            "finished_at": datetime.now(UTC),
        }, terminal_status

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=finish)
    return result


async def _recover_failed_run_finalization(
    session_factory,
    *,
    run_id: UUID,
    status: str,
    error: str | None,
    runner_owner_id: str,
) -> str | None:
    """Commit an observable terminal error if the normal terminal writer fails."""
    requested_status = status if status in TERMINAL_STATUSES else "failed"
    saved_error = error[:4000] if error else "Task finalization failed"

    def recover(run: ChatRun, metadata: dict[str, Any]):
        if run.status not in ACTIVE_STATUSES:
            return None, {}, run.status
        if metadata.get("runner_owner_id") != runner_owner_id:
            return None, {}, run.status
        terminal_status = requested_status
        if metadata.get("cancel_requested") and terminal_status != "interrupted":
            terminal_status = "cancelled"
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        metadata["finish_intent"] = {
            "status": terminal_status,
            "error": saved_error,
            "context_version": int(metadata.get("context_version", 1)),
            "runner_owner_id": runner_owner_id,
        }
        return metadata, {
            "status": terminal_status,
            "error": saved_error,
            "finished_at": datetime.now(UTC),
        }, terminal_status

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=recover)
    return result


async def interrupt_active_runs(session_factory, *, task_kinds: set[str] | None = None) -> int:
    """Mark stale owned runs interrupted without replaying or claiming live work.

    Ownerless running rows may belong to a pre-lease process and are left alone.
    An old ownerless queued row is safe to interrupt because no runner owns it
    until it atomically writes its lease before execution.
    """
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=RUNNER_LEASE_TTL_SECONDS)
    interrupted = 0
    async with session_factory() as db:
        result = await db.execute(select(ChatRun.id).where(ChatRun.status.in_(ACTIVE_STATUSES)))
        active_run_ids = result.scalars().all()

    for run_id in active_run_ids:
        def interrupt(run: ChatRun, metadata: dict[str, Any]):
            if run.status not in ACTIVE_STATUSES:
                return None, {}, False
            task_kind = metadata.get("task_kind")
            if (
                metadata.get("schema_version") != 1
                or not isinstance(task_kind, str)
                or task_kind == "chat"
                or (task_kinds is not None and task_kind not in task_kinds)
            ):
                return None, {}, False

            owner_id = metadata.get("runner_owner_id")
            heartbeat = _parse_datetime(metadata.get("runner_heartbeat_at"))
            if owner_id and heartbeat:
                if heartbeat >= stale_before:
                    return None, {}, False
            elif run.status == "queued" and not owner_id and not heartbeat:
                created_at = _parse_datetime(run.created_at)
                if created_at is None or created_at >= stale_before:
                    return None, {}, False
            else:
                # An ownerless running run may still belong to an older live worker.
                return None, {}, False

            metadata["revision"] = int(metadata.get("revision", 0)) + 1
            metadata["cancel_requested"] = False
            snapshot = dict(metadata.get("snapshot") or {})
            snapshot["interruption"] = "The server restarted; this task was not replayed."
            metadata["snapshot"] = bounded_snapshot(snapshot)
            return metadata, {
                "status": "interrupted",
                "error": "The server restarted; task was not replayed.",
                "finished_at": now,
            }, True

        changed, _ = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=interrupt)
        interrupted += int(changed)
    return interrupted


async def _refresh_runner_lease(session_factory, *, run_id: UUID, owner_id: str) -> bool:
    def heartbeat(run: ChatRun, metadata: dict[str, Any]):
        if run.status not in ACTIVE_STATUSES:
            return None, {}, False
        if metadata.get("runner_owner_id") != owner_id:
            return None, {}, False
        metadata["runner_heartbeat_at"] = datetime.now(UTC).isoformat()
        return metadata, {}, True

    changed, _ = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=heartbeat)
    return changed


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


async def _run_cancel_requested(
    session_factory, *, run_id: UUID, chat_id: UUID, user_id: UUID
) -> bool:
    async with session_factory() as db:
        result = await db.execute(
            select(ChatRun.run_metadata, ChatRun.status).where(
                ChatRun.id == run_id,
                ChatRun.chat_id == chat_id,
                ChatRun.user_id == user_id,
            )
        )
        row = result.one_or_none()
        if row is None:
            return True
        metadata, status = row
        return status == "cancelling" or bool((metadata or {}).get("cancel_requested"))


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, dict):
        return {str(key)[:100]: _bounded_json(item, depth=depth + 1) for key, item in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_bounded_json(item, depth=depth + 1) for item in value[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _utf8_prefix(value: Any, max_bytes: int) -> tuple[str, bool]:
    text = value if isinstance(value, str) else str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _snapshot_json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def bounded_snapshot(snapshot: Any) -> dict[str, Any]:
    """Return a size-bounded snapshot without storing partial citation URLs."""
    if not isinstance(snapshot, dict):
        return {"truncated": True}

    truncated = bool(snapshot.get("truncated", False))
    safe: dict[str, Any] = {}
    known = {"sources", "progress", "subagents", "errors", "usage", "truncated"}
    for key, value in snapshot.items():
        key = str(key)[:100]
        if key not in known:
            safe[key] = _bounded_json(value)

    safe_progress: list[dict[str, Any]] = []
    progress = snapshot.get("progress")
    if isinstance(progress, list):
        if len(progress) > 40:
            truncated = True
        for item in progress[-40:]:
            if not isinstance(item, dict):
                truncated = True
                continue
            bounded: dict[str, Any] = {}
            for field_name, byte_limit in (("phase", 80), ("detail", 512)):
                if field_name in item:
                    bounded[field_name], cut = _utf8_prefix(item[field_name], byte_limit)
                    truncated = truncated or cut
            for field_name, byte_limit, max_items in (("sub_queries", 256, 12), ("urls_reading", MAX_SOURCE_URL_BYTES, 10)):
                values = item.get(field_name)
                if not isinstance(values, (list, tuple)):
                    continue
                if len(values) > max_items:
                    truncated = True
                collected = []
                for value in values[:max_items]:
                    bounded_value, cut = _utf8_prefix(value, byte_limit)
                    if field_name == "urls_reading" and cut:
                        truncated = True
                        continue
                    collected.append(bounded_value)
                    truncated = truncated or cut
                bounded[field_name] = collected
            for field_name in ("sources_found", "urls_read"):
                value = item.get(field_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bounded[field_name] = value
            safe_progress.append(bounded)
    if safe_progress or "progress" in snapshot:
        safe["progress"] = safe_progress

    safe_subagents: dict[str, dict[str, str]] = {}
    subagents = snapshot.get("subagents")
    if isinstance(subagents, dict):
        entries = list(subagents.items())
        if len(entries) > 8:
            truncated = True
        for task_id, item in entries[-8:]:
            if not isinstance(item, dict):
                truncated = True
                continue
            bounded: dict[str, str] = {}
            for field_name, byte_limit in (("task_id", 80), ("kind", 40), ("status", 24), ("goal", 300)):
                value = item.get(field_name)
                if value is None:
                    continue
                bounded[field_name], cut = _utf8_prefix(value, byte_limit)
                truncated = truncated or cut
            bounded_id, cut = _utf8_prefix(task_id, 80)
            truncated = truncated or cut
            if "task_id" not in bounded:
                bounded["task_id"] = bounded_id
            safe_subagents[bounded_id] = bounded
    if safe_subagents or "subagents" in snapshot:
        safe["subagents"] = safe_subagents

    safe_errors: list[dict[str, str]] = []
    errors = snapshot.get("errors")
    if isinstance(errors, list):
        if len(errors) > 20:
            truncated = True
        for item in errors[-20:]:
            value = item.get("message") if isinstance(item, dict) else item
            message, cut = _utf8_prefix(value, 1000)
            safe_errors.append({"message": message})
            truncated = truncated or cut
    if safe_errors or "errors" in snapshot:
        safe["errors"] = safe_errors

    safe_sources: list[dict[str, str]] = []
    sources = snapshot.get("sources")
    if isinstance(sources, list):
        if len(sources) > 30:
            truncated = True
        for source in sources[:30]:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                truncated = True
                continue
            url, url_cut = _utf8_prefix(source["url"], MAX_SOURCE_URL_BYTES)
            if url_cut:
                # Citation targets stay exact or are omitted; never persist a broken URL prefix.
                truncated = True
                continue
            title, title_cut = _utf8_prefix(source.get("title", ""), MAX_SOURCE_TITLE_BYTES)
            bounded_source = {"title": title, "url": url}
            if isinstance(source.get("snippet"), str) and source["snippet"]:
                snippet, snippet_cut = _utf8_prefix(source["snippet"], 600)
                bounded_source["snippet"] = snippet
                truncated = truncated or snippet_cut
            safe_sources.append(bounded_source)
            truncated = truncated or title_cut
    if safe_sources or "sources" in snapshot:
        safe["sources"] = safe_sources

    if "usage" in snapshot:
        safe["usage"] = _bounded_json(snapshot.get("usage"))

    while _snapshot_json_bytes({**safe, "truncated": truncated}) > MAX_SNAPSHOT_BYTES:
        truncated = True
        if safe.get("sources"):
            safe["sources"].pop()
        elif safe.get("progress"):
            safe["progress"].pop(0)
        elif safe.get("errors"):
            safe["errors"].pop(0)
        elif safe.get("subagents"):
            safe["subagents"].pop(next(iter(safe["subagents"])))
        elif safe.get("usage"):
            usage = safe["usage"]
            if isinstance(usage, dict) and "subagent_generations" in usage:
                usage.pop("subagent_generations", None)
            else:
                safe.pop("usage", None)
        else:
            optional = [key for key in safe if key != "truncated"]
            if not optional:
                return {"truncated": True}
            largest = max(optional, key=lambda key: _snapshot_json_bytes(safe[key]))
            safe.pop(largest, None)

    safe["truncated"] = truncated
    return safe
