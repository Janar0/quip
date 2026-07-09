"""Regression tests for server-side outbound URL validation."""

import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from quip.services.image_gen import _read_image_to_base64
from quip.services.scraper import _direct_fetch
from quip.services.url_security import safe_get, validate_outbound_url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "https://user:password@example.com/image.png",
        "http://localhost/admin",
        "http://127.0.0.1/admin",
        "http://10.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/admin",
        "http://[fe80::1]/admin",
    ],
)
async def test_validate_outbound_url_rejects_unsafe_destinations(url):
    with pytest.raises(ValueError):
        await validate_outbound_url(url)


@pytest.mark.asyncio
async def test_validate_outbound_url_rejects_hostname_resolving_private():
    private_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.10", 443))
    ]
    with patch(
        "quip.services.url_security.socket.getaddrinfo",
        return_value=private_result,
    ):
        with pytest.raises(ValueError, match="non-public"):
            await validate_outbound_url("https://internal.example/image.png")


@pytest.mark.asyncio
async def test_validate_outbound_url_accepts_public_resolved_destination():
    public_result = [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
    ]
    with patch(
        "quip.services.url_security.socket.getaddrinfo",
        return_value=public_result,
    ):
        validated = await validate_outbound_url("https://example.com/image.png")

    assert validated == "https://example.com/image.png"


@pytest.mark.asyncio
async def test_safe_get_rejects_redirect_to_private_network():
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/admin"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="non-public"):
            await safe_get(client, "https://93.184.216.34/start")

    assert requests == ["https://93.184.216.34/start"]


@pytest.mark.asyncio
async def test_external_image_reader_never_requests_private_url():
    with patch("quip.services.image_gen.httpx.AsyncClient") as client_factory:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client_factory.return_value = client

        result = await _read_image_to_base64("http://127.0.0.1/secret.png")

    assert result is None
    client.get.assert_not_called()


@pytest.mark.asyncio
async def test_direct_scraper_never_requests_private_url():
    with patch("quip.services.scraper.httpx.AsyncClient") as client_factory:
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client_factory.return_value = client

        with pytest.raises(ValueError, match="non-public"):
            await _direct_fetch("http://169.254.169.254/latest/meta-data", 1000)

    client.get.assert_not_called()
