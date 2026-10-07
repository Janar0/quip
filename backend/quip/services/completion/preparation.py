"""Request preparation: tenant-scoped attachments, model policy and provider history."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting, get_setting
from quip.models.budget import Budget
from quip.models.chat import Chat, Message
from quip.models.file import File
from quip.models.usage import UsageLog
from quip.models.user import User
from quip.models.workspace import Workspace
from quip.routers.models import get_cached_model, get_default_model
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.services.completion.prompt import PromptBuilder
from quip.services.multimodal import build_multimodal_message
from quip.services.sandbox import sandbox_manager
from quip.services.workspaces import ensure_personal_workspace, get_workspace_for_user

logger = logging.getLogger(__name__)


async def check_budget(user: User, db: AsyncSession, *, session_factory) -> None:
    has_budget = await db.execute(
        select(Budget.id).where((Budget.user_id == user.id) | (Budget.user_id.is_(None))).limit(1)
    )
    if has_budget.scalar_one_or_none() is None:
        return

    async with session_factory() as fresh_db:
        for user_filter in [Budget.user_id == user.id, Budget.user_id.is_(None)]:
            result = await fresh_db.execute(select(Budget).where(user_filter))
            budgets = result.scalars().all()
            if not budgets:
                continue
            now = datetime.now(UTC)
            for budget in budgets:
                if not budget or budget.limit_usd <= 0:
                    continue
                if budget.period == "daily":
                    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
                else:
                    since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                usage_result = await fresh_db.execute(
                    select(func.coalesce(func.sum(UsageLog.cost), 0)).where(
                        UsageLog.user_id == user.id, UsageLog.created_at >= since
                    )
                )
                current_cost = Decimal(usage_result.scalar() or 0)
                if current_cost >= budget.limit_usd:
                    raise HTTPException(
                        status_code=429,
                        detail={
                            "code": "budget_exceeded",
                            "current": float(current_cost),
                            "limit": float(budget.limit_usd),
                            "period": budget.period,
                        },
                    )


async def _load_attachments(
    file_ids: list[UUID],
    user_id: UUID,
    chat_id: UUID,
    workspace_id: UUID | None,
    db: AsyncSession,
) -> list[dict]:
    if not file_ids:
        return []

    unique_ids = list(dict.fromkeys(file_ids))
    result = await db.execute(
        select(File).where(
            File.id.in_(unique_ids),
            File.user_id == user_id,
            or_(File.chat_id == chat_id, File.chat_id.is_(None)),
            or_(File.workspace_id == workspace_id, File.workspace_id.is_(None)),
        )
    )
    files_by_id = {file.id: file for file in result.scalars().all()}
    if len(files_by_id) != len(unique_ids):
        # Do not disclose whether a rejected ID exists for another tenant or chat.
        raise HTTPException(status_code=404, detail="One or more files not found")

    files = [files_by_id[file_id] for file_id in unique_ids]
    return [
        {
            "file_id": str(f.id),
            "filename": f.filename,
            "file_type": f.file_type,
            "content_type": f.content_type,
            "storage_path": f.storage_path,
        }
        for f in files
    ]


async def _build_history_dicts(
    messages: list[Message],
    file_path_map: dict[str, str],
    is_ollama: bool,
    db: AsyncSession,
) -> tuple[list[dict], set[str]]:
    history = []
    inlined_doc_file_ids: set[str] = set()
    for m in messages:
        if not m.content:
            continue
        msg_dict = {"role": m.role, "content": m.content}
        msg_attachments = (m.meta or {}).get("attachments", [])
        if msg_attachments:
            enriched = [{**a, "storage_path": file_path_map.get(a.get("file_id", ""), "")} for a in msg_attachments]
            msg_dict, doc_ids = await build_multimodal_message(msg_dict, enriched, is_ollama, db=db)
            inlined_doc_file_ids.update(doc_ids)
        if m.role == "assistant" and m.tool_calls:
            gen_urls: list[str] = []
            for tc in m.tool_calls:
                if tc.get("name") == "generate_image":
                    result = tc.get("result")
                    if isinstance(result, dict):
                        gen_urls.extend(result.get("urls", []))
                        if not gen_urls and result.get("url"):
                            gen_urls.append(result["url"])
            if gen_urls:
                url_note = "\n[Generated image URLs: " + ", ".join(gen_urls) + "]"
                msg_dict["content"] = (msg_dict.get("content") or "") + url_note
        history.append(msg_dict)
    return history, inlined_doc_file_ids


def _resolve_model(model: str, *, search_mode: bool = False) -> str:
    """Resolve effective model — shared between chat_completion and regenerate.

    Applies search_mode override from config, then falls back to cached model list
    if nothing selected.
    """
    effective = PromptBuilder.resolve_model(model, search_mode=search_mode)
    if not effective:
        default = get_default_model()
        if default:
            return default["id"]
        return model
    return effective


def _validate_model(model_id: str) -> dict:
    """Validate model ID exists in cache and has valid context_length.

    Returns model metadata dict. Never raises — always returns a usable dict.
    """
    cached = get_cached_model(model_id)
    if not cached:
        # Model not in cache — could be unsupported or (commonly) the model
        # list cache has expired (OpenRouter TTL 5 min, Ollama 30 s). The
        # context window is simply UNKNOWN here; context_length=0 signals
        # _truncate_history to skip truncation rather than assume a tiny 4096
        # window and shred the prompt (which drops the user's own message).
        logger.warning("Model %s not found in cache — allowing request to proceed", model_id)
        return {"id": model_id, "context_length": 0, "supports_tools": True}

    if cached.get("context_length", 0) <= 0:
        logger.warning(
            "Model %s has context_length=%s — may not work correctly",
            model_id,
            cached.get("context_length"),
        )
        # Don't block — just warn

    return cached


def _truncate_history(
    history: list[dict],
    model_info: dict,
    *,
    max_output_tokens: int = 4096,
) -> list[dict]:
    """Truncate oldest messages if estimated tokens exceed context_length.

    Uses a rough heuristic: chars / 4 ≈ tokens. Preserves system prompt at
    the front and truncates from the oldest non-system message.
    """
    context_length = model_info.get("context_length", 0)
    if context_length <= 0:
        return history  # unknown context — skip truncation

    available = max(context_length - max_output_tokens, 1024)
    if available <= 0:
        return history

    # Estimate total tokens
    total_chars = sum(len(m.get("content", "") or "") for m in history)
    estimated_tokens = total_chars // 4

    if estimated_tokens <= available:
        return history

    # Truncate from the front, keeping system prompt at position 0
    system_msgs = [m for m in history if m.get("role") == "system"]
    non_system = [m for m in history if m.get("role") != "system"]

    # Never drop the most recent turn — that's the user's current question.
    # Dropping it leaves the model with only the system prompt and produces
    # nonsense / unrelated output. Trim only the older turns ahead of it.
    pinned = non_system[-1:] if non_system else []
    trimmed = non_system[:-1]
    while trimmed:
        current_chars = sum(len(m.get("content", "") or "") for m in system_msgs + trimmed + pinned)
        if current_chars // 4 <= available:
            break
        trimmed.pop(0)  # remove oldest

    result = system_msgs + trimmed + pinned
    dropped = len(history) - len(result)
    if dropped > 0:
        logger.warning(
            "Truncated %d messages from history (%d → %d) to fit context_length=%d",
            dropped,
            len(history),
            len(result),
            context_length,
        )
    return result


@dataclass
class PreparedPrompt:
    history: list[dict]
    model: str
    model_info: dict
    api_key: str
    search_enabled: bool
    search_mode: bool
    tool_gating_enabled: bool
    locale: str
    location: str

    @property
    def is_ollama(self) -> bool:
        return self.model.startswith("ollama/")


async def prepare_prompt(
    *,
    chain: list[Message],
    file_path_map: dict[str, str],
    model: str,
    search_mode: bool,
    query: str,
    request,
    user: User,
    chat: Chat,
    workspace: Workspace,
    db: AsyncSession,
    regenerate: bool = False,
) -> PreparedPrompt:
    """Build the shared provider context before admitting any new chat turn."""
    effective_model = _resolve_model(model, search_mode=search_mode)
    model_info = _validate_model(effective_model)
    api_key = get_setting("openrouter_api_key")
    is_ollama = effective_model.startswith("ollama/")
    if not is_ollama and not api_key:
        detail = "No OpenRouter API key configured."
        if not regenerate:
            detail += " Add one in Admin > Settings."
        raise HTTPException(status_code=400, detail=detail)
    history, inlined_doc_file_ids = await _build_history_dicts(chain, file_path_map, is_ollama, db)
    search_enabled = get_bool_setting("search_enabled", False)
    tool_gating_enabled = get_bool_setting("tool_gating_enabled", True)
    locale, location = PromptBuilder.resolve_runtime_context(request, user)
    system_prompt = PromptBuilder.build(
        tool_gating_enabled=tool_gating_enabled,
        locale=locale,
        location=location,
        search_enabled=search_enabled,
        search_mode=search_mode,
        sandbox_available=sandbox_manager.available,
    )
    if workspace.instructions:
        system_prompt = (
            system_prompt + "\n\nWORKSPACE INSTRUCTIONS (apply throughout this workspace):\n" + workspace.instructions
        ).strip()
    # Regeneration historically retrieves all relevant documents afresh.
    if query or not regenerate:
        system_prompt = await PromptBuilder.inject_rag(
            system_prompt,
            query,
            chat.id,
            user.id,
            set() if regenerate else inlined_doc_file_ids,
            db,
            workspace_id=chat.workspace_id,
        )
    if system_prompt:
        history.insert(0, {"role": "system", "content": system_prompt})
    return PreparedPrompt(
        _truncate_history(history, model_info),
        effective_model,
        model_info,
        api_key,
        search_enabled,
        search_mode,
        tool_gating_enabled,
        locale,
        location,
    )


async def determine_parent(db: AsyncSession, chat: Chat, branch_from_message_id: UUID | None) -> UUID | None:
    if branch_from_message_id:
        result = await db.execute(
            select(Message).where(
                Message.id == branch_from_message_id,
                Message.chat_id == chat.id,
            )
        )
        source_msg = result.scalar_one_or_none()
        return source_msg.parent_id if source_msg else None
    parent_ids_subq = select(Message.parent_id).where(
        Message.chat_id == chat.id,
        Message.parent_id.isnot(None),
    )
    leaf_result = await db.execute(
        select(Message.id)
        .where(Message.chat_id == chat.id, ~Message.id.in_(parent_ids_subq))
        .order_by(Message.created_at.desc())
        .limit(1)
    )
    return leaf_result.scalar_one_or_none()


async def load_chat_workspace(
    req: CompletionRequest | RegenerateRequest, user: User, db: AsyncSession
) -> tuple[Chat, Workspace]:
    """Resolve workspace ownership, leaving new chats private until admission."""
    if req.chat_id:
        result = await db.execute(select(Chat).where(Chat.id == req.chat_id, Chat.user_id == user.id))
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        if chat.workspace_id is None:
            chat.workspace_id = (await ensure_personal_workspace(user, db)).id
        if getattr(req, "workspace_id", None) and req.workspace_id != chat.workspace_id:
            raise HTTPException(status_code=404, detail="Chat not found in workspace")
        workspace = await get_workspace_for_user(chat.workspace_id, user.id, db)
    else:
        workspace = (
            await get_workspace_for_user(req.workspace_id, user.id, db)
            if req.workspace_id
            else await ensure_personal_workspace(user, db)
        )
        chat = Chat(
            id=uuid4(),
            user_id=user.id,
            workspace_id=workspace.id,
            title=req.message[:50] + ("..." if len(req.message) > 50 else ""),
            model=req.model or workspace.default_model,
        )
    return chat, workspace
