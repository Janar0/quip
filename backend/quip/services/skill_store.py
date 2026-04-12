"""Database-backed skill store with seeding for built-in skills."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from quip.models.skill import Skill
from quip.database import async_session

# Cache loaded from DB at startup
_skills_cache: dict[str, Skill] = {}


async def load_skills():
    """Load all skills from DB into memory cache. Called at startup."""
    async with async_session() as db:
        result = await db.execute(select(Skill))
        skills = result.scalars().all()
        _skills_cache.clear()
        for s in skills:
            _skills_cache[s.id] = s


async def seed_builtin_skills(db: AsyncSession):
    """Insert or update built-in skills. Called at startup.

    For existing built-in skills, refreshes code-owned fields (prompt_instructions,
    data_schema, template_html, template_css, api_config) from the source definition.
    User-editable fields (enabled, name, description) are NOT overwritten.
    """
    from quip.services.builtin_skills import BUILTIN_SKILLS
    # Fields controlled by code — always sync from source
    CODE_FIELDS = {"prompt_instructions", "data_schema", "template_html", "template_css", "api_config", "is_builtin", "is_internal"}
    for skill_data in BUILTIN_SKILLS:
        existing = await db.get(Skill, skill_data["id"])
        if not existing:
            db.add(Skill(**skill_data))
        else:
            for field in CODE_FIELDS:
                if field in skill_data:
                    setattr(existing, field, skill_data[field])
    await db.commit()
    await load_skills()


def get_skill(name: str) -> Skill | None:
    return _skills_cache.get(name)


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
