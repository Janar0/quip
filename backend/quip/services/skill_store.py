"""Database-backed skill store with seeding from the pluggable skill registry.

Skills are defined under `quip/skills/{widgets,tools,artifacts}/<id>.py` — each
module exports a `SKILL` dict. `discover_skills()` walks the registry at startup.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from quip.models.skill import Skill
from quip.database import async_session
from quip.skills import discover_skills

# Cache loaded from DB at startup
_skills_cache: dict[str, Skill] = {}

# Fields the code owns — always refreshed from the manifest.
_CODE_FIELDS = {
    "prompt_instructions", "data_schema", "template_html", "template_css",
    "api_config", "is_builtin", "is_internal", "settings_schema",
}


async def load_skills():
    """Load all skills from DB into memory cache. Called at startup."""
    async with async_session() as db:
        result = await db.execute(select(Skill))
        skills = result.scalars().all()
        _skills_cache.clear()
        for s in skills:
            _skills_cache[s.id] = s


async def seed_builtin_skills(db: AsyncSession):
    """Insert or update built-in skills from the pluggable registry.

    Code-owned fields (prompt, template, schema, settings_schema) are always
    refreshed. User-editable fields (enabled, name, description, settings) are
    not overwritten; `settings` is seeded with `default_settings` on first insert.
    """
    for skill_data in discover_skills():
        skill_data = dict(skill_data)
        default_settings = skill_data.pop("_default_settings", None)
        existing = await db.get(Skill, skill_data["id"])
        if not existing:
            init = dict(skill_data)
            if default_settings is not None:
                init["settings"] = default_settings
            db.add(Skill(**init))
        else:
            for field in _CODE_FIELDS:
                if field in skill_data:
                    setattr(existing, field, skill_data[field])
            # Add any new default_settings keys without overwriting user-set ones
            if default_settings:
                merged = dict(default_settings)
                merged.update(existing.settings or {})
                existing.settings = merged
    await db.commit()
    await load_skills()


def get_skill(name: str) -> Skill | None:
    return _skills_cache.get(name)


def get_skill_setting(skill_id: str, key: str, default=None):
    """Read a per-skill setting value, falling back to the manifest default."""
    skill = _skills_cache.get(skill_id)
    if skill is None:
        return default
    settings = skill.settings or {}
    if key in settings:
        return settings[key]
    for field in (skill.settings_schema or []):
        if field.get("key") == key:
            return field.get("default", default)
    return default


def list_skill_index(enabled_filter: set[str] | None = None) -> str:
    """Render skill index for system prompt. Only enabled, non-internal skills."""
    lines = []
    for name in sorted(_skills_cache):
        skill = _skills_cache[name]
        if skill.is_internal or not skill.enabled:
            continue
        if enabled_filter and name not in enabled_filter:
            continue
        lines.append(f"- `{name}` — {skill.description}")
    return "\n".join(lines)


def get_widget_skills() -> list[dict]:
    """Return all enabled widget skills with their templates (for frontend cache)."""
    result = []
    for skill in _skills_cache.values():
        if skill.category == "widget" and skill.enabled and skill.template_html:
            result.append({
                "id": skill.id,
                "name": skill.name,
                "template_html": skill.template_html,
                "template_css": skill.template_css or "",
            })
    return result


async def create_skill(db: AsyncSession, data: dict) -> Skill:
    skill = Skill(**data)
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    _skills_cache[skill.id] = skill
    return skill


async def update_skill(db: AsyncSession, skill_id: str, data: dict) -> Skill | None:
    skill = await db.get(Skill, skill_id)
    if not skill:
        return None
    for key, val in data.items():
        setattr(skill, key, val)
    await db.commit()
    await db.refresh(skill)
    _skills_cache[skill.id] = skill
    return skill


async def delete_skill(db: AsyncSession, skill_id: str) -> bool:
    skill = await db.get(Skill, skill_id)
    if not skill:
        return False
    await db.delete(skill)
    await db.commit()
    _skills_cache.pop(skill_id, None)
    return True


async def get_all_skills(db: AsyncSession) -> list[Skill]:
    result = await db.execute(select(Skill).order_by(Skill.name))
    return list(result.scalars().all())


def build_enabled_skills(
    *, search_mode: bool = False, search_enabled: bool, sandbox_available: bool
) -> set[str]:
    """Compute the set of skill IDs the model should see for this turn.

    Single pass over `_skills_cache` — earlier versions iterated 4-5 times.
    """
    if search_mode:
        return {"fast_search"} if _skills_cache.get("fast_search") else set()

    enabled: set[str] = set()
    for sid, sk in _skills_cache.items():
        if not sk.enabled or sk.is_internal:
            continue
        cat = sk.category
        if cat == "artifact" or cat == "widget":
            enabled.add(sid)
        elif sid in ("web_search", "fast_search"):
            if search_enabled:
                enabled.add(sid)
        elif sid == "sandbox":
            if sandbox_available:
                enabled.add(sid)
        elif sid in ("image_generation", "music_generation"):
            enabled.add(sid)
    return enabled


def build_tools_for_api(
    base_tools: list[dict],
    image_tool: dict,
    music_tool: dict,
    sandbox_tools: list[dict],
    search_tools: list[dict],
    *,
    search_mode: bool = False,
    search_enabled: bool,
    sandbox_available: bool,
) -> list[dict]:
    """Assemble the tools list passed to the provider for one completion turn."""
    tools = list(base_tools)
    img = _skills_cache.get("image_generation")
    if img and img.enabled:
        tools.append(image_tool)
    music = _skills_cache.get("music_generation")
    if music and music.enabled:
        tools.append(music_tool)
    if search_mode:
        tools.extend(search_tools)
    else:
        sb = _skills_cache.get("sandbox")
        if sb and sb.enabled and sandbox_available:
            tools.extend(sandbox_tools)
        if search_enabled:
            tools.extend(search_tools)
    return tools
