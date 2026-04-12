"""Migration endpoint — import chats from OpenWebUI export."""
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.models.chat import Chat, Message
from quip.services.permissions import get_current_user

router = APIRouter(prefix="/api/migrate", tags=["migrate"])


@router.post("/openwebui")
async def import_openwebui(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import chats from OpenWebUI JSON export.

    Accepts a JSON file containing a list of chat objects from OpenWebUI's
    "Export All Chats" feature.
    """
    if not file.filename or not file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Please upload a .json file")

    content = await file.read()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")

    # OpenWebUI exports as a list of chat objects
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Expected a list of chat objects")

    imported_chats = 0
    imported_messages = 0
    skipped = 0

    for chat_data in data:
        try:
            chat_obj = chat_data.get("chat", chat_data)
            title = chat_obj.get("title", chat_data.get("title", "Imported Chat"))
            history = chat_obj.get("history", {})
            messages_dict = history.get("messages", {})

            if not messages_dict:
                skipped += 1
                continue

            # Parse timestamp
            created_ts = chat_data.get("created_at")
            if isinstance(created_ts, (int, float)):
                created_at = datetime.fromtimestamp(created_ts, tz=timezone.utc)
            else:
                created_at = datetime.now(timezone.utc)

            updated_ts = chat_data.get("updated_at")
            if isinstance(updated_ts, (int, float)):
                updated_at = datetime.fromtimestamp(updated_ts, tz=timezone.utc)
            else:
                updated_at = created_at

            # Determine model from first assistant message
            model = None
            for msg in messages_dict.values():
                if msg.get("role") == "assistant" and msg.get("model"):
                    model = msg["model"]
                    break

            # Create chat
            chat = Chat(
                user_id=user.id,
                title=title[:500],
                model=model,
                created_at=created_at,
                updated_at=updated_at,
            )
            db.add(chat)
            await db.flush()

            # Sort messages by timestamp and insert
            sorted_msgs = sorted(
                messages_dict.values(),
                key=lambda m: m.get("timestamp", 0),
            )

            for msg_data in sorted_msgs:
                role = msg_data.get("role", "user")
                if role not in ("user", "assistant", "system"):
                    continue

                # Content can be string or list of content blocks
                content = msg_data.get("content", "")
                if isinstance(content, list):
                    # Extract text from content blocks
                    parts = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            parts.append(block.get("text", ""))
                        elif isinstance(block, str):
                            parts.append(block)
                    content = "\n".join(parts)

                if not content:
                    continue

                msg_ts = msg_data.get("timestamp")
                if isinstance(msg_ts, (int, float)):
                    msg_created = datetime.fromtimestamp(msg_ts, tz=timezone.utc)
                else:
                    msg_created = created_at

                msg = Message(
                    chat_id=chat.id,
                    role=role,
                    content=content,
                    model=msg_data.get("model"),
                    created_at=msg_created,
                )
                db.add(msg)
                imported_messages += 1

            imported_chats += 1

        except Exception:
            skipped += 1
            continue

    await db.commit()

    return {
        "imported_chats": imported_chats,
        "imported_messages": imported_messages,
        "skipped": skipped,
    }
