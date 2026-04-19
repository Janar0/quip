"""Provider logo proxy — downloads lobe-icons SVGs on first request, caches to
disk, serves from disk thereafter. Avoids leaking third-party logos into the
repo and gives the frontend a stable same-origin URL.

No hardcoded whitelist: any slug matching the lobe-icons naming convention
(lowercase alphanumerics + dashes) is tried. Misses are cached in memory so
we don't hammer upstreams for unknown slugs."""
from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

router = APIRouter(prefix="/api/provider-icon", tags=["icons"])

# Cache dir lives alongside the backend package root. Gitignored.
ICONS_DIR = Path(__file__).resolve().parent.parent.parent / "provider_icons"
ICONS_DIR.mkdir(parents=True, exist_ok=True)

# Only allow lobe-icons-shaped slugs — prevents path traversal and stops the
# endpoint from turning into an arbitrary URL proxy.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")

_locks: dict[str, asyncio.Lock] = {}
_negative_cache: set[str] = set()  # slugs that failed upstream; cleared on restart

# Try upstreams in order. npmmirror occasionally 404s, unpkg can rate-limit,
# GitHub raw is slowest but most reliable.
UPSTREAMS = [
    "https://unpkg.com/@lobehub/icons-static-svg@latest/icons/{name}.svg",
    "https://raw.githubusercontent.com/lobehub/lobe-icons/refs/heads/master/packages/static-svg/icons/{name}.svg",
    "https://registry.npmmirror.com/@lobehub/icons-static-svg/latest/files/icons/{name}.svg",
]


async def _fetch_svg(name: str) -> bytes | None:
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for tmpl in UPSTREAMS:
            try:
                r = await client.get(tmpl.format(name=name))
                if r.status_code == 200 and r.content.lstrip().startswith((b"<svg", b"<?xml")):
                    return r.content
            except httpx.HTTPError:
                continue
    return None


# Long cache for misses too — a slug that doesn't exist in lobe-icons won't
# start existing tomorrow, so browsers + service workers shouldn't keep asking.
_MISS_HEADERS = {"Cache-Control": "public, max-age=604800", "X-Icon-Miss": "1"}
_HIT_HEADERS = {"Cache-Control": "public, max-age=86400, immutable"}


def _miss() -> Response:
    return Response(status_code=404, headers=_MISS_HEADERS, content=b"")


@router.get("/{name}")
async def get_provider_icon(name: str):
    name = name.lower().strip()
    if not SLUG_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="invalid slug")
    if name in _negative_cache:
        return _miss()

    local = ICONS_DIR / f"{name}.svg"
    if not local.exists():
        lock = _locks.setdefault(name, asyncio.Lock())
        async with lock:
            if not local.exists() and name not in _negative_cache:
                content = await _fetch_svg(name)
                if content is None:
                    _negative_cache.add(name)
                    return _miss()
                local.write_bytes(content)
        if name in _negative_cache:
            return _miss()

    return Response(
        content=local.read_bytes(),
        media_type="image/svg+xml",
        headers=_HIT_HEADERS,
    )
