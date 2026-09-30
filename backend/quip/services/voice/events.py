"""Persist a strict subset of Qwen DataChannel transcript and usage events."""
from datetime import UTC, datetime
from uuid import UUID, uuid5

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Message
from quip.models.user import User
from quip.services.voice.common import get_latest_leaf_message_id, get_owned_call

MAX_TRANSCRIPT_CHARS = 20_000
MAX_CLIENT_TOKENS = 1_000_000_000


def _short_string(event: dict, key: str, *, required: bool = True) -> str | None:
    value = event.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > 200:
        raise HTTPException(status_code=422, detail="Malformed provider event")
    return value


def _client_usage(event: dict) -> dict:
    response = event.get("response")
    if not isinstance(response, dict):
        raise HTTPException(status_code=422, detail="Malformed provider event")
    usage = response.get("usage")
    if not isinstance(usage, dict):
        raise HTTPException(status_code=422, detail="Malformed provider event")
    fields = ("total_tokens", "input_tokens", "output_tokens")
    result = {}
    for field in fields:
        value = usage.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= MAX_CLIENT_TOKENS:
            raise HTTPException(status_code=422, detail="Malformed provider event")
        result[field] = value
    result.update(
        response_id=_short_string(response, "id"),
        source="qwen_realtime_client_event",
        reported_at=datetime.now(UTC).isoformat(),
    )
    return result


async def persist_provider_event(
    db: AsyncSession,
    user: User,
    call_id: UUID,
    event: dict,
) -> dict:
    call = await get_owned_call(db, call_id, user.id)
    if call is None:
        raise HTTPException(status_code=404, detail="Voice call not found")
    if call.status in {"ended", "failed"}:
        raise HTTPException(status_code=409, detail="Voice call has ended")
    if not isinstance(event, dict):
        raise HTTPException(status_code=422, detail="Malformed provider event")

    event_type = event.get("type")
    if event_type == "session.created":
        session = event.get("session")
        if not isinstance(session, dict) or session.get("model") not in (None, call.model):
            raise HTTPException(status_code=422, detail="Malformed provider event")
        if call.status == "connecting":
            call.status = "active"
            call.connected_at = datetime.now(UTC)
            await db.commit()
        return {"status": call.status}

    if event_type == "response.done":
        usage = _client_usage(event)
        call.client_usage = usage
        await db.commit()
        return {"status": call.status, "usage_is_preliminary": True}

    if event_type == "conversation.item.input_audio_transcription.completed":
        role = "user"
        transcript_key = "transcript"
    elif event_type == "response.audio_transcript.done":
        role = "assistant"
        transcript_key = "transcript"
    else:
        raise HTTPException(status_code=422, detail="Unsupported provider event")

    item_id = _short_string(event, "item_id")
    event_id = _short_string(event, "event_id", required=False)
    transcript = event.get(transcript_key)
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > MAX_TRANSCRIPT_CHARS:
        raise HTTPException(status_code=422, detail="Malformed provider event")

    # Provider item IDs are opaque. UUID5 gives retries one stable Message key per call/speaker/item.
    message_id = uuid5(call.id, f"{role}:{item_id}")
    existing = await db.get(Message, message_id)
    if existing is not None:
        return {"status": "recorded", "message_id": str(existing.id), "duplicate": True}

    message = Message(
        id=message_id,
        chat_id=call.chat_id,
        parent_id=await get_latest_leaf_message_id(db, call.chat_id),
        role=role,
        content=transcript.strip(),
        model=call.model if role == "assistant" else None,
        provider="qwen" if role == "assistant" else None,
        meta={
            "source": "qwen_realtime_client_event",
            "voice_call_id": str(call.id),
            "provider_item_id": item_id,
            "provider_event_id": event_id,
            "transcript_is_client_reported": True,
        },
        created_at=datetime.now(UTC),
    )
    db.add(message)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.get(Message, message_id)
        if existing is None:
            raise
        return {"status": "recorded", "message_id": str(existing.id), "duplicate": True}
    return {"status": "recorded", "message_id": str(message.id), "duplicate": False}
