"""Admin CRUD for skills + public templates endpoint + AI draft generator."""
import hashlib
import json
import re

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db
from quip.models.user import User
from quip.services.config import get_setting
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
    settings_schema: list[dict] | None = None
    settings: dict | None = None


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
    settings_schema: list[dict] | None = None
    settings: dict | None = None


def _serialize(s) -> dict:
    return {
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
        "settings_schema": s.settings_schema,
        "settings": s.settings,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


# Public endpoint — returns widget templates for frontend cache (any authenticated user).
# ETag short-circuits the 304 path: clients re-validate cheaply when nothing changed.
@router.get("/templates")
async def list_templates(request: Request, user: User = Depends(get_current_user)):
    payload = get_widget_skills()
    body = json.dumps(payload, sort_keys=True).encode()
    etag = '"' + hashlib.md5(body).hexdigest() + '"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "no-cache"})
    return Response(
        content=body,
        media_type="application/json",
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


# Admin CRUD
@router.get("", dependencies=[Depends(get_admin_user)])
async def list_skills(db: AsyncSession = Depends(get_db)):
    skills = await get_all_skills(db)
    return [_serialize(s) for s in skills]


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


# --- AI-assisted skill draft generation ---

_GENERATOR_PROMPT = """You design new skills for an AI chat platform called QUIP.

A skill is one of:
  - "widget": a rich HTML card rendered in chat from a Mustache template + data.
  - "tool": a prompt-only instruction set for the agent.
  - "artifact": a markup/syntax the agent emits to render something structured.

Given the user's description, produce a STRICT JSON object with these fields (and nothing else — no prose, no code fences):
{
  "id": "snake_case_slug",
  "name": "Human Name",
  "description": "one line shown in skill index",
  "category": "widget" | "tool" | "artifact",
  "type": "content" | "api",
  "prompt_instructions": "full instructions the agent sees when it calls load_skill",
  "data_schema": { ... } or null,
  "template_html": "<div class='widget-myname'> ... </div>" or null,
  "template_css": ".widget-card .widget-myname { ... }" or null,
  "api_config": { ... } or null,
  "settings_schema": [{"key":"...","label":"...","type":"text|number|boolean|select|password","default":"...","options":[...] (if select)}] or null
}

Rules:
- For widgets, template_html must use Mustache syntax ({{field}}, {{#list}}...{{/list}}).
- Scope all CSS to `.widget-card .widget-<id>` to avoid bleed.
- Use CSS variables --quip-text, --quip-text-dim, --quip-text-muted, --quip-border, --quip-link, --quip-hover with dark fallbacks.
- For tools, template_html and template_css must be null.
- Keep data_schema concise — map field name to a short type hint.
- Include an "example" key inside data_schema with realistic sample data so the skill can be previewed.
"""


class GenerateRequest(BaseModel):
    prompt: str
    model: str | None = None


@router.post("/generate", dependencies=[Depends(get_admin_user)])
async def generate_skill(body: GenerateRequest):
    """Ask the LLM to draft a skill manifest from a natural-language description."""
    api_key = get_setting("openrouter_api_key", "")
    if not api_key:
        raise HTTPException(400, "OpenRouter API key not configured")
    model = body.model or get_setting("default_model", "") or "anthropic/claude-sonnet-4-5"

    timeout = httpx.Timeout(connect=15.0, read=300.0, write=30.0, pool=15.0)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/Janar0/quip",
                    "X-Title": "QUIP",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": _GENERATOR_PROMPT},
                        {"role": "user", "content": body.prompt},
                    ],
                    "response_format": {"type": "json_object"},
                },
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "LLM timed out. Try a faster model or shorter prompt.")
    except httpx.HTTPError as e:
        raise HTTPException(502, f"LLM network error: {e}")
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, f"LLM error: {resp.text[:500]}")
    try:
        payload = resp.json()
    except ValueError:
        raise HTTPException(502, f"Non-JSON LLM response: {resp.text[:500]}")
    content = (payload.get("choices") or [{}])[0].get("message", {}).get("content", "")
    # Strip fences if the model added them despite the instruction
    content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
    try:
        draft = json.loads(content)
    except json.JSONDecodeError as e:
        raise HTTPException(502, f"Could not parse LLM output as JSON: {e}. Raw: {content[:500]}")
    return {"draft": draft}
