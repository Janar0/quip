"""Best-effort delivery of WebUI replies back to their Telegram chat."""

from __future__ import annotations

import logging

import httpx

from quip.core.config import get_setting
from quip.models.chat import Chat

logger = logging.getLogger(__name__)

_MAX_TELEGRAM_TEXT = 4096


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

    try:
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{token}",
            timeout=httpx.Timeout(20.0, connect=5.0),
        ) as client:
            for chunk in _chunks(text):
                rich_response = await client.post(
                    "/sendRichMessage",
                    json={**payload, "rich_message": {"markdown": chunk}},
                )
                rich_body = rich_response.json()
                if rich_body.get("ok"):
                    continue
                plain_response = await client.post(
                    "/sendMessage",
                    json={**payload, "text": chunk},
                )
                plain_response.raise_for_status()
                plain_body = plain_response.json()
                if not plain_body.get("ok"):
                    raise RuntimeError(plain_body.get("description") or "Telegram rejected the message")
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        logger.warning("Could not mirror WebUI reply to Telegram chat %s: %s", external_chat_id, exc)
