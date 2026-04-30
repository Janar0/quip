"""Pluggable skill registry.

Each skill lives in `skills/<category>/<skill_id>.py` and exports a `SKILL: dict`
with all DB fields plus optional extras:

  - `settings_schema`: list of field descriptors for the admin settings form:
      [{"key": "model", "label": "Model", "type": "text"|"select"|"number"|"boolean",
        "default": "...", "options": ["..."], "help": "..."}]
  - `default_settings`: {key: value} initial values (merged into skill.settings on seed).
  - `handler`: optional callable, registered by tool/widget name for dispatch.
      For tools: key is the tool name (e.g. "generate_image"); signature (args, ctx) -> dict.
      For widgets: key is "widget:<skill_id>"; signature (skill, params) -> dict.

discover_skills() walks all three category subpackages and returns (skills, handlers).
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable

from quip.core.skill_manifest import SkillManifest

logger = logging.getLogger(__name__)

_SUBPACKAGES = ("widgets", "tools", "artifacts")

# Populated by discover_skills(). Other modules import these.
HANDLERS: dict[str, Callable] = {}


def discover_skills() -> list[dict]:
    """Import every skill module under skills/{widgets,tools,artifacts}/ and collect
    their SKILL dicts. Also registers handlers in HANDLERS."""
    HANDLERS.clear()
    collected: list[dict] = []
    seen: set[str] = set()

    for sub in _SUBPACKAGES:
        pkg = importlib.import_module(f"quip.skills.{sub}")
        for mod_info in pkgutil.iter_modules(pkg.__path__):
            if mod_info.name.startswith("_"):
                continue
            mod = importlib.import_module(f"quip.skills.{sub}.{mod_info.name}")
            skill = getattr(mod, "SKILL", None)
            if not isinstance(skill, dict):
                continue
            sid = skill.get("id")
            if not sid or sid in seen:
                continue
            seen.add(sid)

            # Validate against SkillManifest (warn on failure but don't block)
            try:
                manifest = SkillManifest.from_dict(skill)
            except Exception:
                logger.warning(
                    "Skipping skill %s/%s: invalid SKILL dict", sub, mod_info.name,
                    exc_info=True,
                )
                continue

            # Separate code-owned metadata from DB fields
            skill_copy = manifest.to_seed_dict()
            handler = skill.get("handler")
            if handler is not None:
                # widget handlers registered under "widget:<id>"; tool handlers under tool name
                key = skill.get("_handler_key") or sid
                HANDLERS[key] = handler

            collected.append(skill_copy)
    return collected
