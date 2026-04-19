"""Admin endpoints — settings, user management, models, usage."""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.chat import Chat
from quip.models.usage import UsageLog
from quip.models.budget import Budget
from quip.models.user import User, Auth
from quip.services.permissions import get_admin_user
from quip.services.config import get_setting, set_setting, save_settings, get_bool_setting
from quip.services.auth import hash_password
from quip.providers.openrouter import list_models as or_list_models, get_key_info

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Settings ---

class SettingsUpdate(BaseModel):
    openrouter_api_key: str | None = None
    ollama_url: str | None = None
    system_prompt: str | None = None
    model_whitelist: list[str] | None = None
    rag_enabled: bool | None = None
    search_enabled: bool | None = None
    research_enabled: bool | None = None
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


class SettingsResponse(BaseModel):
    openrouter_api_key_set: bool
    openrouter_key_info: dict | None = None
    ollama_url: str = "http://localhost:11434"
    system_prompt: str = ""
    model_whitelist: list[str] = []
    rag_enabled: bool = True
    search_enabled: bool = False
    research_enabled: bool = True
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
        research_enabled=get_bool_setting("research_enabled", True),
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
    )


_JSON_SETTING_FIELDS = {"model_whitelist", "model_aliases"}
_BOOL_SETTING_FIELDS = {"rag_enabled", "search_enabled", "research_enabled"}


@router.put("/settings")
async def update_settings(data: SettingsUpdate, user: User = Depends(get_admin_user)):
    for key, val in data.model_dump(exclude_none=True).items():
        if key in _JSON_SETTING_FIELDS:
            set_setting(key, json.dumps(val))
        elif key in _BOOL_SETTING_FIELDS:
            set_setting(key, "true" if val else "false")
        else:
            set_setting(key, str(val) if not isinstance(val, str) else val)
    await save_settings()
    return {"status": "ok"}


# --- Models ---

@router.get("/models")
async def get_models(user: User = Depends(get_admin_user)):
    key = get_setting("openrouter_api_key")
    if not key:
        return {"models": [], "error": "No API key configured"}
    models = await or_list_models(key)
    return {"models": models}


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
    items = []
    for b in budgets:
        user_name = None
        if b.user_id:
            u = await db.execute(select(User.name).where(User.id == b.user_id))
            user_name = u.scalar_one_or_none()
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
