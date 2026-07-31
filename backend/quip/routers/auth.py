import os
import secrets
from datetime import UTC, datetime
from urllib.parse import urlencode
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from quip.database import get_db
from quip.models.bootstrap import BootstrapState
from quip.models.user import Auth, User
from quip.schemas.user import RefreshRequest, TokenResponse, UserLogin, UserRegister, UserResponse
from quip.services.auth import (
    clear_session_cookies,
    create_access_token,
    create_refresh_token,
    decode_token,
    discard_bootstrap_token,
    ensure_bootstrap_token,
    hash_password,
    set_session_cookies,
    verify_bootstrap_token,
    verify_password,
)
from quip.services.permissions import get_current_user, get_optional_current_user
from quip.services.telegram_auth import (
    TelegramAuthError,
    build_telegram_authorization_url,
    claim_telegram_link,
    create_telegram_link,
    exchange_telegram_code,
    get_telegram_bot_username,
    oauth_cookie_options,
    telegram_bot_token,
    telegram_oauth_error_redirect,
    telegram_oauth_ttl,
    telegram_redirect_uri,
    unlink_telegram,
    verify_telegram_id_token,
)
from quip.services.workspaces import ensure_personal_workspace

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")


async def _get_or_create_bootstrap_state(db: AsyncSession) -> BootstrapState:
    state = await db.get(BootstrapState, 1)
    if state is not None:
        return state
    count_result = await db.execute(select(func.count()).select_from(User))
    state = BootstrapState(id=1, completed=(count_result.scalar_one() > 0))
    db.add(state)
    await db.flush()
    return state


@router.get("/setup")
async def setup_status(db: AsyncSession = Depends(get_db)):
    state = await db.get(BootstrapState, 1)
    if state is None:
        count_result = await db.execute(select(func.count()).select_from(User))
        required = count_result.scalar_one() == 0
    else:
        required = not state.completed
    if required:
        ensure_bootstrap_token(log_token=True)
    return {
        "required": required,
        "admin_email_configured": bool(ADMIN_EMAIL.strip()),
    }


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: UserRegister, response: Response, db: AsyncSession = Depends(get_db)):
    email = data.email.lower().strip()
    username = data.username.strip()
    # Check duplicate email
    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    # Check duplicate username
    existing = await db.execute(select(User).where(func.lower(User.username) == username.lower()))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    state = await _get_or_create_bootstrap_state(db)
    bootstrap_claimed = False
    if not state.completed:
        email_authorized = bool(ADMIN_EMAIL.strip()) and email == ADMIN_EMAIL.lower().strip()
        if not email_authorized and not verify_bootstrap_token(data.bootstrap_token):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrator bootstrap token required",
            )
        user_id = uuid4()
        claim = await db.execute(
            update(BootstrapState)
            .where(BootstrapState.id == 1, BootstrapState.completed.is_(False))
            .values(
                completed=True,
                claimed_by=user_id,
                completed_at=datetime.now(UTC),
            )
        )
        if claim.rowcount != 1:
            raise HTTPException(status_code=409, detail="Administrator bootstrap already claimed")
        role = "admin"
        bootstrap_claimed = True
    else:
        user_id = uuid4()
        role = "pending"

    user = User(
        id=user_id,
        email=email,
        username=username,
        name=data.name,
        role=role,
    )
    db.add(user)
    await db.flush()

    auth = Auth(id=user.id, password_hash=hash_password(data.password))
    db.add(auth)
    await ensure_personal_workspace(user, db)
    await db.commit()
    if bootstrap_claimed:
        discard_bootstrap_token()

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == data.email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    result = await db.execute(select(Auth).where(Auth.id == user.id))
    auth = result.scalar_one_or_none()
    if not auth or not verify_password(data.password, auth.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    if user.role == "pending":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval")

    user.last_active_at = datetime.now(UTC)
    await db.commit()

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    return tokens


@router.get("/telegram/link")
async def create_telegram_link_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        bot_username = await get_telegram_bot_username()
    except TelegramAuthError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    raw_token, expires_at = await create_telegram_link(db, user)
    return {
        "url": f"https://t.me/{bot_username}?start={raw_token}",
        "expires_at": expires_at,
    }


@router.get("/telegram/claim")
async def claim_telegram_link_endpoint(
    token: str = Query(..., min_length=6, max_length=128),
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user is None:
        login_url = "/auth/login?" + urlencode({"telegram_link": token})
        return RedirectResponse(login_url, status_code=status.HTTP_303_SEE_OTHER)
    try:
        await claim_telegram_link(db, token, user)
    except TelegramAuthError:
        return RedirectResponse("/auth/login?telegram_error=failed", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse("/chat?telegram=linked", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/telegram/status")
async def telegram_status(user: User = Depends(get_current_user)):
    return {
        "linked": bool(user.telegram_user_id),
        "telegram_user_id": user.telegram_user_id,
    }


@router.delete("/telegram/link", status_code=status.HTTP_204_NO_CONTENT)
async def remove_telegram_link(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await unlink_telegram(db, user)


@router.get("/telegram/login")
async def telegram_login(request: Request):
    """Start Telegram's OIDC Authorization Code + PKCE flow."""
    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(48)
    nonce = secrets.token_urlsafe(32)
    try:
        authorization_url = build_telegram_authorization_url(request, state, verifier, nonce)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    response = RedirectResponse(authorization_url, status_code=status.HTTP_303_SEE_OTHER)
    options = oauth_cookie_options()
    response.set_cookie("quip_telegram_oauth_state", state, max_age=telegram_oauth_ttl(), **options)
    response.set_cookie("quip_telegram_oauth_verifier", verifier, max_age=telegram_oauth_ttl(), **options)
    response.set_cookie("quip_telegram_oauth_nonce", nonce, max_age=telegram_oauth_ttl(), **options)
    return response


@router.get("/telegram/callback")
async def telegram_login_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    redirect = RedirectResponse("/auth/login?telegram_error=failed", status_code=status.HTTP_303_SEE_OTHER)
    cookie_options = oauth_cookie_options()
    redirect.delete_cookie("quip_telegram_oauth_state", path=cookie_options["path"])
    redirect.delete_cookie("quip_telegram_oauth_verifier", path=cookie_options["path"])
    redirect.delete_cookie("quip_telegram_oauth_nonce", path=cookie_options["path"])

    expected_state = request.cookies.get("quip_telegram_oauth_state")
    verifier = request.cookies.get("quip_telegram_oauth_verifier")
    nonce = request.cookies.get("quip_telegram_oauth_nonce")
    if not code or not state or not expected_state or not verifier or not nonce or not secrets.compare_digest(state, expected_state):
        return redirect

    bot_token = telegram_bot_token()
    try:
        token_response = await exchange_telegram_code(
            code,
            telegram_redirect_uri(request),
            bot_token,
            verifier,
        )
        claims = await verify_telegram_id_token(token_response["id_token"], bot_token, nonce)
    except TelegramAuthError as exc:
        redirect.headers["location"] = telegram_oauth_error_redirect(str(exc))
        return redirect

    telegram_user_id = str(claims["sub"])
    result = await db.execute(select(User).where(User.telegram_user_id == telegram_user_id))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.role == "pending":
        redirect.headers["location"] = "/auth/login?telegram_error=not_linked"
        return redirect

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )
    set_session_cookies(redirect, tokens.access_token, tokens.refresh_token)
    redirect.headers["location"] = "/chat"
    return redirect


@router.post("/refresh")
async def refresh(
    data: RefreshRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    explicit_token = data.refresh_token
    refresh_token = explicit_token or request.cookies.get("quip_refresh")
    payload = decode_token(refresh_token) if refresh_token else None
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    result = await db.execute(select(User).where(User.id == UUID(payload["sub"])))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.role == "pending":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval")

    tokens = TokenResponse(
        access_token=create_access_token(str(user.id), user.role),
        refresh_token=create_refresh_token(str(user.id)),
    )
    set_session_cookies(response, tokens.access_token, tokens.refresh_token)
    # A browser using HttpOnly cookies must not be able to turn them back into
    # JavaScript-readable bearer tokens. Explicit token clients retain the
    # existing token-rotation response for API compatibility.
    if explicit_token is None:
        return {"status": "ok"}
    return tokens


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response):
    clear_session_cookies(response)


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


@router.get("/settings")
async def get_user_settings(user: User = Depends(get_current_user)):
    return user.settings or {}


@router.patch("/settings")
async def update_user_settings(
    data: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    current = user.settings or {}
    # Only allow known keys
    allowed = {"name", "default_model", "locale"}
    for key, value in data.items():
        if key in allowed:
            current[key] = value
    user.settings = current
    flag_modified(user, "settings")

    # Also update display name if provided
    if "name" in data and data["name"]:
        user.name = data["name"]

    await db.commit()
    return {"status": "ok"}
