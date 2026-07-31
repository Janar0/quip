from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.chat import Chat, ChatRun, Message
from quip.models.file import File
from quip.models.sandbox import Sandbox
from quip.models.user import User
from quip.schemas.chat import (
    ChatCreate,
    ChatResponse,
    ChatRunResponse,
    ChatUpdate,
    ChatWithMessages,
    MessageResponse,
)
from quip.services.permissions import get_current_user
from quip.services.sandbox import sandbox_manager
from quip.services.workspaces import ensure_personal_workspace, get_workspace_for_user

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[ChatResponse], response_model_exclude_none=True)
async def list_chats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    workspace_id: UUID | None = Query(default=None),
):
    query = select(Chat).where(Chat.user_id == user.id, Chat.archived.is_(False))
    if workspace_id is not None:
        await get_workspace_for_user(workspace_id, user.id, db)
        query = query.where(Chat.workspace_id == workspace_id)
    result = await db.execute(
        query
        .order_by(Chat.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return result.scalars().all()


@router.post("", response_model=ChatResponse, status_code=status.HTTP_201_CREATED)
async def create_chat(
    data: ChatCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    workspace = (
        await get_workspace_for_user(data.workspace_id, user.id, db)
        if data.workspace_id
        else await ensure_personal_workspace(user, db)
    )
    chat = Chat(
        user_id=user.id,
        workspace_id=workspace.id,
        title=data.title,
        model=data.model or workspace.default_model,
    )
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


@router.get("/{chat_id}", response_model=ChatWithMessages, response_model_exclude_none=True)
async def get_chat(
    chat_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=1000),
    before: int | None = Query(default=None, ge=0, description="Created-at unix-ms cursor; messages strictly older are returned"),
):
    """Return chat metadata and a window of messages.

    Default returns the most recent 200 messages. Pass `before=<unix_ms>` to
    page backwards. Reduces payload on long chats from MBs to ~100KB.
    """
    result = await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    from datetime import datetime
    q = select(Message).where(Message.chat_id == chat_id)
    if before is not None:
        q = q.where(Message.created_at < datetime.fromtimestamp(before / 1000, tz=UTC))
    q = q.order_by(Message.created_at.desc()).limit(limit)
    msgs = await db.execute(q)
    messages = list(msgs.scalars().all())
    messages.reverse()  # caller expects ascending order
    run_result = await db.execute(
        select(ChatRun)
        .where(ChatRun.chat_id == chat_id, ChatRun.user_id == user.id)
        .order_by(ChatRun.created_at.desc())
        .limit(50)
    )

    return ChatWithMessages(
        id=chat.id,
        user_id=chat.user_id,
        workspace_id=chat.workspace_id,
        title=chat.title,
        model=chat.model,
        source=chat.source,
        external_chat_id=chat.external_chat_id,
        external_thread_id=chat.external_thread_id,
        pinned=chat.pinned,
        archived=chat.archived,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
        runs=[ChatRunResponse.model_validate(run) for run in run_result.scalars().all()],
    )


@router.patch("/{chat_id}", response_model=ChatResponse)
async def update_chat(
    chat_id: UUID,
    data: ChatUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    update_data = data.model_dump(exclude_unset=True)
    if "workspace_id" in update_data:
        workspace_id = update_data["workspace_id"]
        if workspace_id is None:
            workspace_id = (await ensure_personal_workspace(user, db)).id
            update_data["workspace_id"] = workspace_id
        else:
            await get_workspace_for_user(workspace_id, user.id, db)
        await db.execute(
            update(File)
            .where(File.chat_id == chat.id, File.user_id == user.id)
            .values(workspace_id=workspace_id)
        )
    for key, value in update_data.items():
        setattr(chat, key, value)
    await db.commit()
    await db.refresh(chat)
    return chat


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat(
    chat_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Clean up sandbox workspace for this chat
    if sandbox_manager.available:
        sb_result = await db.execute(select(Sandbox).where(Sandbox.user_id == user.id))
        sandbox = sb_result.scalar_one_or_none()
        if sandbox:
            try:
                await sandbox_manager.delete_chat_files(sandbox, str(chat_id))
            except Exception:
                pass  # Don't block chat deletion if sandbox cleanup fails

    await db.delete(chat)
    await db.commit()


@router.get("/search/messages")
async def search_chats(
    q: str = Query(..., min_length=1),
    workspace_id: UUID | None = Query(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search across chat titles and message content."""
    if workspace_id is not None:
        await get_workspace_for_user(workspace_id, user.id, db)
    pattern = f"%{q}%"
    # Find chats where title or any message content matches
    msg_chat_ids = (
        select(Message.chat_id)
        .join(Chat, Message.chat_id == Chat.id)
        .where(
            Chat.user_id == user.id,
            Message.content.ilike(pattern),
            *([Chat.workspace_id == workspace_id] if workspace_id else []),
        )
        .distinct()
    )
    title_chat_ids = (
        select(Chat.id)
        .where(
            Chat.user_id == user.id,
            Chat.title.ilike(pattern),
            *([Chat.workspace_id == workspace_id] if workspace_id else []),
        )
    )

    result = await db.execute(
        select(Chat)
        .where(or_(Chat.id.in_(msg_chat_ids), Chat.id.in_(title_chat_ids)))
        .order_by(Chat.updated_at.desc())
        .limit(20)
    )
    chats = result.scalars().all()

    # Fetch one matching message per chat in a single query (was N+1).
    chat_ids = [c.id for c in chats]
    snippets_by_chat: dict[UUID, str] = {}
    if chat_ids:
        msgs_result = await db.execute(
            select(Message.chat_id, Message.content)
            .where(Message.chat_id.in_(chat_ids), Message.content.ilike(pattern))
            .order_by(Message.created_at.desc())
        )
        for cid, content in msgs_result.all():
            if cid not in snippets_by_chat:
                snippets_by_chat[cid] = content

    q_lower = q.lower()
    results = []
    for chat in chats:
        snippet = None
        msg = snippets_by_chat.get(chat.id)
        if msg:
            idx = msg.lower().find(q_lower)
            start = max(0, idx - 40)
            end = min(len(msg), idx + len(q) + 40)
            snippet = ("..." if start > 0 else "") + msg[start:end] + ("..." if end < len(msg) else "")

        results.append({
            "id": str(chat.id),
            "title": chat.title,
            "snippet": snippet,
            "updated_at": chat.updated_at.isoformat() if chat.updated_at else None,
        })

    return {"results": results}


class MessageEdit(BaseModel):
    content: str


# TODO: This endpoint is currently unreachable from the frontend — the UI uses
# branch-based editing (fork + sibling) instead of in-place mutation. Consider
# either wiring it up as an alternative edit mode or removing it in a cleanup pass.
@router.patch("/{chat_id}/messages/{message_id}")
async def edit_message(
    chat_id: UUID,
    message_id: UUID,
    data: MessageEdit,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit a user message's content."""
    result = await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    result = await db.execute(select(Message).where(Message.id == message_id, Message.chat_id == chat_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.content = data.content
    await db.commit()
    return {"status": "ok"}
