"""Skill manifest — canonical types for the skill system."""

from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SkillDef:
    """Lightweight in-memory skill definition returned to the LLM."""
    name: str
    summary: str        # one-line pitch for the skill index
    when_to_use: str    # trigger hint (reserved for future use)
    body: str           # full prompt instructions


@dataclass
class SkillSettingField:
    """Descriptor for a single field in the admin settings form."""
    key: str
    label: str
    type: str           # "text" | "select" | "number" | "boolean" | "password"
    default: str = ""
    options: list[str] | None = None
    help: str | None = None


@dataclass
class SkillManifest:
    """Canonical skill manifest — mirrors the SKILL dict from each skill module.

    Used for validation and DB seeding. Not stored in the SKILL dict files
    themselves (those stay as plain dicts for now).
    """
    id: str
    name: str
    description: str
    category: str              # "widget" | "tool" | "artifact"
    type: str                  # "content" | "api"
    enabled: bool = True
    is_builtin: bool = True
    is_internal: bool = False
    prompt_instructions: str = ""

    icon: str | None = None
    data_schema: dict | None = None
    template_html: str | None = None
    template_css: str | None = None
    api_config: dict | None = None
    settings_schema: list[dict] | None = None
    default_settings: dict | None = field(default=None, repr=False)

    # Runtime-only (stripped before seeding DB)
    handler: Callable | None = field(default=None, repr=False, compare=False)
    _handler_key: str | None = field(default=None, repr=False)

    @classmethod
    def from_dict(cls, data: dict) -> "SkillManifest":
        """Construct and validate from a raw SKILL dict."""
        known = {
            "id", "name", "description", "category", "type", "enabled",
            "is_builtin", "is_internal", "prompt_instructions",
            "icon", "data_schema", "template_html", "template_css",
            "api_config", "settings_schema",
        }
        kwargs = {k: data[k] for k in known if k in data}
        kwargs["handler"] = data.get("handler")
        kwargs["_handler_key"] = data.get("_handler_key")
        kwargs["default_settings"] = data.get("default_settings")
        return cls(**kwargs)

    def to_seed_dict(self) -> dict:
        """Convert to a dict for seed_builtin_skills (DB fields + _default_settings)."""
        result = {
            "id": self.id, "name": self.name, "description": self.description,
            "category": self.category, "type": self.type, "enabled": self.enabled,
            "is_builtin": self.is_builtin, "is_internal": self.is_internal,
            "prompt_instructions": self.prompt_instructions,
            "icon": self.icon, "data_schema": self.data_schema,
            "template_html": self.template_html, "template_css": self.template_css,
            "api_config": self.api_config, "settings_schema": self.settings_schema,
        }
        if self.default_settings is not None:
            result["_default_settings"] = self.default_settings
        return result
