"""Small shared helpers for per-call ownership and transcript ordering."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Message
from quip.models.voice import VoiceCall


async def get_owned_call(db: AsyncSession, call_id: UUID, user_id: UUID) -> VoiceCall | None:
    result = await db.execute(select(VoiceCall).where(VoiceCall.id == call_id, VoiceCall.user_id == user_id))
    return result.scalar_one_or_none()


async def get_latest_leaf_message_id(db: AsyncSession, chat_id: UUID) -> UUID | None:
    child_parents = select(Message.parent_id).where(
        Message.chat_id == chat_id,
        Message.parent_id.is_not(None),
    )
    result = await db.execute(
        select(Message.id)
        .where(Message.chat_id == chat_id, ~Message.id.in_(child_parents))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()
