"""Best-effort delivery of WebUI replies back to their Telegram chat."""

from __future__ import annotations

import logging
import re

import httpx

from quip.core.config import get_setting
from quip.models.chat import Chat
from quip.services.artifacts import extract_artifacts

logger = logging.getLogger(__name__)

_MAX_TELEGRAM_TEXT = 4096
_SOURCE_LINE = re.compile(
    r"^(\s*)\[(\d+)\]\s+(.+?)\s+-\s+(https?://\S+)\s*$", re.MULTILINE
)


def _telegram_text(text: str) -> tuple[str, list[dict]]:
    artifacts, cleaned = extract_artifacts(text)

    def source_link(match: re.Match[str]) -> str:
        prefix, number, title, url = match.groups()
        return f"{prefix}[{number}] [{title}]({url.rstrip('.,;')})"

    cleaned = _SOURCE_LINE.sub(source_link, cleaned)
    return cleaned, artifacts


def _chunks(text: str) -> list[str]:
    chunks: list[str] = []
    remaining = text
    while len(remaining) > _MAX_TELEGRAM_TEXT:
        cut = max(remaining.rfind("\n", 0, _MAX_TELEGRAM_TEXT), remaining.rfind(" ", 0, _MAX_TELEGRAM_TEXT))
        if cut < _MAX_TELEGRAM_TEXT // 2:
            cut = _MAX_TELEGRAM_TEXT
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks or [""]


def _is_telegram_request(request) -> bool:
    client = getattr(request, "client", None)
    return bool(client and getattr(client, "host", "") == "telegram")


async def notify_telegram_chat(chat: Chat, text: str, request) -> None:
    """Mirror a completed WebUI answer to the Telegram origin thread."""
    if chat.source != "telegram" or _is_telegram_request(request) or not text:
        return
    token = get_setting("telegram_bot_token", "").strip()
    external_chat_id = chat.external_chat_id
    if not token or not external_chat_id:
        return

    payload = {"chat_id": external_chat_id}
    if chat.external_thread_id and chat.external_thread_id != "0":
        payload["message_thread_id"] = int(chat.external_thread_id)

    display_text, artifacts = _telegram_text(text)
    try:
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=httpx.Timeout(20.0, connect=5.0),
        ) as client:
            if display_text:
                for chunk in _chunks(display_text):
                    rich_response = await client.post(
                        "/sendRichMessage",
                        json={
                            **payload,
                            "rich_message": {
                                "markdown": chunk,
                                "skip_entity_detection": True,
                            },
                        },
                    )
                    rich_body = rich_response.json()
                    if rich_body.get("ok"):
                        continue
                    plain_response = await client.post(
                        "/sendMessage",
                        json={
                            **payload,
                            "text": chunk,
                            "link_preview_options": {"is_disabled": True},
                        },
                    )
                    plain_response.raise_for_status()
                    plain_body = plain_response.json()
                    if not plain_body.get("ok"):
                        raise RuntimeError(plain_body.get("description") or "Telegram rejected the message")
            for artifact in artifacts:
                fence = chr(96) * 3
                artifact_text = (
                    f"🧩 **{artifact.get('title') or 'Artifact'}**\n\n"
                    f"{fence}{artifact.get('language') or ''}\n"
                    f"{artifact.get('content') or ''}\n{fence}"
                )
                for chunk in _chunks(artifact_text):
                    response = await client.post(
                        "/sendRichMessage",
                        json={
                            **payload,
                            "rich_message": {
                                "markdown": chunk,
                                "skip_entity_detection": True,
                            },
                        },
                    )
                    response.raise_for_status()
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.warning("Could not mirror WebUI reply to Telegram chat %s: %s", external_chat_id, exc)
