import hmac
import logging
import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path

import bcrypt
import jwt
from fastapi import Response

JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("JWT_REFRESH_TOKEN_EXPIRE_DAYS", "30"))
ACCESS_COOKIE_NAME = "quip_access"
REFRESH_COOKIE_NAME = "quip_refresh"
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").strip().lower() in {"1", "true", "yes", "on"}
COOKIE_DOMAIN = os.getenv("COOKIE_DOMAIN") or None
BOOTSTRAP_TOKEN_FILE = Path(
    os.getenv(
        "BOOTSTRAP_TOKEN_FILE",
        str(Path(__file__).resolve().parents[2] / "data" / ".bootstrap_token"),
    )
)

logger = logging.getLogger(__name__)
_bootstrap_token_logged = False


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > 72:
        raise ValueError("Password exceeds bcrypt's 72-byte limit")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except ValueError:
        return False


def create_access_token(user_id: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "exp": datetime.now(UTC) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": datetime.now(UTC) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except (jwt.InvalidTokenError, jwt.ExpiredSignatureError):
        return None


def set_session_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Store browser credentials outside JavaScript-accessible storage."""
    common = {
        "httponly": True,
        "secure": COOKIE_SECURE,
        "samesite": "lax",
        "domain": COOKIE_DOMAIN,
    }
    response.set_cookie(
        ACCESS_COOKIE_NAME,
        access_token,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        path="/",
        **common,
    )
    response.set_cookie(
        REFRESH_COOKIE_NAME,
        refresh_token,
        max_age=REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        path="/api/auth",
        **common,
    )


def clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        ACCESS_COOKIE_NAME,
        path="/",
        domain=COOKIE_DOMAIN,
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        REFRESH_COOKIE_NAME,
        path="/api/auth",
        domain=COOKIE_DOMAIN,
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def ensure_bootstrap_token(*, log_token: bool = False) -> str:
    """Return the install token, creating a mode-0600 token file if needed."""
    global _bootstrap_token_logged
    configured = os.getenv("BOOTSTRAP_TOKEN", "").strip()
    if configured:
        token = configured
    else:
        BOOTSTRAP_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            token = BOOTSTRAP_TOKEN_FILE.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            candidate = secrets.token_urlsafe(32)
            try:
                descriptor = os.open(
                    BOOTSTRAP_TOKEN_FILE,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                )
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    handle.write(candidate)
                token = candidate
            except FileExistsError:
                token = BOOTSTRAP_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError("Bootstrap token file is empty")

    if log_token and not _bootstrap_token_logged:
        logger.warning("First-run administrator bootstrap token: %s", token)
        _bootstrap_token_logged = True
    return token


def verify_bootstrap_token(candidate: str | None) -> bool:
    if not candidate:
        return False
    return hmac.compare_digest(candidate, ensure_bootstrap_token())


def discard_bootstrap_token() -> None:
    """Remove generated bootstrap material after a successful atomic claim."""
    if os.getenv("BOOTSTRAP_TOKEN", "").strip():
        return
    try:
        BOOTSTRAP_TOKEN_FILE.unlink()
    except FileNotFoundError:
        pass
