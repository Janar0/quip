"""Authenticated direct-media Qwen voice session routes."""
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.chat import Chat
from quip.models.user import User
from quip.models.voice import VoiceCall
from quip.schemas.voice import (
    VoiceCallEndResponse,
    VoiceCallStartRequest,
    VoiceCallStartResponse,
    VoiceContextResponse,
    VoiceEventRequest,
    VoiceTaskStartRequest,
    VoiceTaskStartResponse,
    VoiceTaskSteerRequest,
    VoiceTaskSteerResponse,
    VoiceToolRequest,
    VoiceToolResponse,
)
from quip.services.completion.service import _check_budget
from quip.services.permissions import get_current_user
from quip.services.voice.common import get_owned_call
from quip.services.voice.context import VoiceContextService
from quip.services.voice.events import persist_provider_event
from quip.services.voice.session import (
    VoiceProviderError,
    exchange_sdp,
    get_qwen_realtime_config,
    get_qwen_realtime_public_config,
    qwen_realtime_camera_supported,
)
from quip.services.voice.tasks import (
    cancel_delegated_task,
    read_delegated_task,
    start_or_steer_delegated_task,
    steer_delegated_task,
)
from quip.services.voice.tools import cancel_voice_tool, execute_voice_tool

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.get("/config")
async def voice_config(user: User = Depends(get_current_user)):
    """Return authenticated, non-secret model capabilities for the call UI."""
    return get_qwen_realtime_public_config()


@router.get("/calls/{call_id}/context", response_model=VoiceContextResponse)
async def voice_call_context(
    call_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    call = await get_owned_call(db, call_id, user.id)
    if call is None:
        raise HTTPException(status_code=404, detail="Voice call not found")
    if call.status in {"ended", "failed"}:
        raise HTTPException(status_code=409, detail="Voice call has ended")
    chat_result = await db.execute(
        select(Chat).where(Chat.id == call.chat_id, Chat.user_id == user.id)
    )
    chat = chat_result.scalar_one_or_none()
    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")
    packet = await VoiceContextService().build_task_context(
        db, user, chat, "Live voice conversation context"
    )
    return {
        "chat_id": packet.chat_id,
        "context_version": packet.context_version,
        "task_goal": packet.task_goal,
        "summary": packet.summary,
        "summary_sources": list(packet.summary_sources),
        "task_state": packet.task_state,
        "recent": packet.recent,
        "retrieved": packet.retrieved,
        "estimated_tokens": packet.estimated_tokens,
        "instruction": packet.instruction,
    }


@router.post("/calls/{call_id}/events")
async def voice_event(
    call_id: UUID,
    body: VoiceEventRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await persist_provider_event(db, user, call_id, body.event)


@router.post("/calls/{call_id}/tools", response_model=VoiceToolResponse)
async def voice_tool(
    call_id: UUID,
    body: VoiceToolRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await execute_voice_tool(
        db,
        user,
        call_id,
        provider_call_id=body.provider_call_id,
        name=body.name,
        raw_arguments=body.arguments,
    )


@router.post("/calls/{call_id}/tools/{provider_call_id}/cancel")
async def cancel_voice_tool_call(
    call_id: UUID,
    provider_call_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await cancel_voice_tool(db, user, call_id, provider_call_id)


@router.post("/calls/{call_id}/tasks", response_model=VoiceTaskStartResponse, status_code=202)
async def start_voice_task(
    call_id: UUID,
    body: VoiceTaskStartRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await start_or_steer_delegated_task(
        request,
        db,
        user,
        call_id=call_id,
        provider_call_id=body.provider_call_id,
        goal=body.goal,
    )


@router.get("/calls/{call_id}/tasks/{task_id}")
async def voice_task_status(
    call_id: UUID,
    task_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await read_delegated_task(db, request, user, call_id=call_id, task_id=task_id)


@router.post("/calls/{call_id}/tasks/{task_id}/steer", response_model=VoiceTaskSteerResponse)
async def steer_voice_task(
    call_id: UUID,
    task_id: UUID,
    body: VoiceTaskSteerRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await steer_delegated_task(
        db,
        request,
        user,
        call_id=call_id,
        task_id=task_id,
        expected_revision=body.expected_revision,
        idempotency_key=body.idempotency_key,
        instruction=body.instruction,
    )


@router.post("/calls/{call_id}/tasks/{task_id}/cancel")
async def cancel_voice_task(
    call_id: UUID,
    task_id: UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await cancel_delegated_task(db, request, user, call_id=call_id, task_id=task_id)


@router.post("/calls", response_model=VoiceCallStartResponse)
async def start_voice_call(
    body: VoiceCallStartRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    config = get_qwen_realtime_config()
    if not config:
        raise HTTPException(status_code=503, detail="Voice calling is not configured")
    if body.camera_enabled and not qwen_realtime_camera_supported(config.model):
        raise HTTPException(
            status_code=422,
            detail="Camera input is not supported by the configured realtime model",
        )

    chat_result = await db.execute(select(Chat).where(Chat.id == body.chat_id, Chat.user_id == user.id))
    chat = chat_result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Reject exhausted accounts before allocating a call row or contacting Qwen.
    await _check_budget(user, db)

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
        camera_enabled=body.camera_enabled,
    )
    db.add(call)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="A voice call is already active") from None

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
