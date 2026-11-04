"""Quip as the OpenID Connect provider for its Rakazo deployment.

There is exactly one client, Rakazo, and one flow: authorization code with PKCE.
Rakazo stays an unmodified upstream install that only needs its OIDC settings.
"""

import base64
import hashlib
import hmac
import os
import re
import secrets
import tempfile
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_setting
from quip.models.oidc import OidcCode
from quip.models.user import User

CLIENT_ID = "rakazo"
CODE_TTL_SECONDS = 60
TOKEN_TTL_SECONDS = 300
MIN_CLIENT_SECRET_BYTES = 32
PKCE_VALUE = re.compile(r"[A-Za-z0-9._~-]{43,128}")


def int_now() -> int:
    return int(time.time())


now = int_now


@dataclass(frozen=True)
class OidcConfig:
    issuer: str
    rakazo_url: str
    client_secret: str

    @property
    def redirect_uri(self) -> str:
        return f"{self.rakazo_url}/api/auth/callback/oidc"


def oidc_config() -> OidcConfig | None:
    public_url = get_setting("public_app_url", "").strip().rstrip("/")
    rakazo_url = get_setting("rakazo_url", "").strip().rstrip("/")
    # Environment only: the secret is never stored in Quip's settings table.
    client_secret = os.getenv("RAKAZO_OIDC_CLIENT_SECRET", "").strip()
    if not public_url or not rakazo_url or len(client_secret.encode()) < MIN_CLIENT_SECRET_BYTES:
        return None
    return OidcConfig(issuer=f"{public_url}/api/oidc", rakazo_url=rakazo_url, client_secret=client_secret)


def _key_path() -> Path:
    default = Path(__file__).resolve().parents[2] / "data" / ".oidc_signing_key.pem"
    return Path(os.getenv("OIDC_SIGNING_KEY_FILE") or default)


@lru_cache(maxsize=1)
def signing_key() -> rsa.RSAPrivateKey:
    """Reuse the persistent key, or atomically publish a new one (see resolve_jwt_secret)."""
    path = _key_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        candidate = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        handle = tempfile.NamedTemporaryFile(mode="wb", prefix=".oidc-key-", dir=path.parent, delete=False)
        candidate_path = Path(handle.name)
        try:
            with handle:
                os.chmod(candidate_path, 0o600)
                handle.write(
                    candidate.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    )
                )
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(candidate_path, path)
            except FileExistsError:
                pass
        finally:
            candidate_path.unlink()
    return serialization.load_pem_private_key(path.read_bytes(), password=None)


def _key_id() -> str:
    public = (
        signing_key()
        .public_key()
        .public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    return hashlib.sha256(public).hexdigest()[:16]


def jwks() -> dict:
    key = jwt.algorithms.RSAAlgorithm.to_jwk(signing_key().public_key(), as_dict=True)
    return {"keys": [{**key, "kid": _key_id(), "use": "sig", "alg": "RS256"}]}


def _code_digest(code: str) -> str:
    return hashlib.sha256(code.encode()).hexdigest()


def verify_pkce(verifier: str, challenge: str) -> bool:
    if not PKCE_VALUE.fullmatch(verifier):
        return False
    computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(computed, challenge)


async def issue_code(
    db: AsyncSession, *, user_id: UUID, redirect_uri: str, code_challenge: str, nonce: str | None
) -> str:
    code = secrets.token_urlsafe(32)
    await db.execute(delete(OidcCode).where(OidcCode.expires_at < now()))
    db.add(
        OidcCode(
            code_hash=_code_digest(code),
            user_id=user_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            nonce=nonce,
            expires_at=now() + CODE_TTL_SECONDS,
            consumed=False,
        )
    )
    await db.commit()
    return code


async def redeem_code(db: AsyncSession, code: str):
    """Atomically consume a live code; concurrent callers cannot both receive it."""
    result = await db.execute(
        update(OidcCode)
        .where(OidcCode.code_hash == _code_digest(code), OidcCode.consumed.is_(False), OidcCode.expires_at >= now())
        .values(consumed=True)
        .returning(OidcCode.user_id, OidcCode.redirect_uri, OidcCode.code_challenge, OidcCode.nonce)
    )
    row = result.first()
    await db.commit()
    return row


async def eligible_user(db: AsyncSession, user_id: UUID) -> User | None:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None or not user.is_active or user.role == "pending":
        return None
    return user


def identity_claims(user: User) -> dict:
    # Quip does not prove mailbox ownership at registration, so this stays false.
    return {
        "sub": str(user.id),
        "email": user.email,
        "email_verified": False,
        "name": user.name,
        "preferred_username": user.username,
    }


def _sign(claims: dict, typ: str) -> str:
    return jwt.encode(claims, signing_key(), algorithm="RS256", headers={"kid": _key_id(), "typ": typ})


def issue_tokens(config: OidcConfig, user: User, nonce: str | None) -> dict:
    issued = int_now()
    expires = issued + TOKEN_TTL_SECONDS
    id_claims = {
        **identity_claims(user),
        "iss": config.issuer,
        "aud": CLIENT_ID,
        "iat": issued,
        "exp": expires,
    }
    if nonce:
        id_claims["nonce"] = nonce
    access_claims = {
        "iss": config.issuer,
        "aud": f"{config.issuer}/userinfo",
        "sub": str(user.id),
        "iat": issued,
        "exp": expires,
    }
    return {
        "access_token": _sign(access_claims, "at+jwt"),
        "id_token": _sign(id_claims, "JWT"),
        "token_type": "Bearer",
        "expires_in": TOKEN_TTL_SECONDS,
        "scope": "openid email profile",
    }


def access_token_subject(config: OidcConfig, token: str) -> UUID | None:
    try:
        claims = jwt.decode(
            token,
            signing_key().public_key(),
            algorithms=["RS256"],
            audience=f"{config.issuer}/userinfo",
            issuer=config.issuer,
        )
        return UUID(claims["sub"])
    except (jwt.InvalidTokenError, KeyError, ValueError):
        return None
