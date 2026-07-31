"""Telegram account linking and OIDC verification helpers."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt
from fastapi import Request
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_setting
from quip.models.chat import Chat, ChatRun
from quip.models.file import File
from quip.models.user import Auth, TelegramLinkToken, User
from quip.services.workspaces import ensure_personal_workspace

TELEGRAM_OAUTH_AUTHORIZE = "https://oauth.telegram.org/auth"
TELEGRAM_OAUTH_TOKEN = "https://oauth.telegram.org/token"
TELEGRAM_OAUTH_JWKS = "https://oauth.telegram.org/.well-known/jwks.json"
TELEGRAM_OAUTH_ISSUER = "https://oauth.telegram.org"
TELEGRAM_LINK_PREFIX = "link_"
TELEGRAM_LINK_TTL = timedelta(minutes=10)
TELEGRAM_OAUTH_TTL = 600


class TelegramAuthError(ValueError):
    """A user-safe Telegram linking/authentication error."""


def _now() -> datetime:
    return datetime.now(UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def telegram_bot_token() -> str:
    return get_setting("telegram_bot_token", "").strip()


def telegram_bot_id(token: str | None = None) -> str:
    raw = token or telegram_bot_token()
    bot_id, separator, _ = raw.partition(":")
    if not separator or not bot_id.isdigit():
        raise TelegramAuthError("Telegram bot token is not configured correctly")
    return bot_id


async def get_telegram_bot_username(token: str | None = None) -> str:
    raw = token or telegram_bot_token()
    if not raw:
        raise TelegramAuthError("Telegram bot is not configured")
    try:
        async with httpx.AsyncClient(
            base_url=f"https://api.telegram.org/bot{raw}",
            timeout=httpx.Timeout(10.0, connect=5.0),
        ) as client:
            response = await client.post("/getMe")
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TelegramAuthError("Telegram bot is unreachable") from exc
    if not body.get("ok") or not body.get("result", {}).get("username"):
        raise TelegramAuthError("Telegram bot token was rejected")
    return str(body["result"]["username"])


def telegram_redirect_uri(request: Request) -> str:
    configured = get_setting("telegram_login_redirect_uri", "").strip()
    if configured:
        return configured
    return str(request.base_url).rstrip("/") + "/api/auth/telegram/callback"


async def create_telegram_link(db: AsyncSession, user: User) -> tuple[str, datetime]:
    raw_token = TELEGRAM_LINK_PREFIX + secrets.token_urlsafe(32)
    expires_at = _now() + TELEGRAM_LINK_TTL
    db.add(
        TelegramLinkToken(
            user_id=user.id,
            token_hash=_token_hash(raw_token),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return raw_token, expires_at


async def create_telegram_claim(db: AsyncSession, telegram_user_id: str) -> tuple[str, datetime]:
    """Create a pending link that Telegram starts and WebUI finishes."""
    raw_token = TELEGRAM_LINK_PREFIX + secrets.token_urlsafe(32)
    expires_at = _now() + TELEGRAM_LINK_TTL
    db.add(
        TelegramLinkToken(
            token_hash=_token_hash(raw_token),
            telegram_user_id=telegram_user_id,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return raw_token, expires_at


async def _link_user_to_telegram(
    db: AsyncSession,
    user: User,
    telegram_user_id: str,
    sender: dict | None = None,
) -> User:
    existing_result = await db.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    existing = existing_result.scalar_one_or_none()
    if existing is not None and existing.id != user.id:
        existing_auth = await db.execute(select(Auth).where(Auth.id == existing.id))
        is_legacy = existing.email.startswith("telegram-") and existing.email.endswith("@local.quip")
        if existing_auth.scalar_one_or_none() is not None or not is_legacy:
            raise TelegramAuthError("This Telegram account is already linked to another QUIP account")
    if user.telegram_user_id and user.telegram_user_id != telegram_user_id:
        raise TelegramAuthError("This QUIP account already has a different Telegram account linked")

    # The first MVP created synthetic telegram-* users. Re-home their chats when
    # the same Telegram identity is linked to a real WebUI account.
    legacy_result = await db.execute(
        select(User).where(
            User.telegram_user_id == telegram_user_id,
            User.id != user.id,
            User.email.like("telegram-%@local.quip"),
        )
    )
    legacy = legacy_result.scalar_one_or_none()
    if legacy is not None:
        auth_result = await db.execute(select(Auth).where(Auth.id == legacy.id))
        if auth_result.scalar_one_or_none() is None:
            workspace = await ensure_personal_workspace(user, db)
            await db.execute(
                update(Chat)
                .where(Chat.user_id == legacy.id)
                .values(user_id=user.id, workspace_id=workspace.id)
            )
            await db.execute(
                update(File)
                .where(File.user_id == legacy.id)
                .values(user_id=user.id, workspace_id=workspace.id)
            )
            await db.execute(update(ChatRun).where(ChatRun.user_id == legacy.id).values(user_id=user.id))
            legacy.telegram_user_id = None

    user.telegram_user_id = telegram_user_id
    if sender:
        display_name = " ".join(
            part for part in [sender.get("first_name"), sender.get("last_name")] if part
        ).strip()
        if display_name and user.name == user.username:
            user.name = display_name[:255]
    return user


async def consume_telegram_link(
    db: AsyncSession,
    raw_token: str,
    telegram_user_id: str,
    sender: dict | None = None,
) -> User:
    if not raw_token.startswith(TELEGRAM_LINK_PREFIX):
        raise TelegramAuthError("Invalid Telegram link")

    result = await db.execute(
        select(TelegramLinkToken).where(TelegramLinkToken.token_hash == _token_hash(raw_token))
    )
    link = result.scalar_one_or_none()
    now = _now()
    if link is None or link.consumed_at is not None or link.expires_at <= now:
        raise TelegramAuthError("This Telegram link has expired or was already used")
    if link.user_id is None:
        raise TelegramAuthError("Open this Telegram link in the QUIP WebUI")

    user = await db.get(User, link.user_id)
    if user is None or not user.is_active:
        raise TelegramAuthError("QUIP account is unavailable")
    await _link_user_to_telegram(db, user, telegram_user_id, sender)
    # Claim atomically so forwarding a link to two chats cannot bind two
    # Telegram identities to the same one-time token.
    claim = await db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.id == link.id,
            TelegramLinkToken.consumed_at.is_(None),
            TelegramLinkToken.expires_at > now,
            TelegramLinkToken.user_id == user.id,
            TelegramLinkToken.telegram_user_id.is_(None),
        )
        .values(consumed_at=now)
    )
    if claim.rowcount != 1:
        raise TelegramAuthError("This Telegram link has expired or was already used")
    await db.commit()
    await db.refresh(user)
    return user


async def claim_telegram_link(db: AsyncSession, raw_token: str, user: User) -> User:
    """Finish a link initiated by /start after the user signs into WebUI."""
    if not raw_token.startswith(TELEGRAM_LINK_PREFIX):
        raise TelegramAuthError("Invalid Telegram link")

    result = await db.execute(
        select(TelegramLinkToken).where(TelegramLinkToken.token_hash == _token_hash(raw_token))
    )
    link = result.scalar_one_or_none()
    now = _now()
    if (
        link is None
        or link.consumed_at is not None
        or link.expires_at <= now
        or link.user_id is not None
        or not link.telegram_user_id
    ):
        raise TelegramAuthError("This Telegram link has expired or was already used")
    if not user.is_active or user.role == "pending":
        raise TelegramAuthError("QUIP account is unavailable")

    telegram_user_id = link.telegram_user_id
    await _link_user_to_telegram(db, user, telegram_user_id)
    claim = await db.execute(
        update(TelegramLinkToken)
        .where(
            TelegramLinkToken.id == link.id,
            TelegramLinkToken.consumed_at.is_(None),
            TelegramLinkToken.expires_at > now,
            TelegramLinkToken.user_id.is_(None),
            TelegramLinkToken.telegram_user_id == telegram_user_id,
        )
        .values(user_id=user.id, consumed_at=now)
    )
    if claim.rowcount != 1:
        raise TelegramAuthError("This Telegram link has expired or was already used")
    await db.commit()
    await db.refresh(user)
    return user


async def unlink_telegram(db: AsyncSession, user: User) -> None:
    user.telegram_user_id = None
    await db.commit()


async def exchange_telegram_code(
    code: str,
    redirect_uri: str,
    bot_token: str,
    code_verifier: str,
) -> dict:
    payload = {
        "client_id": telegram_bot_id(bot_token),
        "client_secret": bot_token,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    }
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.post(TELEGRAM_OAUTH_TOKEN, data=payload)
            response.raise_for_status()
            body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise TelegramAuthError("Telegram authorization failed") from exc
    if not body.get("id_token"):
        raise TelegramAuthError("Telegram did not return an identity token")
    return body


async def verify_telegram_id_token(id_token: str, bot_token: str, nonce: str | None = None) -> dict:
    bot_id = telegram_bot_id(bot_token)
    try:
        header = jwt.get_unverified_header(id_token)
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0)) as client:
            response = await client.get(TELEGRAM_OAUTH_JWKS)
            response.raise_for_status()
            keys = response.json().get("keys", [])
        jwk = next(key for key in keys if key.get("kid") == header.get("kid"))
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
        claims = jwt.decode(
            id_token,
            public_key,
            algorithms=["RS256"],
            audience=bot_id,
            issuer=TELEGRAM_OAUTH_ISSUER,
        )
    except (StopIteration, KeyError, ValueError, TypeError, jwt.InvalidTokenError, httpx.HTTPError) as exc:
        raise TelegramAuthError("Telegram identity token is invalid") from exc
    if not claims.get("sub"):
        raise TelegramAuthError("Telegram identity token has no user")
    if nonce is not None and claims.get("nonce") != nonce:
        raise TelegramAuthError("Telegram identity token nonce is invalid")
    return claims


def build_telegram_authorization_url(
    request: Request,
    state: str,
    code_verifier: str,
    nonce: str | None = None,
) -> str:
    bot_token = telegram_bot_token()
    params = {
        "client_id": telegram_bot_id(bot_token),
        "redirect_uri": telegram_redirect_uri(request),
        "response_type": "code",
        "scope": "openid profile",
        "state": state,
        "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode("ascii"),
        "code_challenge_method": "S256",
    }
    if nonce:
        params["nonce"] = nonce
    return f"{TELEGRAM_OAUTH_AUTHORIZE}?{urlencode(params)}"


def oauth_cookie_options() -> dict:
    secure = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
    return {
        "httponly": True,
        "secure": secure,
        "samesite": "lax",
        "path": "/api/auth/telegram",
    }


def telegram_oauth_ttl() -> int:
    return TELEGRAM_OAUTH_TTL


def telegram_oauth_error_redirect(message: str) -> str:
    # Keep provider errors out of the URL; the frontend only needs a stable key.
    return "/auth/login?telegram_error=" + ("configuration" if "configured" in message else "failed")
