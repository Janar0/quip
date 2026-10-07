"""Task ownership and detachable subscriptions; durable transitions live in chat_run_store."""

from __future__ import annotations

import asyncio
import logging
import weakref
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID, uuid4

from quip.models.chat import ChatRun
from quip.services import chat_run_store
from quip.services.chat_run_snapshot import (
    _bounded_json,
    _snapshot_json_bytes,
    _utf8_prefix,
    bounded_snapshot,
)
from quip.services.chat_run_store import (
    _finish_run,
    _mark_run_running,
    _metadata_write_sequence,
    _mutate_run_metadata,
    _parse_datetime,
    _recover_failed_run_finalization,
    _refresh_runner_lease,
    _run_cancel_requested,
    _try_finish_run,
    consume_run_steering,
    enqueue_run_steering,
    read_run,
    request_run_cancel,
    update_run_snapshot,
)
from quip.services.chat_run_types import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    MAX_METADATA_WRITE_RETRIES,
    MAX_REPORT_CHARS,
    MAX_SNAPSHOT_BYTES,
    MAX_SOURCE_TITLE_BYTES,
    MAX_SOURCE_URL_BYTES,
    MAX_STEERING_CHARS,
    MAX_STEERING_ITEMS,
    METADATA_WRITE_SEQUENCE_KEY,
    RUNNER_HEARTBEAT_INTERVAL_SECONDS,
    RUNNER_LEASE_TTL_SECONDS,
    SUBSCRIBER_QUEUE_SIZE,
    TERMINAL_STATUSES,
    ChatRunSpec,
    RunFinishDecision,
    RunOutcome,
)
from quip.services.messages_persist import save_assistant_message, update_assistant_message_draft

__all__ = [
    "_bounded_json",
    "_snapshot_json_bytes",
    "_utf8_prefix",
    "bounded_snapshot",
    "_finish_run",
    "_mark_run_running",
    "_metadata_write_sequence",
    "_mutate_run_metadata",
    "_parse_datetime",
    "_recover_failed_run_finalization",
    "_refresh_runner_lease",
    "_run_cancel_requested",
    "_try_finish_run",
    "consume_run_steering",
    "enqueue_run_steering",
    "read_run",
    "request_run_cancel",
    "update_run_snapshot",
    "ACTIVE_STATUSES",
    "CANCELLABLE_STATUSES",
    "MAX_METADATA_WRITE_RETRIES",
    "MAX_REPORT_CHARS",
    "MAX_SNAPSHOT_BYTES",
    "MAX_SOURCE_TITLE_BYTES",
    "MAX_SOURCE_URL_BYTES",
    "MAX_STEERING_CHARS",
    "MAX_STEERING_ITEMS",
    "METADATA_WRITE_SEQUENCE_KEY",
    "RUNNER_HEARTBEAT_INTERVAL_SECONDS",
    "RUNNER_LEASE_TTL_SECONDS",
    "SUBSCRIBER_QUEUE_SIZE",
    "TERMINAL_STATUSES",
    "ChatRunSpec",
    "RunFinishDecision",
    "RunOutcome",
    "ChatRunManager",
    "RunExecutionContext",
    "RunSubscription",
    "interrupt_active_runs",
]

logger = logging.getLogger(__name__)
_SENTINEL = object()


async def interrupt_active_runs(session_factory, *, task_kinds: set[str] | None = None) -> int:
    # Keep the facade's configurable lease duration shared by claiming and recovery.
    return await chat_run_store.interrupt_active_runs(
        session_factory, task_kinds=task_kinds, lease_ttl_seconds=RUNNER_LEASE_TTL_SECONDS
    )


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

        claimed = await chat_run_store.claim_run(
            self.session_factory,
            spec,
            owner_id=self._owner_id,
            lease_ttl_seconds=RUNNER_LEASE_TTL_SECONDS,
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
                        final_message_saved = bool(
                            await save_assistant_message(
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
                            )
                        )
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
                        recovery_status = (
                            "partial"
                            if (final_message_saved or draft_persisted) and context.report.strip()
                            else "failed"
                        )
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
                        await context.emit(
                            {
                                "type": "error",
                                "data": {
                                    "message": "Task finalization is pending; Stop can retry after storage recovers."
                                },
                            }
                        )
                    else:
                        outcome.status = terminal_status
                        await context.emit({"type": "error", "data": {"message": finalization_error}})

                if terminal_status in TERMINAL_STATUSES:
                    await self._broadcast(
                        spec.run_id,
                        {
                            "type": "run_status",
                            "data": {"status": terminal_status, "error": outcome.error},
                        },
                    )
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
