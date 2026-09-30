"""Authenticated direct-media Qwen voice session routes."""
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.chat import Chat
from quip.models.user import User
from quip.models.voice import VoiceCall
from quip.schemas.voice import VoiceCallEndResponse, VoiceCallStartRequest, VoiceCallStartResponse
from quip.services.permissions import get_current_user
from quip.services.voice.session import VoiceProviderError, exchange_sdp, get_qwen_realtime_config

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/calls", response_model=VoiceCallStartResponse)
async def start_voice_call(
    body: VoiceCallStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = get_qwen_realtime_config()
    if not config:
        raise HTTPException(status_code=503, detail="Voice calling is not configured")

    chat_result = await db.execute(select(Chat).where(Chat.id == body.chat_id, Chat.user_id == user.id))
    chat = chat_result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    active_result = await db.execute(
        select(VoiceCall.id).where(
            VoiceCall.user_id == user.id,
            VoiceCall.status.in_(("connecting", "active")),
        ).limit(1)
    )
    if active_result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="A voice call is already active")

    call = VoiceCall(
        id=uuid4(),
        user_id=user.id,
        chat_id=chat.id,
        provider="qwen",
        model=config.model,
        status="connecting",
    )
    db.add(call)
    await db.commit()

    try:
        answer_sdp = await exchange_sdp(config, body.sdp)
    except VoiceProviderError:
        call.status = "failed"
        call.error_code = "provider_signaling_failed"
        call.ended_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(status_code=502, detail="Voice provider could not establish the session") from None

    return VoiceCallStartResponse(call_id=call.id, sdp=answer_sdp)


@router.post("/calls/{call_id}/end", response_model=VoiceCallEndResponse)
async def end_voice_call(
    call_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(VoiceCall).where(VoiceCall.id == call_id, VoiceCall.user_id == user.id))
    call = result.scalar_one_or_none()
    if not call:
        raise HTTPException(status_code=404, detail="Voice call not found")
    if call.status not in ("ended", "failed"):
        call.status = "ended"
        call.ended_at = datetime.now(UTC)
        await db.commit()
    return VoiceCallEndResponse(call_id=call.id, status="ended")
