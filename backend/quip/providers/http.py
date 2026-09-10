"""Connection policy shared by provider requests.

Retry only connection establishment: replaying a partially consumed generation
can duplicate output, tool calls and charges. Keep HTTPX's environment proxy
support, which is needed on networks where direct Internet access is unavailable.
"""

import asyncio
from contextlib import asynccontextmanager

import httpx

CONNECT_ATTEMPTS = 3


async def send_with_connect_retry(client: httpx.AsyncClient, request: httpx.Request, *, stream: bool = False):
    for attempt in range(CONNECT_ATTEMPTS):
        try:
            return await client.send(request, stream=stream)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == CONNECT_ATTEMPTS - 1:
                raise
            await asyncio.sleep(0.5 * 2**attempt)


@asynccontextmanager
async def provider_stream(client: httpx.AsyncClient, method: str, url: str, **kwargs):
    request = client.build_request(method, url, **kwargs)
    response = await send_with_connect_retry(client, request, stream=True)
    try:
        yield response
    finally:
        await response.aclose()


def network_error_message(exc: httpx.RequestError, provider: str = "OpenRouter") -> str:
    detail = str(exc).strip() or str(exc.__cause__ or exc.__class__.__name__)
    if any(
        marker in detail.lower()
        for marker in (
            "name resolution",
            "getaddrinfo",
            "name or service not known",
            "nodename nor servname",
        )
    ):
        return (
            f"Cannot connect to {provider} API: DNS lookup failed after {CONNECT_ATTEMPTS} attempts. "
            "Check DNS and Internet access from the backend process/container and its VPN/proxy settings. "
            "This is a network problem, not an API key error."
        )
    if isinstance(exc, httpx.TimeoutException):
        return f"{provider} request timed out. Please try again."
    return f"Cannot connect to {provider} API. Check the backend's Internet access and proxy settings."
