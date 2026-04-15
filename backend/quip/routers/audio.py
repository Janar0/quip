"""Generated audio endpoint — serves files from data/generated/.

No auth required: filenames are UUIDv4, equivalent in security to signed URLs.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated"

router = APIRouter(prefix="/api/audio", tags=["audio"])

_MIME = {"wav": "audio/wav", "mp3": "audio/mpeg", "ogg": "audio/ogg", "m4a": "audio/mp4"}


@router.get("/{filename}")
async def get_generated_audio(filename: str):
    """Serve a generated audio file. Public — relies on UUID unguessability."""
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = GENERATED_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Audio not found")

    data = file_path.read_bytes()
    mime = _MIME.get(file_path.suffix.lower().lstrip("."), "audio/wav")

    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )
