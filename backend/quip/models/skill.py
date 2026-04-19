from sqlalchemy import Column, String, Text, Boolean, DateTime, JSON, func

from quip.database import Base


class Skill(Base):
    __tablename__ = "skill"

    id = Column(String, primary_key=True)          # slug: "weather", "recipe"
    name = Column(String, nullable=False)           # display: "Weather", "Recipe"
    description = Column(Text, nullable=False)      # one-line for AI index
    category = Column(String, nullable=False, default="widget")  # "widget", "tool", "artifact"
    icon = Column(String, nullable=True)            # SVG path data for admin UI icon
    type = Column(String, nullable=False)           # "api" or "content"
    enabled = Column(Boolean, nullable=False, default=True)

    # AI prompt — what the model sees when it calls load_skill
    prompt_instructions = Column(Text, nullable=False, default="")
    # JSON schema describing the data structure (for documentation/validation)
    data_schema = Column(JSON, nullable=True)

    # Template for rendering
    template_html = Column(Text, nullable=True)
    template_css = Column(Text, nullable=True)

    # API config (only for type="api")
    api_config = Column(JSON, nullable=True)

    # Per-skill runtime settings (operator-tunable; e.g. model name, provider).
    # settings_schema describes the fields; settings holds current values.
    settings_schema = Column(JSON, nullable=True)   # code-owned: list[{key,label,type,default,options?,help?}]
    settings = Column(JSON, nullable=True)          # user-owned: {key: value}

    # For non-widget skills (existing hardcoded ones migrated to DB)
    is_builtin = Column(Boolean, nullable=False, default=False)
    is_internal = Column(Boolean, nullable=False, default=False)  # hidden from skill index

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
