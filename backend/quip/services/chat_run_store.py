"""Durable ChatRun ownership, compare-and-retry mutations and transitions."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import or_, select, update
from sqlalchemy.exc import OperationalError

from quip.models.chat import ChatRun, Message
from quip.services.chat_run_snapshot import bounded_snapshot
from quip.services.chat_run_types import (
    ACTIVE_STATUSES,
    CANCELLABLE_STATUSES,
    MAX_METADATA_WRITE_RETRIES,
    MAX_STEERING_CHARS,
    MAX_STEERING_ITEMS,
    METADATA_WRITE_SEQUENCE_KEY,
    RUNNER_LEASE_TTL_SECONDS,
    TERMINAL_STATUSES,
    ChatRunSpec,
    RunFinishDecision,
)


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
                statement = (
                    update(ChatRun)
                    .where(
                        ChatRun.id == run_id,
                        ChatRun.status == run.status,
                        expected_sequence,
                    )
                    .values(run_metadata=next_metadata, **values)
                )
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
            }
            if message
            else None,
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
        if run.chat_id != chat_id or run.user_id != user_id or metadata.get("runner_owner_id") != runner_owner_id:
            return None, {}, RunFinishDecision(False, run.status, context_version, [])
        if run.status not in ACTIVE_STATUSES:
            return None, {}, RunFinishDecision(False, run.status, context_version, [])
        if isinstance(finish_intent, dict) and finish_intent.get("runner_owner_id") == runner_owner_id:
            return (
                None,
                {},
                RunFinishDecision(
                    True,
                    str(finish_intent.get("status") or requested_status),
                    context_version,
                    [],
                ),
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
        has_finish_intent = isinstance(finish_intent, dict) and finish_intent.get("runner_owner_id") == metadata.get(
            "runner_owner_id"
        )
        terminal_status = finish_intent.get("status") if has_finish_intent else requested_status
        if terminal_status not in TERMINAL_STATUSES:
            terminal_status = requested_status
        if metadata.get("cancel_requested") and terminal_status != "interrupted":
            terminal_status = "cancelled"
        metadata["revision"] = int(metadata.get("revision", 0)) + 1
        return (
            metadata,
            {
                "status": terminal_status,
                "error": (finish_intent.get("error") if has_finish_intent else error[:4000] if error else None),
                "finished_at": datetime.now(UTC),
            },
            terminal_status,
        )

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
        return (
            metadata,
            {
                "status": terminal_status,
                "error": saved_error,
                "finished_at": datetime.now(UTC),
            },
            terminal_status,
        )

    _, result = await _mutate_run_metadata(session_factory, run_id=run_id, mutate=recover)
    return result


async def interrupt_active_runs(
    session_factory, *, task_kinds: set[str] | None = None, lease_ttl_seconds: float = RUNNER_LEASE_TTL_SECONDS
) -> int:
    """Mark stale owned runs interrupted without replaying or claiming live work.

    Ownerless running rows may belong to a pre-lease process and are left alone.
    An old ownerless queued row is safe to interrupt because no runner owns it
    until it atomically writes its lease before execution.
    """
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=lease_ttl_seconds)
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
            return (
                metadata,
                {
                    "status": "interrupted",
                    "error": "The server restarted; task was not replayed.",
                    "finished_at": now,
                },
                True,
            )

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


async def _run_cancel_requested(session_factory, *, run_id: UUID, chat_id: UUID, user_id: UUID) -> bool:
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


async def claim_run(session_factory, spec: ChatRunSpec, *, owner_id: str, lease_ttl_seconds: float) -> bool:
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
            and existing_owner != owner_id
            and heartbeat is not None
            and (datetime.now(UTC) - heartbeat).total_seconds() < lease_ttl_seconds
        ):
            return None, {}, False
        metadata["runner_owner_id"] = owner_id
        metadata["runner_heartbeat_at"] = datetime.now(UTC).isoformat()
        return metadata, {}, True

    claimed, _ = await _mutate_run_metadata(session_factory, run_id=spec.run_id, mutate=claim)
    return claimed
