"""Telegram media download and persistence for the shared QUIP file pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting, get_setting
from quip.models.chat import Chat
from quip.models.file import File
from quip.models.user import User
from quip.services.workspaces import ensure_personal_workspace


class TelegramMediaError(ValueError):
    """A user-safe media ingestion error."""


@dataclass(frozen=True)
class TelegramMedia:
    file_id: str
    kind: str
    filename: str
    content_type: str


def describe_media(message: dict[str, Any]) -> TelegramMedia | None:
    """Extract the one media attachment represented by a Telegram message."""
    photos = message.get("photo")
    if photos:
        photo = max(
            (item for item in photos if item.get("file_id")),
            key=lambda item: (item.get("file_size") or 0, item.get("width") or 0, item.get("height") or 0),
            default=None,
        )
        if photo:
            return TelegramMedia(
                file_id=str(photo["file_id"]),
                kind="image",
                filename=f"telegram-photo-{message.get('message_id', uuid.uuid4().hex)}.jpg",
                content_type="image/jpeg",
            )

    document = message.get("document")
    if document and document.get("file_id"):
        return TelegramMedia(
            file_id=str(document["file_id"]),
            kind="document",
            filename=str(document.get("file_name") or "telegram-document"),
            content_type=str(document.get("mime_type") or "application/octet-stream"),
        )

    video = message.get("video")
    if video and video.get("file_id"):
        return TelegramMedia(
            file_id=str(video["file_id"]),
            kind="video",
            filename=str(video.get("file_name") or "telegram-video.mp4"),
            content_type=str(video.get("mime_type") or "video/mp4"),
        )

    animation = message.get("animation")
    if animation and animation.get("file_id"):
        return TelegramMedia(
            file_id=str(animation["file_id"]),
            kind="video",
            filename=str(animation.get("file_name") or "telegram-animation.mp4"),
            content_type=str(animation.get("mime_type") or "video/mp4"),
        )

    video_note = message.get("video_note")
    if video_note and video_note.get("file_id"):
        return TelegramMedia(
            file_id=str(video_note["file_id"]),
            kind="video",
            filename=f"telegram-video-note-{message.get('message_id', uuid.uuid4().hex)}.mp4",
            content_type="video/mp4",
        )

    audio = message.get("audio")
    if audio and audio.get("file_id"):
        return TelegramMedia(
            file_id=str(audio["file_id"]),
            kind="audio",
            filename=str(audio.get("file_name") or "telegram-audio"),
            content_type=str(audio.get("mime_type") or "audio/mpeg"),
        )

    voice = message.get("voice")
    if voice and voice.get("file_id"):
        return TelegramMedia(
            file_id=str(voice["file_id"]),
            kind="audio",
            filename=f"telegram-voice-{message.get('message_id', uuid.uuid4().hex)}.ogg",
            content_type=str(voice.get("mime_type") or "audio/ogg"),
        )

    return None


def media_prompt(media: TelegramMedia) -> str:
    if media.kind == "image":
        return "Проанализируй прикреплённое изображение."
    if media.kind == "video":
        return "Проанализируй прикреплённое видео."
    if media.kind == "audio":
        return "Сохрани прикреплённую аудиозапись в истории чата. Если транскрипция доступна для выбранной модели, используй её."
    return "Проанализируй прикреплённый файл."


async def persist_media(
    db: AsyncSession,
    user: User,
    chat: Chat,
    media: TelegramMedia,
    api: Any,
) -> File:
    """Download a Telegram attachment and register it in QUIP's normal file store."""
    file_info = await api.call("getFile", {"file_id": media.file_id})
    file_path = str((file_info or {}).get("file_path") or "")
    if not file_path:
        raise TelegramMediaError("Telegram не вернул путь к вложению.")

    try:
        max_bytes = max(1, int(get_setting("telegram_max_file_mb", "20"))) * 1024 * 1024
    except ValueError:
        max_bytes = 20 * 1024 * 1024
    reported_size = int((file_info or {}).get("file_size") or 0)
    if reported_size > max_bytes:
        raise TelegramMediaError(f"Вложение слишком большое. Лимит Telegram для бота: {max_bytes // 1024 // 1024} МБ.")

    data = await api.download_file(file_path)
    if len(data) > max_bytes:
        raise TelegramMediaError(f"Вложение слишком большое. Лимит: {max_bytes // 1024 // 1024} МБ.")

    content_type = media.content_type or mimetypes.guess_type(media.filename)[0] or "application/octet-stream"
    if media.kind == "image":
        from quip.routers.files import _normalize_image

        data = _normalize_image(data, content_type)

    file_id = uuid.uuid4()
    safe_name = Path(media.filename).name.replace("..", "_") or f"telegram-{file_id}"
    suffix = Path(safe_name).suffix
    if not suffix:
        suffix = mimetypes.guess_extension(content_type) or ""
        safe_name = f"{safe_name}{suffix}"
    storage_name = f"{file_id}{suffix}"
    storage_path = f"{user.id}/{storage_name}"
    file_type = media.kind if media.kind in {"image", "video", "audio"} else "document"
    if file_type in {"video", "audio"}:
        embedding_status = "skipped"
    else:
        embedding_status = "pending" if get_bool_setting("rag_enabled", True) else "skipped"

    workspace = await ensure_personal_workspace(user, db)
    file_record = File(
        id=file_id,
        user_id=user.id,
        workspace_id=workspace.id,
        chat_id=chat.id,
        filename=safe_name,
        content_type=content_type,
        size=len(data),
        file_type=file_type,
        storage_path=storage_path,
        hash=hashlib.sha256(data).hexdigest(),
        embedding_status=embedding_status,
    )
    upload_dir = Path(__file__).resolve().parents[2] / "data" / "uploads" / str(user.id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    (upload_dir / storage_name).write_bytes(data)
    db.add(file_record)
    await db.commit()
    await db.refresh(file_record)

    if embedding_status == "pending":
        from quip.routers.files import _process_file_background

        asyncio.create_task(_process_file_background(file_id))
    return file_record
