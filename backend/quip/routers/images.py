"""Generated images endpoint — serves files from data/generated/."""
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.services.auth import decode_token

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated"

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{filename}")
async def get_generated_image(
    filename: str,
    request: Request,
    token: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
):
    """Serve a generated image file. Accepts ?token= query param or Authorization header."""
    if token:
        user = await _auth_from_token(token, db)
    else:
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            user = await _auth_from_token(auth_header[7:], db)
        else:
            raise HTTPException(status_code=401, detail="Not authenticated")

    # Sanitize — no directory traversal
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = GENERATED_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found")

    data = file_path.read_bytes()
    ext = file_path.suffix.lower().lstrip(".")
    mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    mime = mime_map.get(ext, "image/png")

    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )


async def _auth_from_token(token: str, db: AsyncSession) -> User:
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user
