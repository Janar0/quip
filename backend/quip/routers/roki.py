"""Roki module: Quip authenticates the user, Roki receives a signed identity.

Roki is a separate host service with its own repository and release cycle. This
router only forwards ``/api/roki/<path>`` to Roki's ``/api/<path>``; it never
interprets Roki's API, so Roki fixes ship without rebuilding Quip.
"""
import hashlib
import hmac
import os
import re
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

from quip.core.config import get_setting
from quip.models.user import User
from quip.services.permissions import get_current_user

router = APIRouter(prefix="/api/roki", tags=["roki"])

PATH = re.compile(r"[A-Za-z0-9._~/-]{1,512}")
REQUEST_HEADERS = ("content-type", "if-none-match", "if-modified-since")
RESPONSE_HEADERS = ("content-type", "etag", "last-modified", "content-disposition", "cache-control")

_client: httpx.AsyncClient | None = None


def roki_url() -> str:
    return get_setting("roki_url", "").strip().rstrip("/")


def roki_secret() -> bytes:
    # Environment only: the secret is never stored in Quip's settings table.
    return os.getenv("ROKI_IDENTITY_SECRET", "").strip().encode()


def roki_enabled() -> bool:
    return bool(roki_url()) and len(roki_secret()) >= 32


def sign(secret: bytes, method: str, target: str, user: str, admin: bool, *, now: float | None = None) -> dict[str, str]:
    """Same scheme as roki/quip_identity.py; both repos test one shared vector."""
    stamp = str(int(time.time() if now is None else now))
    flag = "1" if admin else "0"
    message = f"{stamp}\n{user}\n{flag}\n{method.upper()}\n{target}".encode()
    return {
        "X-Roki-User": user,
        "X-Roki-Admin": flag,
        "X-Roki-Time": stamp,
        "X-Roki-Signature": hmac.new(secret, message, hashlib.sha256).hexdigest(),
    }


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=5.0))
    return _client


@router.api_route("/{path:path}", methods=["GET", "POST"])
async def forward(path: str, request: Request, user: User = Depends(get_current_user)):
    if not roki_enabled():
        raise HTTPException(status_code=404, detail="Roki is not configured")
    if not PATH.fullmatch(path) or any(part in ("", ".", "..") for part in path.split("/")):
        raise HTTPException(status_code=404, detail="Not found")
    admin = user.role == "admin"
    if path.startswith("admin/") and not admin:
        raise HTTPException(status_code=403, detail="Admin access required")

    target = "/api/" + path + (f"?{request.url.query}" if request.url.query else "")
    headers = {name: value for name in REQUEST_HEADERS if (value := request.headers.get(name))}
    headers.update(sign(roki_secret(), request.method, target, str(user.id), admin))
    outgoing = client().build_request(
        request.method,
        roki_url() + target,
        headers=headers,
        content=request.stream() if request.method == "POST" else None,
    )
    try:
        upstream = await client().send(outgoing, stream=True)
    except httpx.HTTPError:
        raise HTTPException(status_code=502, detail="Roki is unavailable") from None
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers={name: upstream.headers[name] for name in RESPONSE_HEADERS if name in upstream.headers},
        background=BackgroundTask(upstream.aclose),
    )
