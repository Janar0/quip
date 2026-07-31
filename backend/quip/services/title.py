"""Chat-title generation — short call to a cheap model after the first turn."""
from __future__ import annotations

import json
import logging
import re

import httpx

from quip.core.config import get_setting

logger = logging.getLogger(__name__)

_IMPLICIT_CHAT_TITLES = frozenset(
    {
        "telegram chat",
        "new chat",
        "новый чат",
        "новая тема",
        "new topic",
    }
)

_FALLBACK_EMOJIS = (
    ("погод|weather|дожд|температур|снег", "🌤"),
    ("код|программ|python|javascript|api|сервер", "💻"),
    ("рецепт|еда|готов|recipe|cook", "🍽"),
    ("путеше|отпуск|город|место|travel", "🧭"),
    ("спорт|матч|футбол", "🏆"),
    ("музык|песн|music", "🎵"),
    ("работ|план|проект|задач", "📋"),
)


def fallback_chat_emoji(message: str) -> str:
    lowered = message.lower()
    for pattern, emoji in _FALLBACK_EMOJIS:
        if re.search(pattern, lowered):
            return emoji
    return "💬"


def is_implicit_chat_title(title: str | None) -> bool:
    return bool(title and title.strip().casefold() in _IMPLICIT_CHAT_TITLES)


def _clean_title(value: object, message: str) -> str:
    title = str(value or "").strip().strip("\"'`*#")
    title = re.sub(r"\s+", " ", title).strip(" .,:;!?—–-")
    return (title or message[:50] or "Новый чат")[:200]


def _parse_identity(raw: str, message: str) -> tuple[str, str]:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    title = cleaned
    emoji = fallback_chat_emoji(message)
    try:
        payload = json.loads(cleaned)
        if isinstance(payload, dict):
            title = payload.get("title", "")
            candidate = str(payload.get("emoji", "")).strip()
            if candidate and any(ord(char) > 0x1F000 for char in candidate):
                emoji = candidate[:8]
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return _clean_title(title, message), emoji


async def generate_chat_identity(message: str, model: str, api_key: str) -> tuple[str, str] | None:
    """Generate a short title and one emoji; return None only on provider failure."""
    prompt = (
        "Return ONLY strict JSON with exactly two fields: "
        '{"title":"3-5 word title in the same language","emoji":"one emoji"}. '
        "Choose one specific emoji that matches the topic. Do not use generic "
        "speech bubbles or smileys unless the topic is genuinely general. "
        "No markdown, no explanation, no quotes around the whole JSON.\n\n"
        f"Conversation opening message:\n{message[:300]}"
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if model.startswith("ollama/"):
                ollama_base = get_setting("ollama_url", "http://localhost:11434")
                r = await client.post(
                    f"{ollama_base}/api/chat",
                    json={
                        "model": model.removeprefix("ollama/"),
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                if r.is_success:
                    raw = r.json()["message"]["content"]
                    return _parse_identity(raw, message)
            else:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                )
                if r.is_success:
                    raw = r.json()["choices"][0]["message"]["content"]
                    return _parse_identity(raw, message)
    except Exception:
        logger.exception("Chat identity generation failed")
    return None


async def generate_title(message: str, model: str, api_key: str) -> str | None:
    """Generate a short chat title using a cheap model. Returns None on failure."""
    identity = await generate_chat_identity(message, model, api_key)
    return identity[0] if identity else None
