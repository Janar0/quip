"""Persist completed assistant messages + usage logs.

Runs in a fresh DB session because the streaming response may have already
detached from the request-scoped session by the time we save.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from quip.database import async_session
from quip.models.chat import Chat, Message
from quip.models.usage import UsageLog
from quip.services.artifacts import extract_artifacts

logger = logging.getLogger(__name__)


async def save_assistant_message(
    assistant_msg_id: str,
    chat_id: str,
    user_id,
    content: str,
    model: str,
    usage=None,
    reasoning: str = "",
    tool_executions: list[dict] | None = None,
    search_images: list[dict] | None = None,
    subagent_generations: list[str] | None = None,
):
    """Save the completed assistant message to DB in a fresh session."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Message).where(Message.id == UUID(assistant_msg_id))
            )
            msg = result.scalar_one_or_none()
            if msg:
                chat = await db.get(Chat, UUID(chat_id))
                if chat:
                    chat.updated_at = datetime.now(UTC)
                artifacts, display_content = extract_artifacts(content)
                msg.content = display_content
                if artifacts:
                    msg.artifacts = artifacts
                if tool_executions:
                    msg.tool_calls = tool_executions
                if usage:
                    if isinstance(usage, dict):
                        tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
                        msg.token_count = tokens or None
                        msg.cost = usage.get("cost")
                        msg.provider = usage.get("provider")
                    else:
                        msg.token_count = usage.prompt_tokens + usage.completion_tokens
                        msg.cost = usage.cost
                        msg.provider = usage.provider
                if reasoning:
                    msg.meta = {**(msg.meta or {}), "reasoning": reasoning}
                if search_images:
                    msg.meta = {**(msg.meta or {}), "search_images": search_images}
                if subagent_generations:
                    msg.meta = {**(msg.meta or {}), "subagent_generations": subagent_generations}
                msg.model = model

            if usage:
                def _u(key, default=None):
                    if isinstance(usage, dict):
                        return usage.get(key, default)
                    return getattr(usage, key, default)
                log = UsageLog(
                    user_id=user_id,
                    chat_id=UUID(chat_id),
                    message_id=UUID(assistant_msg_id),
                    model=model,
                    provider=_u("provider"),
                    prompt_tokens=_u("prompt_tokens"),
                    completion_tokens=_u("completion_tokens"),
                    cached_tokens=_u("cached_tokens"),
                    cost=_u("cost"),
                    is_byok=_u("is_byok"),
                    generation_id=_u("generation_id"),
                )
                db.add(log)

            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save assistant message: {e}")
