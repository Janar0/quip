"""Skill registry — Claude-Skills-style on-demand prompt loading.

Delegates to the DB-backed skill store (`services/skill_store.py`) which is
the authoritative source. The base system prompt only lists skill NAMES.
When the model needs details, it calls `load_skill(name)` and gets the full
instructions as a tool result.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class SkillDef:
    name: str
    summary: str       # one-line pitch for the skill index
    when_to_use: str   # trigger hint
    body: str          # full detailed instructions returned by load_skill


_INTERNAL_SKILLS = {"search_sub_agent", "sandbox_sub_agent", "artifact_sub_agent"}


def _to_skilldef(db_skill) -> SkillDef:
    return SkillDef(
        name=db_skill.id,
        summary=db_skill.description or "",
        when_to_use="",
        body=db_skill.prompt_instructions or "",
    )


def get_skill(name: str) -> SkillDef | None:
    """Load skill instructions from the DB-backed store."""
    from quip.services.skill_store import get_skill as db_get_skill
    skill = db_get_skill(name)
    if not skill:
        return None
    return _to_skilldef(skill)


def list_skill_index(enabled: set[str]) -> str:
    """Render a compact one-line-per-skill index for the base system prompt."""
    from quip.services.skill_store import get_skill as db_get_skill
    lines = []
    for name in sorted(enabled):
        if name in _INTERNAL_SKILLS:
            continue
        skill = db_get_skill(name)
        if not skill:
            continue
        summary = skill.description or ""
        lines.append(f"- `{name}` — {summary}.")
    return "\n".join(lines)
