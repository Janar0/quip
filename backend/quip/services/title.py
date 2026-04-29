"""Chat-title generation — short call to a cheap model after the first turn."""
from __future__ import annotations

import logging

import httpx

from quip.services.config import get_setting

logger = logging.getLogger(__name__)


async def generate_title(message: str, model: str, api_key: str) -> str | None:
    """Generate a short chat title using a cheap model. Returns None on failure."""
    prompt = (
        f"Write a very short title (3–5 words max) for a conversation that starts with the message below. "
        f"Use the SAME LANGUAGE as the message. Reply with the title only — no quotes, no punctuation.\n\n"
        f"{message[:300]}"
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
                    return r.json()["message"]["content"].strip()
            else:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                )
                if r.is_success:
                    return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None
