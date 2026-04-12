"""Admin CRUD for skills + public templates endpoint."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.services.permissions import get_admin_user, get_current_user
from quip.services.skill_store import (
    get_all_skills, create_skill, update_skill, delete_skill, get_widget_skills,
)

router = APIRouter(prefix="/api/skills", tags=["skills"])


class SkillCreate(BaseModel):
    id: str
    name: str
    description: str
    category: str = "widget"
    icon: str | None = None
    type: str = "content"
    enabled: bool = True
    prompt_instructions: str = ""
    data_schema: dict | None = None
    template_html: str | None = None
    template_css: str | None = None
    api_config: dict | None = None


class SkillUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    icon: str | None = None
    type: str | None = None
    enabled: bool | None = None
    prompt_instructions: str | None = None
    data_schema: dict | None = None
    template_html: str | None = None
    template_css: str | None = None
    api_config: dict | None = None


# Public endpoint — returns widget templates for frontend cache (any authenticated user)
@router.get("/templates")
async def list_templates(user: User = Depends(get_current_user)):
    return get_widget_skills()


# Admin CRUD
@router.get("", dependencies=[Depends(get_admin_user)])
async def list_skills(db: AsyncSession = Depends(get_db)):
    skills = await get_all_skills(db)
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "category": s.category,
            "icon": s.icon,
            "type": s.type,
            "enabled": s.enabled,
            "is_builtin": s.is_builtin,
            "is_internal": s.is_internal,
            "prompt_instructions": s.prompt_instructions,
            "data_schema": s.data_schema,
            "template_html": s.template_html,
            "template_css": s.template_css,
            "api_config": s.api_config,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in skills
    ]


@router.post("", dependencies=[Depends(get_admin_user)])
async def create(body: SkillCreate, db: AsyncSession = Depends(get_db)):
    skill = await create_skill(db, body.model_dump())
    return {"id": skill.id}


@router.put("/{skill_id}", dependencies=[Depends(get_admin_user)])
async def update(skill_id: str, body: SkillUpdate, db: AsyncSession = Depends(get_db)):
    data = body.model_dump(exclude_unset=True)
    skill = await update_skill(db, skill_id, data)
    if not skill:
        raise HTTPException(404, "Skill not found")
    return {"ok": True}


@router.delete("/{skill_id}", dependencies=[Depends(get_admin_user)])
async def delete(skill_id: str, db: AsyncSession = Depends(get_db)):
    ok = await delete_skill(db, skill_id)
    if not ok:
        raise HTTPException(404, "Skill not found")
    return {"ok": True}
