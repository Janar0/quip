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
from quip.services.config import get_setting, set_setting, save_settings
from quip.services.auth import hash_password
from quip.providers.openrouter import list_models as or_list_models, get_key_info

router = APIRouter(prefix="/api/admin", tags=["admin"])


# --- Settings ---

class SettingsUpdate(BaseModel):
    openrouter_api_key: str | None = None
    ollama_url: str | None = None
    system_prompt: str | None = None
    gismeteo_api_key: str | None = None
    model_whitelist: list[str] | None = None
    artifacts_enabled: bool | None = None
    sandbox_enabled: bool | None = None
    sandbox_memory_limit: str | None = None
    sandbox_cpu_limit: str | None = None
    sandbox_idle_timeout: int | None = None
    sandbox_exec_timeout: int | None = None
    rag_enabled: bool | None = None
    search_enabled: bool | None = None
    research_enabled: bool | None = None
    search_provider: str | None = None
    tavily_api_key: str | None = None
    searxng_url: str | None = None
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
    gismeteo_api_key_set: bool = False
    model_whitelist: list[str] = []
    artifacts_enabled: bool = True
    sandbox_enabled: bool = False
    sandbox_memory_limit: str = "512m"
    sandbox_cpu_limit: str = "1.0"
    sandbox_idle_timeout: int = 600
    sandbox_exec_timeout: int = 30
    rag_enabled: bool = True
    search_enabled: bool = False
    research_enabled: bool = True
    search_provider: str = "tavily"
    tavily_api_key_set: bool = False
    searxng_url: str = ""
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
        gismeteo_api_key_set=bool(get_setting("gismeteo_api_key")),
        model_whitelist=whitelist,
        artifacts_enabled=get_setting("artifacts_enabled", "true") == "true",
        sandbox_enabled=get_setting("sandbox_enabled", "false") == "true",
        sandbox_memory_limit=get_setting("sandbox_memory_limit", "512m"),
        sandbox_cpu_limit=get_setting("sandbox_cpu_limit", "1.0"),
        sandbox_idle_timeout=int(get_setting("sandbox_idle_timeout", "600")),
        sandbox_exec_timeout=int(get_setting("sandbox_exec_timeout", "30")),
        rag_enabled=get_setting("rag_enabled", "true") == "true",
        search_enabled=get_setting("search_enabled", "false") == "true",
        research_enabled=get_setting("research_enabled", "true") == "true",
        search_provider=get_setting("search_provider", "tavily"),
        tavily_api_key_set=bool(get_setting("tavily_api_key")),
        searxng_url=get_setting("searxng_url", ""),
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


@router.put("/settings")
async def update_settings(data: SettingsUpdate, user: User = Depends(get_admin_user)):
    if data.openrouter_api_key is not None:
        set_setting("openrouter_api_key", data.openrouter_api_key)
    if data.ollama_url is not None:
        set_setting("ollama_url", data.ollama_url)
    if data.system_prompt is not None:
        set_setting("system_prompt", data.system_prompt)
    if data.gismeteo_api_key is not None:
        set_setting("gismeteo_api_key", data.gismeteo_api_key)
    if data.model_whitelist is not None:
        set_setting("model_whitelist", json.dumps(data.model_whitelist))
    if data.artifacts_enabled is not None:
        set_setting("artifacts_enabled", "true" if data.artifacts_enabled else "false")
    if data.sandbox_enabled is not None:
        set_setting("sandbox_enabled", "true" if data.sandbox_enabled else "false")
    if data.sandbox_memory_limit is not None:
        set_setting("sandbox_memory_limit", data.sandbox_memory_limit)
    if data.sandbox_cpu_limit is not None:
        set_setting("sandbox_cpu_limit", data.sandbox_cpu_limit)
    if data.sandbox_idle_timeout is not None:
        set_setting("sandbox_idle_timeout", str(data.sandbox_idle_timeout))
    if data.sandbox_exec_timeout is not None:
        set_setting("sandbox_exec_timeout", str(data.sandbox_exec_timeout))
    if data.rag_enabled is not None:
        set_setting("rag_enabled", "true" if data.rag_enabled else "false")
    if data.search_enabled is not None:
        set_setting("search_enabled", "true" if data.search_enabled else "false")
    if data.research_enabled is not None:
        set_setting("research_enabled", "true" if data.research_enabled else "false")
    if data.search_provider is not None:
        set_setting("search_provider", data.search_provider)
    if data.tavily_api_key is not None:
        set_setting("tavily_api_key", data.tavily_api_key)
    if data.searxng_url is not None:
        set_setting("searxng_url", data.searxng_url)
    if data.embedding_provider is not None:
        set_setting("embedding_provider", data.embedding_provider)
    if data.embedding_model is not None:
        set_setting("embedding_model", data.embedding_model)
    if data.rag_chunk_size is not None:
        set_setting("rag_chunk_size", str(data.rag_chunk_size))
    if data.rag_chunk_overlap is not None:
        set_setting("rag_chunk_overlap", str(data.rag_chunk_overlap))
    if data.rag_top_k is not None:
        set_setting("rag_top_k", str(data.rag_top_k))
    if data.model_aliases is not None:
        set_setting("model_aliases", json.dumps(data.model_aliases))
    if data.search_model is not None:
        set_setting("search_model", data.search_model)
    if data.research_model is not None:
        set_setting("research_model", data.research_model)
    if data.title_model is not None:
        set_setting("title_model", data.title_model)
    if data.default_model is not None:
        set_setting("default_model", data.default_model)
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
