"""Music generation service — calls OpenRouter audio models (Lyria)."""
import base64
import json
import uuid
from pathlib import Path

import httpx

from quip.providers.openrouter import OPENROUTER_BASE, OPENROUTER_API_KEY
from quip.services.config import get_setting

GENERATED_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated"
MUSIC_MODEL_DEFAULT = "google/lyria-3-clip-preview"


async def generate_music(
    prompt: str,
    model: str = "",
    api_key: str = "",
) -> dict:
    """Call OpenRouter audio generation and save the result to disk.

    Returns:
        {
            "generated_music": True,
            "url": "/api/audio/{filename}",
            "prompt": original prompt,
            "transcript": model's text description,
            "model": model used,
        }
    """
    key = api_key or OPENROUTER_API_KEY
    if not key:
        raise ValueError("No OpenRouter API key configured. Set it in Admin > Settings.")

    if not model:
        model = get_setting("music_model", "") or MUSIC_MODEL_DEFAULT

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Janar0/quip",
        "X-Title": "QUIP",
    }

    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["text", "audio"],
        "audio": {"format": "wav"},
        "stream": True,
    }

    audio_chunks: list[str] = []
    transcript_chunks: list[str] = []
    generation_cost: float = 0.0

    async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=15.0)) as client:
        async with client.stream(
            "POST",
            f"{OPENROUTER_BASE}/chat/completions",
            json=body,
            headers=headers,
        ) as resp:
            if resp.status_code != 200:
                body_bytes = await resp.aread()
                try:
                    err = json.loads(body_bytes)
                    msg = err.get("error", {}).get("message", f"HTTP {resp.status_code}")
                except Exception:
                    msg = f"HTTP {resp.status_code}: {body_bytes[:300].decode(errors='replace')}"
                raise ValueError(f"Music generation failed: {msg}")

            async for line in resp.aiter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    delta = chunk["choices"][0].get("delta", {})
                    audio = delta.get("audio", {})
                    if audio.get("data"):
                        audio_chunks.append(audio["data"])
                    if audio.get("transcript"):
                        transcript_chunks.append(audio["transcript"])
                    usage = chunk.get("usage", {})
                    if usage:
                        generation_cost = float(usage.get("cost", 0) or usage.get("total_cost", 0) or 0)
                except Exception:
                    continue

    if not audio_chunks:
        raise ValueError("No audio returned by the model. Try a different prompt.")

    audio_bytes = base64.b64decode("".join(audio_chunks))

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}.wav"
    (GENERATED_DIR / filename).write_bytes(audio_bytes)

    return {
        "generated_music": True,
        "url": f"/api/audio/{filename}",
        "prompt": prompt,
        "transcript": "".join(transcript_chunks),
        "model": model,
        "cost": generation_cost,
    }
