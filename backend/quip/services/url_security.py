"""Validation helpers for server-side HTTP requests to untrusted URLs."""

import asyncio
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import httpx

_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


def _validate_ip_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    """Reject every address that is not globally routable."""
    if not address.is_global:
        raise ValueError("URL resolves to a non-public network address")


async def validate_outbound_url(url: str) -> str:
    """Validate an untrusted outbound URL and all of its resolved addresses.

    Only public HTTP(S) destinations are accepted. Hostnames that resolve to
    any loopback, private, link-local, shared, reserved, or otherwise
    non-global address are rejected.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("URL is required")

    normalized = url.strip()
    try:
        parsed = urlsplit(normalized)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL") from exc

    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http and https URLs are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs containing credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL hostname is required")

    hostname = hostname.rstrip(".")
    if hostname.lower() == "localhost" or hostname.lower().endswith(".localhost"):
        raise ValueError("Localhost URLs are not allowed")

    # IP literals can be classified without a DNS lookup. Strip an IPv6 zone
    # identifier if present; scoped addresses are non-global and rejected.
    literal = hostname.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(literal)
    except ValueError:
        address = None
    if address is not None:
        _validate_ip_address(address)
        return normalized

    lookup_port = port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        records = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            lookup_port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError("URL hostname could not be resolved") from exc

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for record in records:
        raw_address = record[4][0].split("%", 1)[0]
        try:
            addresses.add(ipaddress.ip_address(raw_address))
        except ValueError as exc:
            raise ValueError("URL resolved to an invalid address") from exc

    if not addresses:
        raise ValueError("URL hostname did not resolve to an address")
    for address in addresses:
        _validate_ip_address(address)

    return normalized


async def safe_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    max_redirects: int = 5,
    **kwargs,
) -> httpx.Response:
    """GET a validated public URL, validating every redirect destination."""
    current_url = await validate_outbound_url(url)

    for redirect_count in range(max_redirects + 1):
        response = await client.get(current_url, follow_redirects=False, **kwargs)
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response
        if redirect_count >= max_redirects:
            await response.aclose()
            raise ValueError("Too many redirects")

        next_url = urljoin(str(response.url), location)
        await response.aclose()
        current_url = await validate_outbound_url(next_url)

    raise ValueError("Too many redirects")
