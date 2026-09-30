"""Small source projection from search tool results for durable UI snapshots."""

import ipaddress
import json
from urllib.parse import urlsplit, urlunsplit


def validated_search_sources(result_json: str, *, limit: int = 30) -> list[dict[str, str]]:
    """Extract only public HTTP(S) citations returned by the search tool."""
    try:
        payload = json.loads(result_json)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return []

    sources = []
    seen = set()
    for item in payload["results"]:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        if not isinstance(raw_url, str):
            continue
        try:
            parts = urlsplit(raw_url.strip())
            host = (parts.hostname or "").lower().rstrip(".")
            if (
                parts.scheme.lower() not in {"http", "https"}
                or not host
                or parts.username
                or parts.password
                or host in {"localhost", "localhost.localdomain"}
                or host.endswith(".localhost")
                or host.endswith(".local")
            ):
                continue
            try:
                if not ipaddress.ip_address(host).is_global:
                    continue
            except ValueError:
                pass
        except ValueError:
            continue
        url = urlunsplit((parts.scheme.lower(), parts.netloc, parts.path, parts.query, ""))
        if url in seen:
            continue
        seen.add(url)
        sources.append({
            "title": str(item.get("title") or host)[:240],
            "url": url[:2000],
            "snippet": str(item.get("snippet") or item.get("content") or "")[:600],
        })
        if len(sources) >= max(1, min(limit, 30)):
            break
    return sources
