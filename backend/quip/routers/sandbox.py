"""Sandbox file management endpoints — upload, download, list files."""
import mimetypes
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.models.chat import Chat
from quip.models.sandbox import Sandbox
from quip.services.permissions import get_current_user
from quip.services.auth import decode_token
from quip.services.sandbox import sandbox_manager

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])


async def _get_user_sandbox(
    user: User, db: AsyncSession
) -> Sandbox | None:
    """Get the user's sandbox if it exists."""
    result = await db.execute(
        select(Sandbox).where(Sandbox.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def _verify_chat_ownership(
    chat_id: UUID, user: User, db: AsyncSession
) -> None:
    """Verify the user owns this chat."""
    result = await db.execute(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user.id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Chat not found")


@router.get("/{chat_id}/files")
async def list_files(
    chat_id: UUID,
    path: str = ".",
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List files in the chat's sandbox workspace."""
    await _verify_chat_ownership(chat_id, user, db)
    sandbox = await _get_user_sandbox(user, db)
    if not sandbox:
        return {"files": []}

    try:
        files = await sandbox_manager.list_files(sandbox, str(chat_id), path)
        return {
            "files": [
                {"name": f.name, "path": f.path, "size": f.size, "is_dir": f.is_dir}
                for f in files
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


async def _get_user_from_token_param(
    token: str, db: AsyncSession
) -> User:
    """Authenticate user from query param token (for direct download links)."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.get("/{chat_id}/file/{path:path}")
async def download_file(
    chat_id: UUID,
    path: str,
    request: Request,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Download a file. Accepts ?token= query param or Authorization header."""
    if token:
        user = await _get_user_from_token_param(token, db)
    else:
        # Try Authorization header
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            user = await _get_user_from_token_param(auth_header[7:], db)
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")
    await _verify_chat_ownership(chat_id, user, db)
    sandbox = await _get_user_sandbox(user, db)
    if not sandbox:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    try:
        data = await sandbox_manager.read_file(sandbox, str(chat_id), path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"File not found: {e}")

    mime_type, _ = mimetypes.guess_type(path)
    return Response(
        content=data,
        media_type=mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{path.split("/")[-1]}"'},
    )


@router.post("/{chat_id}/upload")
async def upload_file(
    chat_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file to the chat's sandbox workspace."""
    await _verify_chat_ownership(chat_id, user, db)
    sandbox = await sandbox_manager.get_or_create(user.id, db)
    await sandbox_manager.ensure_chat_dir(sandbox, str(chat_id))

    content = await file.read()
    filename = file.filename or "uploaded_file"
    # Sanitize filename
    filename = filename.replace("/", "_").replace("\\", "_").replace("..", "_")

    try:
        await sandbox_manager.write_file(sandbox, str(chat_id), filename, content)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "ok", "filename": filename, "size": len(content)}


@router.get("/{chat_id}/status")
async def sandbox_status(
    chat_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get sandbox status for the current user."""
    await _verify_chat_ownership(chat_id, user, db)
    sandbox = await _get_user_sandbox(user, db)
    if not sandbox:
        return {"status": "none", "container_name": None}

    return {
        "status": sandbox.status,
        "container_name": sandbox.container_name,
        "image_tag": sandbox.image_tag,
        "last_active_at": sandbox.last_active_at.isoformat() if sandbox.last_active_at else None,
    }


@router.delete("/{chat_id}")
async def delete_chat_workspace(
    chat_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete the chat's workspace files (not the whole sandbox)."""
    await _verify_chat_ownership(chat_id, user, db)
    sandbox = await _get_user_sandbox(user, db)
    if sandbox:
        await sandbox_manager.delete_chat_files(sandbox, str(chat_id))
    return {"status": "ok"}
