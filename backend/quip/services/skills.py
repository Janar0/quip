"""Backward-compat re-exports. Use quip.core.skill_manifest + quip.services.skill_store."""
from quip.core.skill_manifest import SkillDef  # noqa: F401
from quip.services.skill_store import get_skill_def as get_skill  # noqa: F401
from quip.services.skill_store import list_skill_index_markdown as list_skill_index  # noqa: F401
