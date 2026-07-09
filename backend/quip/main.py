import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

import quip.models  # noqa: F401 — register all models with Base
from quip.core.config import load_settings
from quip.database import DATABASE_URL, engine
from quip.migrations.runner import SCHEMA_REVISION, upgrade_schema
from quip.routers.admin import router as admin_router
from quip.routers.audio import router as audio_router
from quip.routers.auth import router as auth_router
from quip.routers.chats import router as chats_router
from quip.routers.completion import router as completion_router
from quip.routers.files import router as files_router
from quip.routers.icons import router as icons_router
from quip.routers.images import router as images_router
from quip.routers.migrate import router as migrate_router
from quip.routers.models import router as models_router
from quip.routers.sandbox import router as sandbox_router
from quip.routers.skills import router as skills_router
from quip.routers.workspaces import router as workspaces_router
from quip.services.openwebui_migration import run_migration_if_needed
from quip.services.sandbox import sandbox_cleanup_loop, sandbox_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("AUTO_MIGRATE", "true").strip().lower() in {"1", "true", "yes", "on"}:
        await asyncio.to_thread(upgrade_schema, DATABASE_URL)
    await run_migration_if_needed()
    await load_settings()
    from quip.database import async_session
    from quip.services.skill_store import seed_builtin_skills
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

app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag"],
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
app.include_router(audio_router)
app.include_router(icons_router)
app.include_router(workspaces_router)


@app.get("/health/live")
async def liveness():
    return {"status": "ok"}


@app.get("/health/ready")
@app.get("/health")
async def readiness():
    executor_required = bool(sandbox_manager.executor_url)
    components = {
        "database": "error",
        "schema": "unknown",
        "storage": "error",
        "executor": "error" if executor_required else "optional",
    }
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            components["database"] = "ok"
            revision = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one_or_none()
            components["schema"] = "ok" if revision == SCHEMA_REVISION else f"expected-{SCHEMA_REVISION}"
    except Exception:
        components["database"] = "error"

    data_dir = Path(__file__).resolve().parent.parent / "data"
    if data_dir.is_dir() and os.access(data_dir, os.W_OK):
        components["storage"] = "ok"

    if executor_required:
        components["executor"] = "ok" if await sandbox_manager.healthcheck() else "error"

    required_components = ["database", "schema", "storage"]
    if executor_required:
        required_components.append("executor")
    ready = all(components[name] == "ok" for name in required_components)
    payload = {"status": "ready" if ready else "not_ready", "components": components}
    return JSONResponse(payload, status_code=200 if ready else 503)
