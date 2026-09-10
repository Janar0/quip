"""OpenRouter provider — streams chat completions via OpenRouter API.

Handles all OpenRouter-specific quirks:
- Model names with provider prefix (anthropic/claude-sonnet-4.5)
- cache_control for Anthropic models
- `: OPENROUTER PROCESSING` SSE keep-alive comments
- usage.cost in final chunk (empty choices)
- generation_id from X-Generation-Id header
- native_finish_reason alongside finish_reason
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from copy import deepcopy

import httpx

from quip.providers.http import network_error_message, provider_stream, send_with_connect_retry
from quip.providers.types import StreamChunk, ToolCallDelta, UsageInfo

logger = logging.getLogger(__name__)

OPENROUTER_BASE = "https://openrouter.ai/api/v1"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")


def _build_headers(api_key: str) -> dict:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Janar0/quip",
        "X-Title": "QUIP",
    }


def _should_add_cache_control(model: str) -> bool:
    """Anthropic models benefit from cache_control."""
    return model.startswith("anthropic/")


def _mark_last_text_part(parts: list[dict], cache_marker: dict) -> None:
    """Add cache_control to the last text part in a multimodal content array."""
    for part in reversed(parts):
        if part.get("type") == "text":
            part["cache_control"] = cache_marker
            return


def _inject_cache_control(messages: list[dict]) -> list[dict]:
    """Add cache_control to the last user/system message for Anthropic prompt caching.

    Anthropic caches everything up to and including the marked message.
    We mark the second-to-last message (last context before the new user turn)
    so that conversation history gets cached across turns.
    """
    msgs = deepcopy(messages)

    # Find the last two user/system messages to mark as cache breakpoints
    # - Mark the system prompt (if any) so it's always cached
    # - Mark the second-to-last message so prior conversation history is cached
    cache_marker = {"type": "ephemeral"}

    # Mark system message if present
    if msgs and msgs[0]["role"] == "system":
        content = msgs[0]["content"]
        if isinstance(content, str):
            msgs[0]["content"] = [{"type": "text", "text": content, "cache_control": cache_marker}]
        elif isinstance(content, list):
            _mark_last_text_part(content, cache_marker)

    # Mark the second-to-last message (prior context) if we have 3+ messages
    if len(msgs) >= 3:
        target = msgs[-2]
        content = target.get("content")
        if isinstance(content, str):
            target["content"] = [{"type": "text", "text": content, "cache_control": cache_marker}]
        elif isinstance(content, list):
            _mark_last_text_part(content, cache_marker)

    return msgs


DEFAULT_MAX_TOKENS = 4096


def build_request_body(
    model: str,
    messages: list[dict],
    temperature: float = 0.7,
    max_tokens: int | None = None,
    stream: bool = True,
    tools: list[dict] | None = None,
) -> dict:
    # Auto-inject cache_control for Anthropic models
    if _should_add_cache_control(model):
        messages = _inject_cache_control(messages)

    body: dict = {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": temperature,
        "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
    }
    if tools:
        body["tools"] = tools

    return body


async def stream_completion(
    messages: list[dict],
    model: str,
    api_key: str = "",
    temperature: float = 0.7,
    max_tokens: int | None = None,
    tools: list[dict] | None = None,
    context_length: int = 0,
) -> AsyncIterator[StreamChunk]:
    """Stream chat completion from OpenRouter. Yields StreamChunk objects."""

    key = api_key or OPENROUTER_API_KEY
    if not key:
        yield StreamChunk(error="No OpenRouter API key configured. Set it in Admin > Settings.")
        return

    resolved_max = max_tokens or DEFAULT_MAX_TOKENS
    body = build_request_body(model, messages, temperature, resolved_max, stream=True, tools=tools)
    headers = _build_headers(key)

    generation_id = ""

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0)) as client:
        try:
            async with provider_stream(
                client, "POST", f"{OPENROUTER_BASE}/chat/completions", json=body, headers=headers
            ) as response:
                # Capture generation ID from header
                generation_id = response.headers.get("x-generation-id", "")

                if response.status_code != 200:
                    error_body = await response.aread()
                    try:
                        err = json.loads(error_body)
                        msg = err.get("error", {}).get("message", f"HTTP {response.status_code}")
                    except (json.JSONDecodeError, AttributeError):
                        msg = f"HTTP {response.status_code}: {error_body.decode()}"
                    yield StreamChunk(error=msg)
                    return

                async for line in response.aiter_lines():
                    # Skip empty lines and OpenRouter keep-alive comments
                    if not line or line.startswith(":"):
                        continue

                    # Strip "data: " prefix
                    if not line.startswith("data:"):
                        continue
                    line = line[5:].lstrip()

                    if line == "[DONE]":
                        return

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Check for error in chunk (mid-stream errors)
                    if not isinstance(chunk, dict):
                        continue

                    if "error" in chunk:
                        err = chunk["error"]
                        msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                        yield StreamChunk(error=msg)
                        return

                    provider = chunk.get("provider", "")
                    model_name = chunk.get("model", model)
                    choices = chunk.get("choices") or []

                    # Check for usage data in any chunk (may come with or without choices)
                    usage_chunk = None
                    if isinstance(chunk.get("usage"), dict):
                        usage_data = chunk["usage"]
                        prompt_details = usage_data.get("prompt_tokens_details") or {}
                        usage_chunk = UsageInfo(
                            prompt_tokens=usage_data.get("prompt_tokens", 0),
                            completion_tokens=usage_data.get("completion_tokens", 0),
                            cached_tokens=prompt_details.get("cached_tokens", 0),
                            cost=usage_data.get("cost", 0.0) or 0.0,
                            is_byok=usage_data.get("is_byok", False),
                            generation_id=generation_id,
                            provider=provider,
                        )

                    # Final chunk with usage only (empty choices)
                    if not choices:
                        if usage_chunk:
                            yield StreamChunk(usage=usage_chunk, model=model_name, provider=provider)
                        continue

                    # Normal content chunk
                    for choice in choices:
                        delta = choice.get("delta") or {}
                        content = delta.get("content", "")
                        reasoning = delta.get("reasoning", "") or delta.get("reasoning_content", "")
                        finish = choice.get("finish_reason")

                        # Parse tool call deltas
                        tc_deltas = delta.get("tool_calls")
                        parsed_tcs = None
                        if tc_deltas:
                            parsed_tcs = [
                                ToolCallDelta(
                                    index=tc.get("index", 0),
                                    id=tc.get("id", ""),
                                    function_name=tc.get("function", {}).get("name", ""),
                                    function_arguments=tc.get("function", {}).get("arguments", ""),
                                )
                                for tc in tc_deltas
                            ]

                        if content or reasoning or finish or parsed_tcs:
                            yield StreamChunk(
                                content=content or "",
                                reasoning=reasoning or "",
                                finish_reason=finish,
                                model=model_name,
                                provider=provider,
                                tool_calls=parsed_tcs,
                            )

                    # Yield usage if it came with a content chunk
                    if usage_chunk:
                        yield StreamChunk(usage=usage_chunk, model=model_name, provider=provider)

        except httpx.RequestError as exc:
            logger.warning("OpenRouter request failed: %s", type(exc).__name__)
            yield StreamChunk(error=network_error_message(exc))
        except Exception:
            logger.exception("Invalid OpenRouter response")
            yield StreamChunk(error="OpenRouter returned an invalid response. Please try again.")


async def _get_data(path: str, api_key: str, fallback, *, params: dict | None = None):
    key = api_key or OPENROUTER_API_KEY
    if not key:
        return fallback
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            request = client.build_request(
                "GET",
                f"{OPENROUTER_BASE}/{path}",
                headers=_build_headers(key),
                params=params,
            )
            response = await send_with_connect_retry(client, request)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data") if isinstance(payload, dict) else None
            return data if isinstance(data, type(fallback)) else fallback
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("OpenRouter %s unavailable: %s", path, type(exc).__name__)
        return fallback


async def get_generation(generation_id: str, api_key: str = "") -> dict:
    """Optional billing metadata must not break an otherwise successful answer."""
    if not generation_id:
        return {}
    return await _get_data("generation", api_key, {}, params={"id": generation_id})


async def list_models(api_key: str = "") -> list[dict]:
    return await _get_data("models", api_key, [])


async def get_key_info(api_key: str = "") -> dict:
    """Settings stay accessible when the provider is offline."""
    return await _get_data("key", api_key, {})
