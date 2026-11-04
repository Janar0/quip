"""OpenID Connect endpoints that let Rakazo sign people in with their Quip account."""

import base64
import hmac
from urllib.parse import quote, unquote, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.services import oidc
from quip.services.oidc import OidcConfig
from quip.services.permissions import get_optional_current_user

router = APIRouter(prefix="/api/oidc", tags=["oidc"])

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
MAX_NONCE_CHARS = 255


def require_config() -> OidcConfig:
    config = oidc.oidc_config()
    if config is None:
        raise HTTPException(status_code=404, detail="Not found")
    return config


@router.get("/.well-known/openid-configuration")
async def discovery(config: OidcConfig = Depends(require_config)):
    return {
        "issuer": config.issuer,
        "authorization_endpoint": f"{config.issuer}/authorize",
        "token_endpoint": f"{config.issuer}/token",
        "userinfo_endpoint": f"{config.issuer}/userinfo",
        "jwks_uri": f"{config.issuer}/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "scopes_supported": ["openid", "email", "profile"],
        "claims_supported": ["sub", "email", "email_verified", "name", "preferred_username"],
        "token_endpoint_auth_methods_supported": ["client_secret_basic", "client_secret_post"],
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }


@router.get("/jwks")
async def jwks(_: OidcConfig = Depends(require_config)):
    return oidc.jwks()


@router.get("/authorize")
async def authorize(
    request: Request,
    config: OidcConfig = Depends(require_config),
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = request.query_params
    # Exact match first: an error must never be redirected to an unverified address.
    if query.get("client_id") != oidc.CLIENT_ID or query.get("redirect_uri") != config.redirect_uri:
        raise HTTPException(status_code=400, detail="Unknown client or redirect address")

    def respond(**params: str) -> RedirectResponse:
        if state := query.get("state"):
            params["state"] = state
        params["iss"] = config.issuer
        return RedirectResponse(f"{config.redirect_uri}?{urlencode(params)}", status_code=302, headers=NO_STORE)

    if query.get("response_type") != "code":
        return respond(error="unsupported_response_type")
    if "openid" not in query.get("scope", "").split():
        return respond(error="invalid_scope")
    challenge = query.get("code_challenge", "")
    nonce = query.get("nonce")
    if (
        query.get("code_challenge_method") != "S256"
        or not oidc.PKCE_VALUE.fullmatch(challenge)
        or (nonce and len(nonce) > MAX_NONCE_CHARS)
    ):
        return respond(error="invalid_request")

    prompt = query.get("prompt", "").split()
    # Quip's session does not record when the password was entered, so a request for
    # a fresh login is refused instead of answered with an invented auth_time.
    if "login" in prompt or "max_age" in query:
        return respond(error="login_required")
    if user is None:
        if "none" in prompt:
            return respond(error="login_required")
        back = quote(f"{request.url.path}?{request.url.query}", safe="")
        return RedirectResponse(f"/auth/login?next={back}", status_code=302, headers=NO_STORE)

    code = await oidc.issue_code(
        db, user_id=user.id, redirect_uri=config.redirect_uri, code_challenge=challenge, nonce=nonce
    )
    return respond(code=code)


def _token_error(error: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status_code, headers=NO_STORE)


def _client_credentials(request: Request, form) -> tuple[str, str]:
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() == "basic":
        try:
            client_id, _, secret = base64.b64decode(value, validate=True).decode().partition(":")
        except ValueError:
            return "", ""
        return unquote(client_id), unquote(secret)
    return str(form.get("client_id", "")), str(form.get("client_secret", ""))


@router.post("/token")
async def token(
    request: Request,
    config: OidcConfig = Depends(require_config),
    db: AsyncSession = Depends(get_db),
):
    form = await request.form()
    client_id, secret = _client_credentials(request, form)
    if client_id != oidc.CLIENT_ID or not hmac.compare_digest(secret.encode(), config.client_secret.encode()):
        return _token_error("invalid_client", 401)
    if form.get("grant_type") != "authorization_code":
        return _token_error("unsupported_grant_type")
    # The code is spent before any further check, so a failed attempt cannot be retried.
    row = await oidc.redeem_code(db, str(form.get("code", "")))
    if (
        row is None
        or form.get("redirect_uri") != row.redirect_uri
        or not oidc.verify_pkce(str(form.get("code_verifier", "")), row.code_challenge)
    ):
        return _token_error("invalid_grant")
    user = await oidc.eligible_user(db, row.user_id)
    if user is None:
        return _token_error("invalid_grant")
    return JSONResponse(oidc.issue_tokens(config, user, row.nonce), headers=NO_STORE)


@router.get("/userinfo")
async def userinfo(
    request: Request,
    config: OidcConfig = Depends(require_config),
    db: AsyncSession = Depends(get_db),
):
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    subject = oidc.access_token_subject(config, value) if scheme.lower() == "bearer" else None
    user = await oidc.eligible_user(db, subject) if subject else None
    if user is None:
        return JSONResponse(
            {"error": "invalid_token"}, status_code=401, headers={**NO_STORE, "WWW-Authenticate": "Bearer"}
        )
    return JSONResponse(oidc.identity_claims(user), headers=NO_STORE)
