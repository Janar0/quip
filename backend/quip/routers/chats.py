from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.models.chat import Chat, Message
from quip.models.sandbox import Sandbox
from quip.services.sandbox import sandbox_manager
from pydantic import BaseModel
from quip.schemas.chat import ChatCreate, ChatUpdate, ChatResponse, ChatWithMessages, MessageResponse
from quip.services.permissions import get_current_user

router = APIRouter(prefix="/api/chats", tags=["chats"])


@router.get("", response_model=list[ChatResponse])
async def list_chats(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    result = await db.execute(
        select(Chat)
        .where(Chat.user_id == user.id, Chat.archived == False)
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
    chat = Chat(user_id=user.id, title=data.title, model=data.model)
    db.add(chat)
    await db.commit()
    await db.refresh(chat)
    return chat


@router.get("/{chat_id}", response_model=ChatWithMessages)
async def get_chat(
    chat_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    msgs = await db.execute(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
    )
    messages = msgs.scalars().all()

    return ChatWithMessages(
        id=chat.id,
        user_id=chat.user_id,
        title=chat.title,
        model=chat.model,
        pinned=chat.pinned,
        archived=chat.archived,
        created_at=chat.created_at,
        updated_at=chat.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
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
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Search across chat titles and message content."""
    pattern = f"%{q}%"
    # Find chats where title or any message content matches
    msg_chat_ids = (
        select(Message.chat_id)
        .join(Chat, Message.chat_id == Chat.id)
        .where(Chat.user_id == user.id, Message.content.ilike(pattern))
        .distinct()
    )
    title_chat_ids = (
        select(Chat.id)
        .where(Chat.user_id == user.id, Chat.title.ilike(pattern))
    )

    result = await db.execute(
        select(Chat)
        .where(or_(Chat.id.in_(msg_chat_ids), Chat.id.in_(title_chat_ids)))
        .order_by(Chat.updated_at.desc())
        .limit(20)
    )
    chats = result.scalars().all()

    # For each matching chat, find the matching message snippet
    results = []
    for chat in chats:
        snippet = None
        msg_result = await db.execute(
            select(Message.content)
            .where(Message.chat_id == chat.id, Message.content.ilike(pattern))
            .limit(1)
        )
        msg = msg_result.scalar_one_or_none()
        if msg:
            # Extract a snippet around the match
            lower = msg.lower()
            idx = lower.find(q.lower())
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
