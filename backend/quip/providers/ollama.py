"""Ollama provider — streams chat completions from a local Ollama instance."""
import json
from typing import AsyncIterator, Optional

import httpx

from quip.providers.openrouter import StreamChunk, UsageInfo, ToolCallDelta

DEFAULT_OLLAMA_URL = "http://localhost:11434"


async def stream_completion(
    messages: list[dict],
    model: str,
    base_url: str = DEFAULT_OLLAMA_URL,
    temperature: float = 0.7,
    max_tokens: Optional[int] = None,
    tools: list[dict] | None = None,
    context_length: int = 0,
) -> AsyncIterator[StreamChunk]:
    """Stream chat completion from Ollama. Yields StreamChunk objects."""

    body: dict = {
        "model": model,
        "messages": messages,
        "stream": True,
        "options": {"temperature": temperature, "num_predict": max_tokens or 4096},
    }
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=10.0)) as client:
        try:
            async with client.stream(
                "POST",
                f"{base_url}/api/chat",
                json=body,
            ) as response:
                if response.status_code != 200:
                    error_body = await response.aread()
                    try:
                        err = json.loads(error_body)
                        msg = err.get("error", f"HTTP {response.status_code}")
                    except (json.JSONDecodeError, AttributeError):
                        msg = f"HTTP {response.status_code}: {error_body.decode()}"
                    yield StreamChunk(error=msg)
                    return

                async for line in response.aiter_lines():
                    if not line:
                        continue

                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "error" in chunk:
                        yield StreamChunk(error=chunk["error"])
                        return

                    msg = chunk.get("message", {})
                    content = msg.get("content", "")
                    done = chunk.get("done", False)

                    # Parse tool calls from Ollama response
                    tc_list = msg.get("tool_calls")
                    parsed_tcs = None
                    if tc_list:
                        parsed_tcs = [
                            ToolCallDelta(
                                index=i,
                                id=f"ollama-tc-{i}",
                                function_name=tc.get("function", {}).get("name", ""),
                                function_arguments=json.dumps(tc.get("function", {}).get("arguments", {})),
                            )
                            for i, tc in enumerate(tc_list)
                        ]

                    if content or parsed_tcs:
                        yield StreamChunk(
                            content=content,
                            model=model,
                            provider="ollama",
                            tool_calls=parsed_tcs,
                        )

                    if done:
                        # Ollama returns usage in the final chunk
                        prompt_tokens = chunk.get("prompt_eval_count", 0)
                        completion_tokens = chunk.get("eval_count", 0)
                        yield StreamChunk(
                            finish_reason="stop",
                            model=model,
                            provider="ollama",
                            usage=UsageInfo(
                                prompt_tokens=prompt_tokens,
                                completion_tokens=completion_tokens,
                                cost=0.0,
                                provider="ollama",
                            ),
                        )

        except httpx.ConnectError:
            yield StreamChunk(error=f"Cannot connect to Ollama at {base_url}. Is it running?")
        except httpx.ReadTimeout:
            yield StreamChunk(error="Ollama request timed out.")
        except Exception as e:
            yield StreamChunk(error=f"Ollama error: {str(e)}")


def _guess_ollama_context_length(model_name: str, details: dict | None = None) -> int:
    """Guess context length from model name heuristics.

    Ollama responses don't always include context_length, but we can infer from
    common model family patterns.
    """
    name_lower = model_name.lower()
    param_size = (details or {}).get("parameter_size", "")

    # Explicit context tags in name: e.g. "qwen-8k", "llama-128k"
    import re
    ctx_match = re.search(r"(\d+)k", name_lower)
    if ctx_match:
        return int(ctx_match.group(1)) * 1024

    # Larger models (70B+) typically have bigger context windows
    if any(x in name_lower for x in ("70b", "72b", "123b", "405b", "120b", "671b")):
        return 32768
    if any(x in name_lower for x in ("30b", "31b", "32b", "33b", "34b", "35b")):
        return 8192
    if any(x in name_lower for x in ("13b", "14b", "20b", "21b", "22b", "27b")):
        return 8192

    # Gemma models are known for long context
    if "gemma" in name_lower:
        if any(x in name_lower for x in ("7b", "9b", "12b")):
            return 8192
        if any(x in name_lower for x in ("2b", "3b")):
            return 4096

    # Default for most 7B/8B models
    return 4096


async def list_models(base_url: str = DEFAULT_OLLAMA_URL) -> list[dict]:
    """Fetch available models from Ollama."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{base_url}/api/tags")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [
                {
                    "id": f"ollama/{m['name']}",
                    "name": f"[Ollama] {m['name']}",
                    "context_length": _guess_ollama_context_length(m.get("name", ""), m.get("details")),
                    "pricing": {"prompt": "0", "completion": "0"},
                    "provider": "ollama",
                    "supports_tools": True,
                }
                for m in data.get("models", [])
            ]
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.ReadError, httpx.RequestError):
            return []
