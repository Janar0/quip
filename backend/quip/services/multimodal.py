"""Multimodal message helpers — image/video attachment expansion + base64 cache.

Files in `UPLOAD_DIR/<storage_path>` are immutable once written (file_id is unique
per upload). Caching the encoded form by storage_path is therefore safe and
cheap, and avoids re-reading + re-encoding the same image on every chat turn.
"""
from __future__ import annotations

import base64
import logging
import re
from collections import OrderedDict
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Cap the cache to avoid runaway memory growth. Each entry is one encoded file.
# At ~2MB/image average, 64 entries ≈ 128MB worst case.
_B64_CACHE_MAX = 64
_b64_cache: "OrderedDict[str, str]" = OrderedDict()

# Extracted-text cache. Mirrors _b64_cache: file bytes are immutable per
# storage_path so the extraction is too. Avoids re-parsing a 5MB xlsx on every
# follow-up turn of a long chat.
_TEXT_CACHE_MAX = 64
_text_cache: "OrderedDict[str, str]" = OrderedDict()

# Per-file inlined-text cap (~7-8k tokens). One huge spreadsheet shouldn't
# be allowed to blow the entire context window.
_DOC_INLINE_CHAR_CAP = 30_000


def _cached_b64(storage_path_str: str, raw_bytes_loader) -> str:
    """Return base64-encoded file contents, caching by storage path."""
    cached = _b64_cache.get(storage_path_str)
    if cached is not None:
        _b64_cache.move_to_end(storage_path_str)
        return cached
    data = raw_bytes_loader()
    encoded = base64.b64encode(data).decode()
    _b64_cache[storage_path_str] = encoded
    if len(_b64_cache) > _B64_CACHE_MAX:
        _b64_cache.popitem(last=False)
    return encoded


def clear_b64_cache() -> None:
    """Test/admin hook — wipe the cache."""
    _b64_cache.clear()
    _text_cache.clear()


def _truncate(text: str, cap: int = _DOC_INLINE_CHAR_CAP) -> str:
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n…[truncated, {len(text) - cap} more chars]"


async def _extract_document_text(att: dict, db: "AsyncSession | None") -> str:
    """Resolve attached-document text: cache → DocumentChunk rows → on-disk extract."""
    from quip.routers.files import UPLOAD_DIR

    storage_path = att.get("storage_path", "")
    if not storage_path:
        return ""

    cached = _text_cache.get(storage_path)
    if cached is not None:
        _text_cache.move_to_end(storage_path)
        return cached

    text = ""

    # Fast path: the background processor already extracted + chunked this file.
    file_id = att.get("file_id")
    if db is not None and file_id:
        try:
            from sqlalchemy import select
            from quip.models.file import DocumentChunk

            result = await db.execute(
                select(DocumentChunk.content)
                .where(DocumentChunk.file_id == file_id)
                .order_by(DocumentChunk.chunk_index.asc())
            )
            parts = [c for (c,) in result.all() if c]
            if parts:
                text = "\n\n".join(parts)
        except Exception as e:
            logger.warning("DocumentChunk lookup failed for %s: %s", file_id, e)

    # Fallback: re-extract from disk (background job not yet finished, or no chunks).
    if not text:
        full_path = UPLOAD_DIR / storage_path
        if full_path.exists():
            try:
                from quip.services import documents as docs_svc
                result = await docs_svc.extract(str(full_path), att.get("content_type", ""))
                text = "\n\n".join(p.text for p in result.pages if p.text)
            except Exception as e:
                logger.warning("inline extract failed for %s: %s", storage_path, e)

    if text:
        text = _truncate(text)
        _text_cache[storage_path] = text
        if len(_text_cache) > _TEXT_CACHE_MAX:
            _text_cache.popitem(last=False)

    return text


def _format_doc_block(att: dict, text: str) -> str:
    fname = att.get("filename") or att.get("file_id") or "file"
    ftype = att.get("file_type") or "document"
    if not text:
        return f"[Attached file: {fname} ({ftype}) — extraction returned no text]"
    return f"[Attached file: {fname} ({ftype})]\n{text}\n[end of file]"


_VIDEO_URL_PATTERNS = [
    r'https?://(?:www\.)?youtube\.com/watch\S+',
    r'https?://youtu\.be/\S+',
    r'https?://(?:www\.)?rutube\.ru/video/\S+',
    r'https?://(?:www\.)?vk\.com/video\S+',
    r'https?://vkvideo\.ru/\S+',
]


def extract_video_urls(text: str) -> tuple[str, list[str]]:
    """Pull video URLs out of message text. Returns (cleaned_text, [urls])."""
    urls: list[str] = []
    for pattern in _VIDEO_URL_PATTERNS:
        for match in re.findall(pattern, text):
            urls.append(match)
            text = text.replace(match, '')
    return text.strip(), urls


async def build_multimodal_message(
    msg: dict,
    attachments: list[dict],
    is_ollama: bool,
    db: "AsyncSession | None" = None,
) -> tuple[dict, list[str]]:
    """Rewrite a message so attachments become provider-native parts.

    Returns (rewritten_message, inlined_document_file_ids). Caller can use the
    file-id list to suppress duplicate RAG retrieval for those same files on
    this turn.

    Ollama: attaches images as `images: [b64, ...]`; ignores video.
    OpenRouter: returns `content` as a multimodal array of {text, image_url, video_url}.
    Documents: extracted text is prepended to the text content (both providers).
    """
    from quip.routers.files import UPLOAD_DIR

    image_attachments = [a for a in attachments if a.get("file_type") == "image"]
    video_attachments = [a for a in attachments if a.get("file_type") == "video"]
    document_attachments = [a for a in attachments if a.get("file_type") == "document"]
    text = msg.get("content", "")

    text, video_urls = extract_video_urls(text)

    inlined_file_ids: list[str] = []
    doc_blocks: list[str] = []
    for att in document_attachments:
        extracted = await _extract_document_text(att, db)
        if extracted:
            doc_blocks.append(_format_doc_block(att, extracted))
            fid = att.get("file_id")
            if fid:
                inlined_file_ids.append(str(fid))

    if doc_blocks:
        text = ("\n\n".join(doc_blocks) + ("\n\n" + text if text else "")).strip()

    has_media = image_attachments or video_attachments or video_urls
    logger.debug(
        "build_multimodal: %d images, %d videos, %d urls, %d documents",
        len(image_attachments), len(video_attachments), len(video_urls), len(document_attachments),
    )

    if not has_media:
        if doc_blocks:
            return ({**msg, "content": text}, inlined_file_ids)
        return (msg, inlined_file_ids)

    if is_ollama:
        images: list[str] = []
        for att in image_attachments:
            storage_path = att.get("storage_path", "")
            if not storage_path:
                continue
            full_path = UPLOAD_DIR / storage_path
            if full_path.exists():
                images.append(_cached_b64(storage_path, full_path.read_bytes))
        if images:
            return ({**msg, "content": text or msg.get("content", ""), "images": images}, inlined_file_ids)
        if doc_blocks:
            return ({**msg, "content": text}, inlined_file_ids)
        return (msg, inlined_file_ids)

    # OpenRouter / OpenAI multimodal format
    content_parts: list[dict] = []
    text_with_hints = text
    if image_attachments:
        url_hints = [f"/api/files/{att['file_id']}" for att in image_attachments if att.get("file_id")]
        if url_hints:
            text_with_hints = (text + "\n[Uploaded image URLs: " + ", ".join(url_hints) + "]").strip()
    if text_with_hints:
        content_parts.append({"type": "text", "text": text_with_hints})

    for att in image_attachments:
        storage_path = att.get("storage_path", "")
        if not storage_path:
            continue
        full_path = UPLOAD_DIR / storage_path
        if not full_path.exists():
            continue
        b64 = _cached_b64(storage_path, full_path.read_bytes)
        mime = att.get("content_type", "image/png")
        content_parts.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })

    for att in video_attachments:
        storage_path = att.get("storage_path", "")
        if not storage_path:
            continue
        full_path = UPLOAD_DIR / storage_path
        if not full_path.exists():
            continue
        b64 = _cached_b64(storage_path, full_path.read_bytes)
        mime = att.get("content_type", "video/mp4")
        content_parts.append({
            "type": "video_url",
            "video_url": {"url": f"data:{mime};base64,{b64}"},
        })

    for url in video_urls:
        content_parts.append({
            "type": "video_url",
            "video_url": {"url": url},
        })

    if len(content_parts) > 1 or (content_parts and content_parts[0].get("type") != "text"):
        return ({**msg, "content": content_parts}, inlined_file_ids)
    if doc_blocks:
        return ({**msg, "content": text}, inlined_file_ids)
    return (msg, inlined_file_ids)
