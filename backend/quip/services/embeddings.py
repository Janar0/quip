"""Embedding service — generate embeddings via OpenRouter or Ollama."""
import logging
from typing import Optional

import httpx

from quip.services.config import get_setting

logger = logging.getLogger(__name__)

BATCH_SIZE = 100  # Max texts per API call


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts using the configured provider."""
    if not texts:
        return []

    provider = get_setting("embedding_provider", "openrouter")
    model = get_setting("embedding_model", "openai/text-embedding-3-small")

    all_embeddings: list[list[float]] = []

    # Batch processing
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]

        if provider == "ollama":
            embeddings = await _embed_ollama(batch, model)
        else:
            embeddings = await _embed_openrouter(batch, model)

        if embeddings is None:
            return []
        all_embeddings.extend(embeddings)

    return all_embeddings


async def _embed_openrouter(texts: list[str], model: str) -> Optional[list[list[float]]]:
    """Generate embeddings via OpenRouter (OpenAI-compatible endpoint)."""
    api_key = get_setting("openrouter_api_key")
    if not api_key:
        logger.error("No OpenRouter API key configured for embeddings")
        return None

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/embeddings",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "input": texts,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            # OpenAI format: {"data": [{"embedding": [...], "index": 0}, ...]}
            embeddings_data = data.get("data", [])
            # Sort by index to ensure order
            embeddings_data.sort(key=lambda x: x.get("index", 0))
            return [item["embedding"] for item in embeddings_data]

    except Exception as e:
        logger.error(f"OpenRouter embedding failed: {e}")
        return None


async def _embed_ollama(texts: list[str], model: str) -> Optional[list[list[float]]]:
    """Generate embeddings via Ollama."""
    base_url = get_setting("ollama_url", "http://localhost:11434")

    try:
        # Strip ollama/ prefix if present
        clean_model = model.removeprefix("ollama/")

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/api/embed",
                json={
                    "model": clean_model,
                    "input": texts,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("embeddings", [])

    except Exception as e:
        logger.error(f"Ollama embedding failed: {e}")
        return None
