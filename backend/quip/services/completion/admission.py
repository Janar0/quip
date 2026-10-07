"""Atomic admission of a prepared turn and attachment claims."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.chat import Chat, ChatRun, Message
from quip.models.file import DocumentChunk, File
from quip.models.user import User
from quip.schemas.chat import CompletionRequest
from quip.services.completion.preparation import _load_attachments, determine_parent


async def admit_chat_turn(
    *,
    req: CompletionRequest,
    user: User,
    chat: Chat,
    user_msg: Message,
    attachments: list[dict],
    is_new_chat: bool,
    user_parent_id: UUID | None,
    effective_model: str,
    research_mode: bool,
    db: AsyncSession,
) -> tuple[Message, ChatRun, list[dict]]:
    # Preparation above may run OCR or other external calls. Keep the
    # user turn private until it can be saved with its assistant and run.
    # End the read transaction so the leaf check below sees current state.
    await db.commit()
    if is_new_chat:
        db.add(chat)
        await db.flush()
    else:
        # A no-op UPDATE reserves SQLite's writer lock for the leaf check,
        # attachment claim and complete turn. Competing requests serialize
        # here, then a stale normal turn is rejected instead of branching.
        await db.execute(update(Chat).where(Chat.id == chat.id).values(updated_at=Chat.updated_at))
        if not req.branch_from_message_id:
            current_parent_id = await determine_parent(db, chat, None)
            if current_parent_id != user_parent_id:
                raise HTTPException(status_code=409, detail="Chat changed while preparing the message. Retry.")

    if attachments:
        file_ids_to_link = [UUID(att["file_id"]) for att in attachments]
        await db.execute(
            update(File)
            .where(
                File.id.in_(file_ids_to_link),
                File.user_id == user.id,
                File.chat_id.is_(None),
                or_(File.workspace_id == chat.workspace_id, File.workspace_id.is_(None)),
            )
            .values(chat_id=chat.id, workspace_id=chat.workspace_id)
        )
        # Re-check after the atomic claim. A competing completion may have
        # linked an unattached file to another chat during preparation.
        attachments = await _load_attachments(file_ids_to_link, user.id, chat.id, chat.workspace_id, db)
        await db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.file_id.in_(file_ids_to_link), DocumentChunk.chat_id.is_(None))
            .values(chat_id=chat.id)
        )

    db.add(user_msg)
    await db.flush()

    assistant_msg = Message(
        chat_id=chat.id,
        role="assistant",
        content="",
        model=effective_model,
        parent_id=user_msg.id,
    )
    db.add(assistant_msg)
    await db.flush()
    run = ChatRun(
        chat_id=chat.id,
        user_id=user.id,
        assistant_message_id=assistant_msg.id,
        status="queued" if research_mode else "running",
        model=effective_model,
        started_at=None if research_mode else datetime.now(UTC),
        run_metadata=(
            {
                "schema_version": 1,
                "task_kind": "research",
                "revision": 0,
                "context_version": 1,
                "cancel_requested": False,
                "steering": [],
                "snapshot": {"progress": [], "subagents": {}, "errors": [], "sources": [], "usage": {}},
            }
            if research_mode
            else {}
        ),
    )
    db.add(run)
    await db.flush()
    await db.commit()

    return assistant_msg, run, attachments
