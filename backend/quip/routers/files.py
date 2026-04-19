"""File upload/download/delete endpoints for images and documents."""
import asyncio
import hashlib
import mimetypes
import os
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File as FastAPIFile, Form, Query, Request
from fastapi.responses import Response
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.models.file import File, DocumentChunk
from quip.services.permissions import get_current_user
from quip.services.auth import decode_token
from quip.services.config import get_setting, get_bool_setting

UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "uploads"

IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/svg+xml"}
DOCUMENT_TYPES = {
    "application/pdf",
    "text/plain",
    "text/markdown",
    "text/csv",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
VIDEO_TYPES = {"video/mp4", "video/webm", "video/mpeg", "video/quicktime", "video/x-msvideo"}
VIDEO_MAX_BYTES = 100 * 1024 * 1024  # 100 MB

router = APIRouter(prefix="/api/files", tags=["files"])


def _classify_file(content_type: str) -> str:
    """Classify file as 'image', 'video', or 'document'."""
    if content_type in IMAGE_TYPES or content_type.startswith("image/"):
        return "image"
    if content_type in VIDEO_TYPES or content_type.startswith("video/"):
        return "video"
    if content_type in DOCUMENT_TYPES:
        return "document"
    if content_type.startswith("text/"):
        return "document"
    return "document"


def _normalize_image(data: bytes, content_type: str, max_size: int = 2 * 1024 * 1024, max_px: int = 2048) -> bytes:
    """Apply EXIF orientation and optionally resize large images."""
    if content_type == "image/svg+xml":
        return data
    is_jpeg = content_type in ("image/jpeg", "image/jpg")
    try:
        from PIL import Image, ImageOps
        import io
        img = Image.open(io.BytesIO(data))

        # Apply EXIF orientation — physically rotates pixels, strips orientation tag
        img = ImageOps.exif_transpose(img)

        # Resize if too large
        if len(data) > max_size:
            ratio = max_px / max(img.size)
            if ratio < 1:
                new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
                img = img.resize(new_size, Image.LANCZOS)

        # Always re-encode JPEGs to strip EXIF and bake in orientation;
        # for other formats, only re-encode if resized
        if is_jpeg or len(data) > max_size:
            buf = io.BytesIO()
            fmt = "JPEG" if is_jpeg else "PNG"
            save_kwargs = {"format": fmt, "optimize": True}
            if fmt == "JPEG":
                save_kwargs["quality"] = 85
            img.save(buf, **save_kwargs)
            return buf.getvalue()

        return data
    except Exception:
        return data


@router.post("/upload")
async def upload_files(
    files: list[UploadFile] = FastAPIFile(...),
    chat_id: str | None = Form(default=None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload one or more files. Returns file metadata."""
    results = []
    user_dir = UPLOAD_DIR / str(user.id)
    user_dir.mkdir(parents=True, exist_ok=True)

    pending_file_ids: list[UUID] = []

    for upload in files:
        data = await upload.read()
        content_type = upload.content_type or "application/octet-stream"
        file_type = _classify_file(content_type)

        # Resize large images; reject oversized videos
        if file_type == "image":
            data = _normalize_image(data, content_type)
        elif file_type == "video" and len(data) > VIDEO_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"Video file too large (max 100 MB)")

        # Hash for dedup
        file_hash = hashlib.sha256(data).hexdigest()

        # Create DB record
        import uuid
        file_id = uuid.uuid4()
        ext = Path(upload.filename or "file").suffix or ""
        storage_name = f"{file_id}{ext}"
        storage_path = f"{user.id}/{storage_name}"

        # Determine initial embedding status
        if file_type in ("image", "video"):
            embedding_status = "skipped"
        elif get_bool_setting("rag_enabled", True):
            embedding_status = "pending"
        else:
            embedding_status = "skipped"

        chat_uuid = UUID(chat_id) if chat_id else None

        file_record = File(
            id=file_id,
            user_id=user.id,
            chat_id=chat_uuid,
            filename=upload.filename or "file",
            content_type=content_type,
            size=len(data),
            file_type=file_type,
            storage_path=storage_path,
            hash=file_hash,
            embedding_status=embedding_status,
        )
        db.add(file_record)

        # Save to filesystem
        file_path = user_dir / storage_name
        file_path.write_bytes(data)

        # Copy to sandbox workspace if available
        if chat_uuid:
            try:
                from quip.services.sandbox import sandbox_manager
                from quip.services.skill_store import get_skill as _gsk
                _sb = _gsk("sandbox")
                if sandbox_manager.available and _sb and _sb.enabled:
                    from quip.database import async_session
                    from quip.models.sandbox import Sandbox
                    async with async_session() as sdb:
                        result = await sdb.execute(
                            select(Sandbox).where(Sandbox.user_id == user.id)
                        )
                        sandbox = result.scalar_one_or_none()
                        if sandbox:
                            await sandbox_manager.ensure_chat_dir(sandbox, str(chat_uuid))
                            # Create uploads subdir and copy file
                            await sandbox_manager._exec(sandbox, f"mkdir -p /workspace/{chat_uuid}/uploads")
                            safe_name = (upload.filename or "file").replace("/", "_").replace("\\", "_").replace("..", "_")
                            await sandbox_manager.write_file(sandbox, str(chat_uuid), f"uploads/{safe_name}", data)
            except Exception:
                pass  # Sandbox copy is best-effort

        # Collect files that need background embedding processing
        if embedding_status == "pending":
            pending_file_ids.append(file_id)

        results.append({
            "id": str(file_id),
            "filename": upload.filename or "file",
            "file_type": file_type,
            "content_type": content_type,
            "size": len(data),
        })

    await db.commit()

    # Kick off background processing AFTER commit so new sessions can see the records
    for fid in pending_file_ids:
        asyncio.create_task(_process_file_background(fid))

    return {"files": results}


async def _process_file_background(file_id: UUID):
    """Process a document file in the background (extract, chunk, embed)."""
    try:
        from quip.database import async_session
        async with async_session() as db:
            from quip.services.documents import process_file
            await process_file(file_id, db)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Background file processing failed for {file_id}: {e}")


@router.get("/{file_id}")
async def get_file(
    file_id: UUID,
    request: Request,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Serve a file. Accepts ?token= query param or Authorization header."""
    # Auth
    if token:
        user = await _auth_from_token(token, db)
    else:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            user = await _auth_from_token(auth_header[7:], db)
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")

    # Lookup file
    result = await db.execute(select(File).where(File.id == file_id, File.user_id == user.id))
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    file_path = UPLOAD_DIR / file_record.storage_path
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    data = file_path.read_bytes()
    mime_type = file_record.content_type or mimetypes.guess_type(file_record.filename)[0] or "application/octet-stream"

    return Response(
        content=data,
        media_type=mime_type,
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a file and its chunks."""
    result = await db.execute(select(File).where(File.id == file_id, File.user_id == user.id))
    file_record = result.scalar_one_or_none()
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")

    # Delete chunks
    await db.execute(delete(DocumentChunk).where(DocumentChunk.file_id == file_id))

    # Delete from filesystem
    file_path = UPLOAD_DIR / file_record.storage_path
    if file_path.exists():
        file_path.unlink()

    await db.delete(file_record)
    await db.commit()


async def _auth_from_token(token: str, db: AsyncSession) -> User:
    """Authenticate user from a JWT token string."""
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
