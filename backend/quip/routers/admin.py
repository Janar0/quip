"""Admin endpoints — settings, user management, models, usage."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from quip.database import get_db
from quip.models.chat import Chat
from quip.models.config import Config
from quip.models.workspace import Workspace
from quip.models.usage import UsageLog
from quip.models.budget import Budget
from quip.models.user import User, Auth
from quip.services.permissions import get_admin_user
from quip.core.config import get_setting, set_setting, save_settings, get_bool_setting, get_all_settings
from quip.services.auth import hash_password
from quip.providers.openrouter import list_models as or_list_models, get_key_info
from quip.routers.models import get_cached_models, invalidate_openrouter_models_cache
from quip.services import model_updater

router = APIRouter(prefix="/api/admin", tags=["admin"])
_model_update_in_progress = False
_model_settings_lock = asyncio.Lock()


def _single_model_update(handler):
    """Reject duplicate in-process mapping calls before they reach the provider."""

    @wraps(handler)
    async def wrapped(*args, **kwargs):
        global _model_update_in_progress
        if _model_update_in_progress:
            raise HTTPException(status_code=409, detail="A model update is already in progress.")
        _model_update_in_progress = True
        try:
            return await handler(*args, **kwargs)
        finally:
            _model_update_in_progress = False

    return wrapped


# --- Settings ---

class SettingsUpdate(BaseModel):
    openrouter_api_key: str | None = None
    ollama_url: str | None = None
    system_prompt: str | None = None
    model_whitelist: list[str] | None = None
    rag_enabled: bool | None = None
    search_enabled: bool | None = None
    research_enabled: bool | None = None
    tool_gating_enabled: bool | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    rag_chunk_size: int | None = None
    rag_chunk_overlap: int | None = None
    rag_top_k: int | None = None
    model_aliases: dict[str, str] | None = None
    search_model: str | None = None
    research_model: str | None = None
    title_model: str | None = None
    default_model: str | None = None
    mistral_api_key: str | None = None
    ocr_provider: str | None = None
    ocr_tesseract_langs: str | None = None
    archive_max_mb: int | None = None
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: str | None = None
    telegram_model: str | None = None
    telegram_login_redirect_uri: str | None = None
    public_app_url: str | None = None
    qwen_voice_enabled: bool | None = None
    qwen_realtime_endpoint: str | None = None
    qwen_realtime_api_key: str | None = None
    qwen_realtime_model: str | None = None
    qwen_realtime_video_enabled: bool | None = None
    voice_delegation_model_id: str | None = None


class SettingsResponse(BaseModel):
    openrouter_api_key_set: bool
    openrouter_key_info: dict | None = None
    ollama_url: str = "http://localhost:11434"
    system_prompt: str = ""
    model_whitelist: list[str] = []
    rag_enabled: bool = True
    search_enabled: bool = False
    research_enabled: bool = False
    embedding_provider: str = "openrouter"
    embedding_model: str = "openai/text-embedding-3-small"
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64
    rag_top_k: int = 5
    model_aliases: dict[str, str] = {}
    search_model: Optional[str] = None
    research_model: Optional[str] = None
    title_model: Optional[str] = None
    default_model: Optional[str] = None
    mistral_api_key_set: bool = False
    ocr_provider: str = "auto"
    ocr_tesseract_langs: str = "eng+rus"
    archive_max_mb: int = 150
    tool_gating_enabled: bool = True
    telegram_bot_token_set: bool = False
    telegram_allowed_user_ids: str = ""
    telegram_model: Optional[str] = None
    telegram_login_redirect_uri: Optional[str] = None
    public_app_url: Optional[str] = None
    qwen_voice_enabled: bool = False
    qwen_realtime_endpoint: str = "https://maas.qwencloudapi.com/api/v1/webrtc/realtime"
    qwen_realtime_api_key_set: bool = False
    qwen_realtime_model: str = "qwen-audio-3.1-realtime-plus"
    qwen_realtime_video_enabled: bool = False
    voice_delegation_model_id: str = ""


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(user: User = Depends(get_admin_user)):
    key = get_setting("openrouter_api_key")
    key_info = None
    if key:
        key_info = await get_key_info(key)
    whitelist_raw = get_setting("model_whitelist", "")
    whitelist = json.loads(whitelist_raw) if whitelist_raw else []
    return SettingsResponse(
        openrouter_api_key_set=bool(key),
        openrouter_key_info=key_info,
        ollama_url=get_setting("ollama_url", "http://localhost:11434"),
        system_prompt=get_setting("system_prompt"),
        model_whitelist=whitelist,
        rag_enabled=get_bool_setting("rag_enabled", True),
        search_enabled=get_bool_setting("search_enabled", False),
        research_enabled=get_bool_setting("research_enabled", False),
        embedding_provider=get_setting("embedding_provider", "openrouter"),
        embedding_model=get_setting("embedding_model", "openai/text-embedding-3-small"),
        rag_chunk_size=int(get_setting("rag_chunk_size", "512")),
        rag_chunk_overlap=int(get_setting("rag_chunk_overlap", "64")),
        rag_top_k=int(get_setting("rag_top_k", "5")),
        model_aliases=json.loads(get_setting("model_aliases", "{}")),
        search_model=get_setting("search_model") or None,
        research_model=get_setting("research_model") or None,
        title_model=get_setting("title_model") or None,
        default_model=get_setting("default_model") or None,
        mistral_api_key_set=bool(get_setting("mistral_api_key")),
        ocr_provider=get_setting("ocr_provider", "auto"),
        ocr_tesseract_langs=get_setting("ocr_tesseract_langs", "eng+rus"),
        archive_max_mb=int(get_setting("archive_max_mb", "150")),
        tool_gating_enabled=get_bool_setting("tool_gating_enabled", True),
        telegram_bot_token_set=bool(get_setting("telegram_bot_token")),
        telegram_allowed_user_ids=get_setting("telegram_allowed_user_ids", ""),
        telegram_model=get_setting("telegram_model") or None,
        telegram_login_redirect_uri=get_setting("telegram_login_redirect_uri") or None,
        public_app_url=get_setting("public_app_url") or None,
        qwen_voice_enabled=get_bool_setting("qwen_voice_enabled", False),
        qwen_realtime_endpoint=get_setting(
            "qwen_realtime_endpoint", "https://maas.qwencloudapi.com/api/v1/webrtc/realtime"
        ),
        qwen_realtime_api_key_set=bool(get_setting("qwen_realtime_api_key")),
        qwen_realtime_model=get_setting("qwen_realtime_model", "qwen-audio-3.1-realtime-plus"),
        qwen_realtime_video_enabled=get_bool_setting("qwen_realtime_video_enabled", False),
        voice_delegation_model_id=get_setting("voice_delegation_model_id"),
    )


_JSON_SETTING_FIELDS = {"model_whitelist", "model_aliases"}
_BOOL_SETTING_FIELDS = {
    "rag_enabled", "search_enabled", "research_enabled", "tool_gating_enabled",
    "qwen_voice_enabled", "qwen_realtime_video_enabled",
}


@router.put("/settings")
async def update_settings(
    data: SettingsUpdate,
    request: Request,
    user: User = Depends(get_admin_user),
):
    async with _model_settings_lock:
        for key, val in data.model_dump(exclude_none=True).items():
            if key in _JSON_SETTING_FIELDS:
                set_setting(key, json.dumps(val))
            elif key in _BOOL_SETTING_FIELDS:
                set_setting(key, "true" if val else "false")
            else:
                set_setting(key, str(val) if not isinstance(val, str) else val)
        await save_settings()
    if any(key.startswith("telegram_") for key in data.model_dump(exclude_none=True)):
        telegram_bot = getattr(request.app.state, "telegram_bot", None)
        if telegram_bot is not None:
            await telegram_bot.reconfigure()
    return {"status": "ok"}


# --- Models ---

@router.get("/models")
async def get_models(user: User = Depends(get_admin_user)):
    key = get_setting("openrouter_api_key")
    if not key:
        return {"models": [], "error": "No API key configured"}
    models = await or_list_models(key)
    return {"models": models}


@router.post("/models/update")
@_single_model_update
async def update_models(
    request: Request,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    """Refresh selected model IDs when a verified same-family successor exists."""
    api_key = get_setting("openrouter_api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="OpenRouter API key is not configured.")

    try:
        raw_whitelist = get_setting("model_whitelist", "")
        whitelist = json.loads(raw_whitelist) if raw_whitelist else []
    except json.JSONDecodeError:
        raise HTTPException(status_code=409, detail="The model allowlist is invalid JSON.")
    if not isinstance(whitelist, list) or any(not isinstance(item, str) for item in whitelist):
        raise HTTPException(status_code=409, detail="The model allowlist has an invalid format.")

    raw_aliases = get_setting("model_aliases", "")
    cached_before_refresh = {item["id"]: item for item in get_cached_models() if item.get("id")}
    catalog = await or_list_models(api_key)
    if not isinstance(catalog, list) or not catalog:
        raise HTTPException(status_code=502, detail="The provider returned no model catalog; nothing was changed.")
    catalog = [item for item in catalog if isinstance(item, dict) and isinstance(item.get("id"), str)]
    if not catalog:
        raise HTTPException(status_code=502, detail="The provider returned an invalid model catalog; nothing was changed.")
    invalidate_openrouter_models_cache()
    fresh_by_id = {item["id"]: item for item in catalog}
    fresh_models = [{"id": item["id"], "name": str(item.get("name") or item["id"])} for item in catalog]

    config_result = await db.execute(select(Config).where(Config.id == 1))
    initial_config = config_result.scalar_one_or_none()
    initial_config_version = initial_config.version if initial_config else None
    initial_config_data = (
        json.dumps(initial_config.data, sort_keys=True, separators=(",", ":"))
        if initial_config
        else None
    )
    users = list((await db.execute(select(User))).scalars().all())
    workspaces = list((await db.execute(select(Workspace))).scalars().all())
    user_default_snapshot = {
        target_user.id: (target_user.settings.get("default_model") if isinstance(target_user.settings, dict) else None)
        for target_user in users
    }
    workspace_default_snapshot = {
        workspace.id: workspace.default_model for workspace in workspaces
    }
    setting_refs = {
        key: get_setting(key) or ""
        for key in ("default_model", "search_model", "research_model", "title_model", "telegram_model")
    }
    reference_names: dict[str, set[str]] = {}

    def record_reference(model_id: str | None, label: str) -> None:
        if model_id:
            reference_names.setdefault(model_id, set()).add(label)

    for model_id in whitelist:
        record_reference(model_id, "model_whitelist")
    for key, model_id in setting_refs.items():
        record_reference(model_id, key)
    for model_id in workspace_default_snapshot.values():
        record_reference(model_id, "workspace_defaults")
    for user_default in user_default_snapshot.values():
        record_reference(user_default, "user_defaults")

    # Do not keep a read transaction open while making a remote mapping call.
    await db.rollback()

    source_ids = list(reference_names)
    if not source_ids:
        return {
            "updated": [],
            "skipped": [{"model_id": None, "reason": "no_configured_models"}],
            "mapper_model": None,
            "settings": {
                "model_whitelist": whitelist,
                "model_aliases": _read_json_setting("model_aliases", {}),
                **setting_refs,
            },
            "models": fresh_models,
        }

    candidate_pools, candidate_skips = model_updater.find_successor_candidates(source_ids, catalog)
    already_skipped = {item["model_id"] for item in candidate_skips}
    mappable = {
        source_id: candidates
        for source_id, candidates in candidate_pools.items()
        if source_id not in already_skipped
    }
    suggestions: dict[str, str] = {}
    duplicate_suggestions: set[str] = set()
    mapper_model = None
    if mappable:
        for configured in (setting_refs["title_model"], setting_refs["default_model"]):
            if configured and not configured.startswith("ollama/") and configured in fresh_by_id:
                mapper_model = configured
                break
        if mapper_model is None:
            for model_id in source_ids:
                if model_id in fresh_by_id and not model_id.startswith("ollama/"):
                    mapper_model = model_id
                    break
        if mapper_model is None:
            for candidates in mappable.values():
                mapper_model = next((item["id"] for item in candidates if item["id"] in fresh_by_id), None)
                if mapper_model:
                    break
        if mapper_model is None:
            raise HTTPException(status_code=409, detail="No available OpenRouter model can map these successors.")
        try:
            suggestions, duplicate_suggestions = await model_updater.request_successor_mappings(
                mapper_model, mappable, api_key
            )
        except model_updater.ModelMappingError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    duplicate_suggestions.intersection_update(source_ids)
    suggestions = {source_id: target_id for source_id, target_id in suggestions.items() if source_id in source_ids}
    for model_id in duplicate_suggestions:
        suggestions.pop(model_id, None)
    resolution = model_updater.resolve_successor_mappings(source_ids, catalog, suggestions)
    skipped = [item for item in resolution["skipped"] if item["model_id"] not in duplicate_suggestions]
    skipped.extend({"model_id": model_id, "reason": "duplicate_suggestion"} for model_id in duplicate_suggestions)
    replacements = resolution["replacements"]

    settings_input: dict[str, object] = {
        "model_whitelist": whitelist,
        "model_aliases": _read_json_setting("model_aliases", {}),
        **setting_refs,
    }
    updated_settings, changed_keys = model_updater.apply_model_replacements(settings_input, replacements)
    if replacements:
        async with _model_settings_lock:
            settings_changed = (
                get_setting("model_whitelist", "") != raw_whitelist
                or get_setting("model_aliases", "") != raw_aliases
                or any((get_setting(key) or "") != value for key, value in setting_refs.items())
            )
            if settings_changed:
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Model settings changed during the update. Review the current selections and retry.",
                )

            # Serialize SQLite writers before re-reading the snapshot so a settings
            # request cannot slip between validation and commit. Row locks cover
            # existing records on databases that implement SELECT FOR UPDATE.
            if db.get_bind().dialect.name == "sqlite":
                await db.execute(text("BEGIN IMMEDIATE"))
            config = (
                await db.execute(
                    select(Config).where(Config.id == 1).with_for_update()
                )
            ).scalar_one_or_none()
            current_config_version = config.version if config else None
            current_config_data = (
                json.dumps(config.data, sort_keys=True, separators=(",", ":"))
                if config
                else None
            )
            current_users = list(
                (
                    await db.execute(
                        select(User)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalars().all()
            )
            current_workspaces = list(
                (
                    await db.execute(
                        select(Workspace)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).scalars().all()
            )
            current_user_defaults = {
                target_user.id: (
                    target_user.settings.get("default_model")
                    if isinstance(target_user.settings, dict)
                    else None
                )
                for target_user in current_users
            }
            current_workspace_defaults = {
                workspace.id: workspace.default_model for workspace in current_workspaces
            }
            if (
                current_config_version != initial_config_version
                or current_config_data != initial_config_data
                or current_user_defaults != user_default_snapshot
                or current_workspace_defaults != workspace_default_snapshot
            ):
                await db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail="Model selections changed during the update. Review the current selections and retry.",
                )

            persisted = dict(config.data) if config and isinstance(config.data, dict) else {}
            persisted.update(get_all_settings())
            for key in changed_keys:
                value = updated_settings[key]
                persisted[key] = json.dumps(value) if key in {"model_whitelist", "model_aliases"} else str(value)
            if config:
                config.data = persisted
                flag_modified(config, "data")
                config.version = (config.version or 0) + 1
            else:
                db.add(Config(id=1, data=persisted, version=1))

            for workspace in current_workspaces:
                if workspace.default_model in replacements:
                    workspace.default_model = replacements[workspace.default_model]
            for target_user in current_users:
                user_settings = target_user.settings if isinstance(target_user.settings, dict) else {}
                user_default = user_settings.get("default_model")
                if user_default in replacements:
                    target_user.settings = {**user_settings, "default_model": replacements[user_default]}
                    flag_modified(target_user, "settings")
            try:
                await db.commit()
            except Exception:
                await db.rollback()
                raise

            for key in changed_keys:
                persisted_value = persisted[key]
                set_setting(key, persisted_value)

    updated = []
    for old_id, new_id in replacements.items():
        old_model = fresh_by_id.get(old_id) or cached_before_refresh.get(old_id)
        new_model = fresh_by_id[new_id]
        updated.append(
            {
                "old_id": old_id,
                "new_id": new_id,
                "references": sorted(reference_names.get(old_id, ())),
                "price_change": model_updater.compare_prices(old_model, new_model),
            }
        )

    if "telegram_model" in changed_keys:
        telegram_bot = getattr(request.app.state, "telegram_bot", None)
        if telegram_bot is not None:
            await telegram_bot.reconfigure()

    return {
        "updated": updated,
        "skipped": skipped,
        "mapper_model": mapper_model,
        "settings": {
            "model_whitelist": updated_settings.get("model_whitelist", whitelist),
            "model_aliases": updated_settings.get("model_aliases", settings_input["model_aliases"]),
            **{key: updated_settings.get(key, value) for key, value in setting_refs.items()},
        },
        "models": fresh_models,
    }


def _read_json_setting(key: str, default):
    raw = get_setting(key, "")
    if not raw:
        return default
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return default
    return value if isinstance(value, type(default)) else default


# --- Users ---

class UserListItem(BaseModel):
    id: str
    email: str
    username: str
    name: str
    role: str
    is_active: bool
    last_active_at: Optional[datetime] = None


@router.get("/users", response_model=list[UserListItem])
async def list_users(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).order_by(User.created_at))
    users = result.scalars().all()
    return [
        UserListItem(
            id=str(u.id), email=u.email, username=u.username,
            name=u.name, role=u.role, is_active=u.is_active,
            last_active_at=u.last_active_at,
        )
        for u in users
    ]


class RoleUpdate(BaseModel):
    role: str


@router.patch("/users/{user_id}/role")
async def update_user_role(
    user_id: str,
    data: RoleUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if data.role not in ("admin", "user", "pending"):
        raise HTTPException(status_code=400, detail="Invalid role")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.role = data.role
    await db.commit()
    return {"status": "ok"}


class StatusUpdate(BaseModel):
    is_active: bool


@router.patch("/users/{user_id}/status")
async def update_user_status(
    user_id: str,
    data: StatusUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if str(target.id) == str(admin.id):
        raise HTTPException(status_code=400, detail="Cannot disable yourself")
    target.is_active = data.is_active
    await db.commit()
    return {"status": "ok"}


class PasswordReset(BaseModel):
    password: str


@router.patch("/users/{user_id}/password")
async def reset_user_password(
    user_id: str,
    data: PasswordReset,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    result = await db.execute(select(Auth).where(Auth.id == UUID(user_id)))
    auth = result.scalar_one_or_none()
    new_hash = hash_password(data.password)
    if auth:
        auth.password_hash = new_hash
    else:
        db.add(Auth(id=UUID(user_id), password_hash=new_hash))
    await db.commit()
    return {"status": "ok"}


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    if str(admin.id) == user_id:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    result = await db.execute(select(User).where(User.id == UUID(user_id)))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.execute(delete(Chat).where(Chat.user_id == UUID(user_id)))
    await db.delete(target)
    await db.commit()


# --- Usage ---

@router.get("/usage")
async def get_usage(
    days: int = Query(default=30, ge=1, le=365),
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)

    # Total stats
    totals_q = await db.execute(
        select(
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost), 0).label("total_cost"),
            func.coalesce(func.sum(UsageLog.prompt_tokens), 0).label("prompt_tokens"),
            func.coalesce(func.sum(UsageLog.completion_tokens), 0).label("completion_tokens"),
            func.coalesce(func.sum(UsageLog.cached_tokens), 0).label("cached_tokens"),
        ).where(UsageLog.created_at >= since)
    )
    totals = totals_q.one()

    # By model
    by_model_q = await db.execute(
        select(
            UsageLog.model,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
            func.coalesce(func.sum(UsageLog.prompt_tokens + UsageLog.completion_tokens), 0).label("tokens"),
        )
        .where(UsageLog.created_at >= since)
        .group_by(UsageLog.model)
        .order_by(func.sum(UsageLog.cost).desc())
    )
    aliases_raw = get_setting("model_aliases", "")
    aliases: dict[str, str] = {}
    if aliases_raw:
        try:
            aliases = json.loads(aliases_raw)
        except json.JSONDecodeError:
            pass
    by_model = [
        {
            "model": r.model,
            "display_name": aliases.get(r.model, r.model),
            "requests": r.requests,
            "cost": float(r.cost),
            "tokens": r.tokens,
        }
        for r in by_model_q.all()
    ]

    # By user
    by_user_q = await db.execute(
        select(
            User.name,
            User.email,
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
        )
        .join(User, UsageLog.user_id == User.id)
        .where(UsageLog.created_at >= since)
        .group_by(User.id, User.name, User.email)
        .order_by(func.sum(UsageLog.cost).desc())
    )
    by_user = [
        {"name": r.name, "email": r.email, "requests": r.requests, "cost": float(r.cost)}
        for r in by_user_q.all()
    ]

    # By day (last N days) — use func.date() to get plain "YYYY-MM-DD" string;
    # avoid cast(..., Date) which triggers SQLAlchemy's fromisoformat processor
    # and fails when aiosqlite already returns a date object (Python 3.11+)
    by_day_q = await db.execute(
        select(
            func.date(UsageLog.created_at).label("day"),
            func.count(UsageLog.id).label("requests"),
            func.coalesce(func.sum(UsageLog.cost), 0).label("cost"),
        )
        .where(UsageLog.created_at >= since)
        .group_by(func.date(UsageLog.created_at))
        .order_by(func.date(UsageLog.created_at))
    )
    by_day = [
        {"day": str(r.day), "requests": r.requests, "cost": float(r.cost)}
        for r in by_day_q.all()
    ]

    return {
        "period_days": days,
        "totals": {
            "requests": totals.requests,
            "cost": float(totals.total_cost),
            "prompt_tokens": totals.prompt_tokens,
            "completion_tokens": totals.completion_tokens,
            "cached_tokens": totals.cached_tokens,
        },
        "by_model": by_model,
        "by_user": by_user,
        "by_day": by_day,
    }


# --- Budgets ---

class BudgetItem(BaseModel):
    id: str
    user_id: str | None
    user_name: str | None = None
    period: str
    limit_usd: float


class BudgetUpdate(BaseModel):
    user_id: str | None = None  # null = global
    period: str = "monthly"
    limit_usd: float


@router.get("/budgets", response_model=list[BudgetItem])
async def list_budgets(
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).order_by(Budget.user_id))
    budgets = result.scalars().all()

    # Batch-load user names to avoid N+1
    user_ids = [b.user_id for b in budgets if b.user_id]
    user_names: dict = {}
    if user_ids:
        u_result = await db.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
        user_names = {uid: name for uid, name in u_result.all()}

    items = []
    for b in budgets:
        user_name = user_names.get(b.user_id) if b.user_id else None
        items.append(BudgetItem(
            id=str(b.id), user_id=str(b.user_id) if b.user_id else None,
            user_name=user_name, period=b.period, limit_usd=float(b.limit_usd),
        ))
    return items


@router.put("/budgets")
async def upsert_budget(
    data: BudgetUpdate,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    uid = UUID(data.user_id) if data.user_id else None
    result = await db.execute(
        select(Budget).where(Budget.user_id == uid, Budget.period == data.period)
    )
    budget = result.scalar_one_or_none()
    if budget:
        budget.limit_usd = data.limit_usd
    else:
        budget = Budget(user_id=uid, period=data.period, limit_usd=data.limit_usd)
        db.add(budget)
    await db.commit()
    return {"status": "ok"}


@router.delete("/budgets/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: str,
    admin: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Budget).where(Budget.id == UUID(budget_id)))
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(404, "Budget not found")
    await db.delete(budget)
    await db.commit()
