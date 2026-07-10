"""System prompt assembly: skills index, RAG context, locale, geo."""
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting, get_setting
from quip.models.user import User
from quip.services.geo import client_ip, format_location, resolve
from quip.services.rag import format_rag_context, retrieve_context
from quip.services.skill_store import (
    build_enabled_skills,
    build_gated_tools_for_api,
    build_tools_for_api,
    get_skill,
    list_skill_index,
)
from quip.services.tools import (
    GATED_TOOL_MAP,
    GENERATE_IMAGE_TOOL,
    GENERATE_MUSIC_TOOL,
    GET_DOCUMENT_IMAGE_TOOL,
    SEARCH_TOOLS,
    LOAD_SKILL_TOOL,
    READ_URL_TOOL,
    SANDBOX_TOOLS,
    WIDGET_TOOL,
)

logger = logging.getLogger(__name__)


class PromptBuilder:
    """Assembles the system prompt and resolves runtime context."""

    @staticmethod
    def resolve_runtime_context(request, user: User) -> tuple[str | None, str | None]:
        """Return (locale, location) for the current request."""
        header = request.headers.get("accept-language", "")
        locale: str | None = None
        user_settings = user.settings or {}
        locale = user_settings.get("locale")
        if not locale and header:
            first = header.split(",")[0].split(";")[0].strip()
            if first:
                locale = first.split("-")[0] or None
        ip = client_ip(request)
        location = format_location(resolve(ip)) if ip else None
        return locale, location

    @staticmethod
    def build(
        tool_gating_enabled: bool,
        locale: str | None,
        location: str | None,
        search_enabled: bool,
        search_mode: bool,
        sandbox_available: bool,
    ) -> str:
        """Assemble the system prompt with skills and runtime context."""
        enabled_skills = build_enabled_skills(
            search_mode=search_mode,
            search_enabled=search_enabled,
            sandbox_available=sandbox_available,
        )

        if tool_gating_enabled:
            role = (
                "You are QUIP, a helpful AI assistant. "
                "The `load_skill` tool is always available — use it to get detailed instructions "
                "for any skill. Some capabilities (web_search, sandbox, image_generation, "
                "music_generation) require you to call `load_skill` first — their tools appear "
                "only after you load the skill and read its instructions. "
                "Artifacts, widgets, and read_url are available directly. "
                "When the user's message contains an http/https URL, call `read_url` on it "
                "to fetch its content before answering."
            )
        else:
            role = (
                "You are QUIP, a helpful AI assistant. "
                "You have named skills you can load on demand with the `load_skill` tool. "
                "When you need details for a capability you don't remember (e.g. how to "
                "format a plot artifact, how to use the sandbox, or the web search "
                "answer style), call `load_skill` with its name before using it. "
                "When the user's message contains an http/https URL, call `read_url` on it "
                "to fetch its content before answering."
            )

        parts: list[str] = [role]

        rt_lines = [f"Current date: {datetime.now(UTC).date().isoformat()}."]
        if locale:
            rt_lines.append(
                f"User interface language: {locale}. Answer in this language unless the user writes in another."
            )
        if location:
            rt_lines.append(
                f"Approximate user location: {location}. Use local units, currency, and conventions when relevant."
            )
        parts.append("\n".join(rt_lines))

        # Fast-search mode: inject full skill body directly (no lazy
        # load_skill round-trip) only when user explicitly asks search mode.
        if search_mode and "fast_search" in enabled_skills:
            skill = get_skill("fast_search")
            if skill and skill.prompt_instructions:
                parts.append(skill.prompt_instructions)
            lazy_skills = enabled_skills - {"fast_search"}
        else:
            lazy_skills = enabled_skills

        index = list_skill_index(lazy_skills)
        if index:
            parts.append("Available skills:\n" + index)

        if "web_search" in enabled_skills or "fast_search" in enabled_skills:
            parts.append(
                "SEARCH CITATION RULE: Cite every non-obvious claim inline with [1], [2], etc. "
                "End your answer with a Sources block — strict format, one source per line:\n"
                "---\n"
                "**Sources:**\n"
                "[1] Exact page title - https://full-url.com/page\n"
                "[2] Exact page title - https://another-url.org/doc\n"
                "Translate 'Sources:' label into the user's language (e.g. 'Источники:' for Russian). "
                "When you search multiple times, number sources sequentially: first search = [1]...[N], "
                "second = [N+1]...[M]. Every [n] in text must have a matching entry here. "
                "CRITICAL: every line must start with [N], use ' - ' between title and full URL, "
                "never split across lines, never use domain names as URLs. "
                "Only present what the search actually returned."
            )

        admin = get_setting("system_prompt", "").strip()
        if admin:
            parts.append(admin)

        return "\n\n".join(parts)

    @staticmethod
    async def inject_rag(
        system_prompt: str,
        user_message: str,
        chat_id,
        user_id,
        inlined_doc_file_ids: set[str],
        db: AsyncSession,
        workspace_id=None,
    ) -> str:
        """Append RAG context to system prompt if enabled and chunks available."""
        if not get_bool_setting("rag_enabled", True):
            return system_prompt
        try:
            rag_chunks = await retrieve_context(
                user_message,
                chat_id,
                user_id,
                db,
                workspace_id=workspace_id,
            )
            if inlined_doc_file_ids:
                rag_chunks = [
                    c
                    for c in rag_chunks
                    if c.get("file_id") not in inlined_doc_file_ids
                ]
            if rag_chunks:
                rag_context = format_rag_context(rag_chunks)
                prompt = (system_prompt + "\n\n" + rag_context).strip()
                logger.info(
                    "RAG: injected %d chunks (%d chars) into prompt for chat=%s",
                    len(rag_chunks),
                    len(rag_context),
                    str(chat_id)[:8],
                )
                return prompt
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")
        return system_prompt

    @staticmethod
    def resolve_model(
        model: str,
        search_mode: bool = False,
    ) -> str:
        """Resolve effective model with optional overrides."""
        if search_mode:
            _sm = get_setting("search_model", "")
            if _sm:
                return _sm
        return model

    @staticmethod
    def build_tools(
        tool_gating_enabled: bool,
        loaded_skills: set[str],
        search_mode: bool,
        search_enabled: bool,
        sandbox_available: bool,
    ) -> list[dict]:
        """Build the tool list for API requests, respecting gating."""
        base_tools = [
            LOAD_SKILL_TOOL,
            WIDGET_TOOL,
            READ_URL_TOOL,
            GET_DOCUMENT_IMAGE_TOOL,
        ]

        if tool_gating_enabled and not search_mode:
            return build_gated_tools_for_api(
                base_tools=base_tools,
                unlocked_gates=loaded_skills,
                gated_tool_map=GATED_TOOL_MAP,
            )
        return build_tools_for_api(
            base_tools=base_tools,
            image_tool=GENERATE_IMAGE_TOOL,
            music_tool=GENERATE_MUSIC_TOOL,
            sandbox_tools=SANDBOX_TOOLS,
            search_tools=SEARCH_TOOLS,
            search_mode=search_mode,
            search_enabled=search_enabled,
            sandbox_available=sandbox_available,
        )
