"""Generated images endpoint — serves files from data/generated/.

No auth required: filenames are UUIDv4 (122 bits of randomness), equivalent in
security to signed URLs. This lets LLMs and widget templates reference images
by path without needing to attach a per-user token.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated"

router = APIRouter(prefix="/api/images", tags=["images"])


@router.get("/{filename}")
async def get_generated_image(filename: str):
    """Serve a generated image file. Public — relies on UUID unguessability."""
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
