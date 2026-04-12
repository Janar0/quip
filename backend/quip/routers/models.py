"""Public models endpoint — returns available models for the model selector.

Models are cached server-side (5 min for OpenRouter, 30s for Ollama)
to avoid hitting external APIs on every page load.
"""
import json
import time

from fastapi import APIRouter, Depends

from quip.models.user import User
from quip.services.permissions import get_current_user
from quip.services.config import get_setting
from quip.providers.openrouter import list_models as or_list_models
from quip.providers.ollama import list_models as ollama_list_models

router = APIRouter(prefix="/api/models", tags=["models"])

# Simple in-memory cache
_cache: dict[str, tuple[float, list]] = {}
OPENROUTER_TTL = 300  # 5 minutes
OLLAMA_TTL = 30       # 30 seconds


def _get_cached(key: str, ttl: float) -> list | None:
    if key in _cache:
        ts, data = _cache[key]
        if time.time() - ts < ttl:
            return data
    return None


def _set_cached(key: str, data: list) -> None:
    _cache[key] = (time.time(), data)


@router.get("")
async def get_available_models(user: User = Depends(get_current_user)):
    models = []

    # OpenRouter models (cached 5 min)
    key = get_setting("openrouter_api_key")
    if key:
        cached = _get_cached("openrouter", OPENROUTER_TTL)
        if cached is not None:
            models.extend(cached)
        else:
            raw = await or_list_models(key)
            or_models = []
            for m in raw:
                pricing = m.get("pricing", {})
                or_models.append({
                    "id": m.get("id", ""),
                    "name": m.get("name", ""),
                    "context_length": m.get("context_length", 0),
                    "pricing": {
                        "prompt": pricing.get("prompt", "0"),
                        "completion": pricing.get("completion", "0"),
                    },
                    "provider": "openrouter",
                })
            _set_cached("openrouter", or_models)
            models.extend(or_models)

    # Ollama models (cached 30s)
    ollama_url = get_setting("ollama_url", "http://localhost:11434")
    cached = _get_cached(f"ollama:{ollama_url}", OLLAMA_TTL)
    if cached is not None:
        models.extend(cached)
    else:
        ollama_models = await ollama_list_models(ollama_url)
        _set_cached(f"ollama:{ollama_url}", ollama_models)
        models.extend(ollama_models)

    # Apply model whitelist filter
    whitelist_raw = get_setting("model_whitelist", "")
    if whitelist_raw:
        try:
            whitelist = json.loads(whitelist_raw)
            if whitelist:
                whitelist_set = set(whitelist)
                models = [m for m in models if m["id"] in whitelist_set]
        except json.JSONDecodeError:
            pass

    # Apply model aliases (display_name override)
    aliases: dict[str, str] = {}
    aliases_raw = get_setting("model_aliases", "")
    if aliases_raw:
        try:
            aliases = json.loads(aliases_raw)
        except json.JSONDecodeError:
            pass
    if aliases:
        models = [
            {**m, "display_name": aliases[m["id"]]} if m["id"] in aliases else m
            for m in models
        ]

    return {"models": models, "default_model": get_setting("default_model") or None}


@router.get("/features")
async def get_features(user: User = Depends(get_current_user)):
    """Return feature flags visible to all authenticated users."""
    return {
        "search_enabled": get_setting("search_enabled", "false") == "true",
    }
