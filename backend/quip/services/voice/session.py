"""Server-only Qwen realtime configuration and WebRTC SDP exchange."""
from dataclasses import dataclass

import httpx

from quip.core.config import get_bool_setting, get_setting


class VoiceProviderError(Exception):
    """Sanitized provider signaling error; never carries provider response text."""


@dataclass(frozen=True)
class QwenRealtimeConfig:
    endpoint: str
    api_key: str
    model: str


def get_qwen_realtime_config() -> QwenRealtimeConfig | None:
    if not get_bool_setting("qwen_voice_enabled", False):
        return None

    endpoint = get_setting("qwen_realtime_endpoint").strip()
    api_key = get_setting("qwen_realtime_api_key").strip()
    model = get_setting("qwen_realtime_model").strip()
    if not endpoint.startswith("https://") or not api_key or not model:
        return None
    return QwenRealtimeConfig(endpoint=endpoint, api_key=api_key, model=model)


async def exchange_sdp(config: QwenRealtimeConfig, offer_sdp: str) -> str:
    """Forward SDP to the operator-configured fixed endpoint, keeping the key server-side."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=5.0)) as client:
            response = await client.post(
                config.endpoint,
                params={"model": config.model},
                content=offer_sdp.encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/sdp",
                    "Accept": "application/sdp",
                },
            )
            response.raise_for_status()
            answer = response.text.strip()
            if not answer or len(answer) > 131_072:
                raise VoiceProviderError("Invalid SDP answer")
            return answer
    except VoiceProviderError:
        raise
    except (httpx.HTTPError, UnicodeError, ValueError) as exc:
        raise VoiceProviderError("Provider signaling failed") from exc
