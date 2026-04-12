import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
import os

from quip.database import engine, Base
from quip.services.config import load_settings
from quip.services.openwebui_migration import run_migration_if_needed
from quip.routers.auth import router as auth_router
from quip.routers.chats import router as chats_router
from quip.routers.completion import router as completion_router
from quip.routers.models import router as models_router
from quip.routers.admin import router as admin_router
from quip.routers.migrate import router as migrate_router
from quip.routers.skills import router as skills_router
from quip.routers.sandbox import router as sandbox_router
from quip.routers.files import router as files_router
from quip.routers.images import router as images_router
from quip.services.sandbox import sandbox_cleanup_loop
import quip.models  # noqa: F401 — register all models with Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Ensure performance indexes exist on existing databases (separate transaction)
    async with engine.begin() as conn:
        for stmt in [
            "CREATE INDEX IF NOT EXISTS ix_usage_log_created ON usage_log(created_at)",
            "CREATE INDEX IF NOT EXISTS ix_usage_log_user_created ON usage_log(user_id, created_at)",
        ]:
            try:
                await conn.execute(text(stmt))
            except Exception:
                pass  # Index may already exist with this name
    await run_migration_if_needed()
    await load_settings()
    from quip.services.skill_store import seed_builtin_skills
    from quip.database import async_session
    async with async_session() as db:
        await seed_builtin_skills(db)
    cleanup_task = asyncio.create_task(sandbox_cleanup_loop())
    yield
    cleanup_task.cancel()
    await engine.dispose()


app = FastAPI(
    title="Q.U.I.P.",
    description="Agent-first multi-provider AI chat platform",
    version="0.1.0",
    lifespan=lifespan,
)

cors_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(completion_router)
app.include_router(models_router)
app.include_router(admin_router)
app.include_router(migrate_router)
app.include_router(skills_router)
app.include_router(sandbox_router)
app.include_router(files_router)
app.include_router(images_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
