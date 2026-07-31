"""Top-level completion service — orchestrates chat & regenerate flows."""
import asyncio
import json
import logging
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting, get_setting
from quip.database import async_session
from quip.models.budget import Budget
from quip.models.chat import Chat, ChatRun, Message
from quip.models.file import DocumentChunk, File
from quip.models.usage import UsageLog
from quip.models.user import User
from quip.routers.models import get_cached_model, get_default_model
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.services.completion.history import HistoryService
from quip.services.completion.prompt import PromptBuilder
from quip.services.completion.stream import StreamOrchestrator, fetch_generation_cost
from quip.services.messages_persist import save_assistant_message
from quip.services.multimodal import build_multimodal_message
from quip.services.sandbox import sandbox_manager
from quip.services.skill_store import get_skill as get_skill_by_name
from quip.services.streaming import sse_event
from quip.services.title import generate_chat_identity, is_implicit_chat_title
from quip.services.workspaces import ensure_personal_workspace, get_workspace_for_user

logger = logging.getLogger(__name__)

UPLOAD_DIR = None


async def _set_run_status(
    run_id: UUID,
    status: str,
    error: str | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Best-effort durable status update, independent of the request session."""
    try:
        async def persist(run_db: AsyncSession) -> None:
            run = await run_db.get(ChatRun, run_id)
            if run is None:
                return
            run.status = status
            run.error = error[:4000] if error else None
            if status in {"completed", "failed", "cancelled"}:
                run.finished_at = datetime.now(UTC)
            await run_db.commit()

        if db is not None:
            await persist(db)
        else:
            async with async_session() as run_db:
                await persist(run_db)
    except Exception:
        logger.exception("Failed to persist chat run status for %s", run_id)


def _get_upload_dir():
    global UPLOAD_DIR
    if UPLOAD_DIR is None:
        from quip.routers.files import UPLOAD_DIR as _dir
        UPLOAD_DIR = _dir
    return UPLOAD_DIR


async def _check_budget(user: User, db: AsyncSession) -> None:
    has_budget = await db.execute(
        select(Budget.id)
        .where((Budget.user_id == user.id) | (Budget.user_id.is_(None)))
        .limit(1)
    )
    if has_budget.scalar_one_or_none() is None:
        return

    async with async_session() as fresh_db:
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
                    from fastapi import HTTPException
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
        from fastapi import HTTPException

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


async def _copy_attachments_to_sandbox(
    user: User, chat: Chat, attachments: list[dict], db: AsyncSession
) -> None:
    if not attachments:
        return
    sb_skill = get_skill_by_name("sandbox")
    if not (sb_skill and sb_skill.enabled):
        return
    if not sandbox_manager.available:
        return

    upload_dir = _get_upload_dir()
    try:
        sandbox = await sandbox_manager.get_or_create(user.id, db)
        await sandbox_manager.ensure_chat_dir(sandbox, str(chat.id))
    except Exception as e:
        logger.warning("Failed to get/create sandbox for file copy: %s", e)
        return

    chat_id = str(chat.id)
    used_names: set[str] = set()
    for att in attachments:
        storage_path = att.get("storage_path", "")
        if not storage_path:
            continue
        host_path = upload_dir / storage_path
        dest = att.get("filename") or host_path.name
        if dest in used_names:
            short = str(att.get("file_id", "")).replace("-", "")[:6] or "dup"
            stem, dot, ext = dest.rpartition(".")
            dest = f"{stem}_{short}.{ext}" if dot else f"{dest}_{short}"
        used_names.add(dest)
        try:
            await sandbox_manager.copy_host_file(sandbox, chat_id, host_path, dest)
        except Exception as e:
            logger.warning("copy_host_file failed for %s: %s", dest, e)


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
            enriched = [
                {**a, "storage_path": file_path_map.get(a.get("file_id", ""), "")}
                for a in msg_attachments
            ]
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


def _parse_sse_frame(frame: str) -> tuple[str, dict]:
    """Parse SSE frame into (event_type, data)."""
    ev = ""
    data_str = ""
    for line in frame.strip().split("\n"):
        if line.startswith("event: "):
            ev = line[7:]
        elif line.startswith("data: "):
            data_str = line[6:]
    try:
        data = json.loads(data_str) if data_str else {}
    except json.JSONDecodeError:
        data = {}
    return ev, data


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
            model_id, cached.get("context_length"),
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
        current_chars = sum(
            len(m.get("content", "") or "") for m in system_msgs + trimmed + pinned
        )
        if current_chars // 4 <= available:
            break
        trimmed.pop(0)  # remove oldest

    result = system_msgs + trimmed + pinned
    dropped = len(history) - len(result)
    if dropped > 0:
        logger.warning(
            "Truncated %d messages from history (%d → %d) to fit context_length=%d",
            dropped, len(history), len(result), context_length,
        )
    return result


def _accumulate_usage(acc: dict | None, new: dict | None) -> dict | None:
    """Sum usage across streaming rounds.

    The orchestrator emits one usage event per round (a tool/search turn runs
    several rounds). Persisting only the last round under-counts tokens and
    cost for every earlier round, so we accumulate instead of overwrite —
    mirroring ResearchSession.add_usage for the deep-research path.
    """
    if not new:
        return acc
    if acc is None:
        acc = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0, "cost": 0.0}
    for k in ("prompt_tokens", "completion_tokens", "cached_tokens"):
        acc[k] = (acc.get(k) or 0) + (new.get(k) or 0)
    acc["cost"] = (acc.get("cost") or 0.0) + (new.get("cost") or 0.0)
    if new.get("provider"):
        acc["provider"] = new["provider"]
    # Keep the most recent generation_id — used as the cost-fetch fallback.
    if new.get("generation_id"):
        acc["generation_id"] = new["generation_id"]
    return acc


class CompletionService:

    @staticmethod
    async def determine_parent(
        db: AsyncSession, chat: Chat, branch_from_message_id: UUID | None
    ) -> UUID | None:
        if branch_from_message_id:
            result = await db.execute(
                select(Message).where(
                    Message.id == branch_from_message_id, Message.chat_id == chat.id
                )
            )
            source_msg = result.scalar_one_or_none()
            return source_msg.parent_id if source_msg else None
        parent_ids_subq = select(Message.parent_id).where(
            Message.chat_id == chat.id, Message.parent_id.isnot(None)
        )
        leaf_result = await db.execute(
            select(Message.id)
            .where(Message.chat_id == chat.id, ~Message.id.in_(parent_ids_subq))
            .order_by(Message.created_at.desc())
            .limit(1)
        )
        return leaf_result.scalar_one_or_none()

    @staticmethod
    async def chat_completion(
        req: CompletionRequest, request, user: User, db: AsyncSession
    ):
        from fastapi import HTTPException
        from fastapi.responses import StreamingResponse

        await _check_budget(user, db)

        api_key = get_setting("openrouter_api_key")
        if not api_key:
            raise HTTPException(
                status_code=400,
                detail="No OpenRouter API key configured. Add one in Admin > Settings.",
            )

        is_new_chat = False
        if req.chat_id:
            result = await db.execute(
                select(Chat).where(Chat.id == req.chat_id, Chat.user_id == user.id)
            )
            chat = result.scalar_one_or_none()
            if not chat:
                raise HTTPException(status_code=404, detail="Chat not found")
            if chat.workspace_id is None:
                chat.workspace_id = (await ensure_personal_workspace(user, db)).id
            if req.workspace_id and req.workspace_id != chat.workspace_id:
                raise HTTPException(status_code=404, detail="Chat not found in workspace")
            workspace = await get_workspace_for_user(chat.workspace_id, user.id, db)
        else:
            is_new_chat = True
            workspace = (
                await get_workspace_for_user(req.workspace_id, user.id, db)
                if req.workspace_id
                else await ensure_personal_workspace(user, db)
            )
            title = req.message[:50] + ("..." if len(req.message) > 50 else "")
            chat = Chat(
                user_id=user.id,
                workspace_id=workspace.id,
                title=title,
                model=req.model or workspace.default_model,
            )
            db.add(chat)
            await db.flush()

        user_parent_id = await CompletionService.determine_parent(
            db, chat, req.branch_from_message_id
        )

        attachments = (
            await _load_attachments(req.file_ids, user.id, chat.id, chat.workspace_id, db)
            if req.file_ids
            else []
        )

        if attachments and chat:
            file_ids_to_link = [UUID(att["file_id"]) for att in attachments]
            await db.execute(
                update(File)
                .where(
                    File.id.in_(file_ids_to_link),
                    File.user_id == user.id,
                    File.chat_id.is_(None),
                    or_(File.workspace_id == chat.workspace_id, File.workspace_id.is_(None)),
                )
                .values(chat_id=chat.id, workspace_id=chat.workspace_id)
            )
            # Re-check after the atomic claim. If another completion linked an
            # unattached file to a different chat first, do not use its data.
            attachments = await _load_attachments(
                file_ids_to_link, user.id, chat.id, chat.workspace_id, db
            )
            await db.execute(
                update(DocumentChunk)
                .where(DocumentChunk.file_id.in_(file_ids_to_link), DocumentChunk.chat_id.is_(None))
                .values(chat_id=chat.id)
            )

        await _copy_attachments_to_sandbox(user, chat, attachments, db)

        user_meta = {}
        if attachments:
            user_meta["attachments"] = [
                {k: v for k, v in a.items() if k != "storage_path"} for a in attachments
            ]
        user_msg = Message(
            chat_id=chat.id, role="user", content=req.message,
            parent_id=user_parent_id, meta=user_meta or None,
        )
        db.add(user_msg)
        await db.flush()

        messages_for_history, file_path_map = await HistoryService.build(
            db, chat, req.branch_from_message_id, user_msg
        )
        history, inlined_doc_file_ids = await _build_history_dicts(
            messages_for_history, file_path_map, False, db
        )

        search_enabled = get_bool_setting("search_enabled", False)
        search_mode = req.mode_hint == "search" and search_enabled
        effective_model = _resolve_model(
            req.model, search_mode=search_mode
        )
        # Validate effective model against cache
        model_info = _validate_model(effective_model)

        tool_gating_enabled = get_bool_setting("tool_gating_enabled", True)
        locale, location = PromptBuilder.resolve_runtime_context(request, user)
        system_prompt = PromptBuilder.build(
            tool_gating_enabled=tool_gating_enabled,
            locale=locale, location=location,
            search_enabled=search_enabled, search_mode=search_mode,
            sandbox_available=sandbox_manager.available,
        )
        if workspace.instructions:
            system_prompt = (
                system_prompt
                + "\n\nWORKSPACE INSTRUCTIONS (apply throughout this workspace):\n"
                + workspace.instructions
            ).strip()
        system_prompt = await PromptBuilder.inject_rag(
            system_prompt,
            req.message,
            chat.id,
            user.id,
            inlined_doc_file_ids,
            db,
            workspace_id=chat.workspace_id,
        )
        if system_prompt:
            history.insert(0, {"role": "system", "content": system_prompt})

        # Truncate history to fit model context window
        history = _truncate_history(history, model_info)

        assistant_msg = Message(
            chat_id=chat.id, role="assistant", content="",
            model=effective_model, parent_id=user_msg.id,
        )
        db.add(assistant_msg)
        await db.flush()
        run = ChatRun(
            chat_id=chat.id,
            user_id=user.id,
            assistant_message_id=assistant_msg.id,
            status="running",
            model=effective_model,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        await db.commit()

        chat_id_str = str(chat.id)
        user_msg_id = str(user_msg.id)
        assistant_msg_id = str(assistant_msg.id)
        run_id = run.id
        user_id = user.id
        user_parent_id_str = str(user_msg.parent_id) if user_msg.parent_id else None
        model_supports_tools = model_info.get("supports_tools", True)

        async def generate():
            full_content = ""
            full_reasoning = ""
            last_usage = None
            tool_executions: list[dict] = []
            search_images: list[dict] = []

            yield sse_event("chat", {
                "chat_id": chat_id_str,
                "user_message_id": user_msg_id,
                "message_id": assistant_msg_id,
                "run_id": str(run_id),
                "user_parent_id": user_parent_id_str,
            })

            orchestrator = StreamOrchestrator(
                messages=list(history),
                model=effective_model,
                base_url="",
                api_key=api_key,
                tool_gating_enabled=tool_gating_enabled,
                search_enabled=search_enabled,
                search_mode=search_mode,
                sandbox_available=sandbox_manager.available,
                loaded_skills=set(),
                supports_tools=model_supports_tools,
                context_length=model_info.get("context_length", 0),
            )
            max_rounds = 3 if search_mode else 12
            async for sse_frame in orchestrator.run(
                chat_id=chat_id_str, user_id=user_id, max_rounds=max_rounds
            ):
                ev_type, data = _parse_sse_frame(sse_frame)
                if ev_type == "content":
                    full_content += data.get("text", "")
                elif ev_type == "reasoning":
                    full_reasoning += data.get("text", "")
                elif ev_type == "usage":
                    last_usage = _accumulate_usage(last_usage, data)
                elif ev_type == "tool_executing":
                    tool_executions.append(
                        {
                            "id": data.get("id"),
                            "name": data.get("name"),
                            "arguments": data.get("arguments"),
                            "status": "running",
                        }
                    )
                elif ev_type == "tool_result":
                    result = data.get("result")
                    try:
                        result = json.loads(result) if isinstance(result, str) else result
                    except json.JSONDecodeError:
                        pass
                    for execution in tool_executions:
                        if execution.get("id") == data.get("id"):
                            execution.update({"result": result, "status": data.get("status", "completed")})
                            break
                elif ev_type == "search_images":
                    incoming = data.get("images") or []
                    if not data.get("append"):
                        search_images = list(incoming)
                    else:
                        known = {item.get("img_src") for item in search_images}
                        search_images.extend(
                            item for item in incoming if item.get("img_src") not in known
                        )
                    search_images = search_images[:10]
                elif ev_type == "error":
                    yield sse_frame
                    if full_content:
                        await save_assistant_message(
                            assistant_msg_id, chat_id_str, user_id,
                            full_content, effective_model, last_usage,
                            reasoning=full_reasoning,
                            tool_executions=tool_executions,
                            search_images=search_images,
                        )
                    return
                yield sse_frame

            if not full_content and full_reasoning:
                full_content = full_reasoning
                full_reasoning = ""
                yield sse_event("content", {"text": full_content})

            # Cost fetch for OpenRouter
            if last_usage:
                await fetch_generation_cost(api_key, last_usage)

            if full_content:
                await save_assistant_message(
                    assistant_msg_id, chat_id_str, user_id,
                    full_content, effective_model, last_usage, reasoning=full_reasoning,
                    tool_executions=tool_executions,
                    search_images=search_images,
                )
                from quip.services.telegram_notify import notify_telegram_chat

                asyncio.create_task(notify_telegram_chat(chat, full_content, request))

            telegram_topic_implicit = (chat.meta or {}).get("telegram_topic_implicit")
            should_generate_telegram_title = (
                chat.source == "telegram"
                and (
                    telegram_topic_implicit
                    if "telegram_topic_implicit" in (chat.meta or {})
                    else is_implicit_chat_title(chat.title)
                )
            )
            if is_new_chat or should_generate_telegram_title:
                identity_model = get_setting("title_model", "") or effective_model
                identity = await generate_chat_identity(
                    req.message, identity_model, get_setting("openrouter_api_key", "")
                )
                if identity:
                    new_title, emoji = identity
                    async with async_session() as _tdb:
                        _chat = await _tdb.get(Chat, chat.id)
                        if _chat:
                            _chat.title = new_title[:200]
                            _chat.meta = {
                                **(_chat.meta or {}),
                                "emoji": emoji,
                                "telegram_topic_implicit": False,
                            }
                            await _tdb.commit()
                    yield sse_event("title", {"title": new_title, "emoji": emoji})

            yield sse_event("done", {})

        async def tracked_generate():
            error_message = None
            terminal = False
            try:
                async for frame in generate():
                    event_type, event_data = _parse_sse_frame(frame)
                    if event_type == "error":
                        error_message = str(event_data.get("error") or event_data.get("message") or "Generation failed")
                    yield frame
                if error_message:
                    await _set_run_status(run_id, "failed", error_message, db)
                else:
                    await _set_run_status(run_id, "completed", db=db)
                terminal = True
            except asyncio.CancelledError:
                await _set_run_status(run_id, "cancelled", "Client disconnected", db)
                terminal = True
                raise
            except Exception as exc:
                logger.exception("Chat run %s failed", run_id)
                await _set_run_status(run_id, "failed", str(exc), db)
                terminal = True
                yield sse_event("error", {"error": "Generation failed"})
            finally:
                if not terminal:
                    await _set_run_status(run_id, "cancelled", "Stream closed before completion", db)

        return StreamingResponse(
            tracked_generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    @staticmethod
    async def regenerate(
        req: RegenerateRequest, request, user: User, db: AsyncSession
    ):
        from fastapi import HTTPException
        from fastapi.responses import StreamingResponse

        await _check_budget(user, db)

        result = await db.execute(
            select(Chat).where(Chat.id == req.chat_id, Chat.user_id == user.id)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
        if chat.workspace_id is None:
            chat.workspace_id = (await ensure_personal_workspace(user, db)).id
        workspace = await get_workspace_for_user(chat.workspace_id, user.id, db)

        result = await db.execute(
            select(Message).where(Message.id == req.message_id, Message.chat_id == req.chat_id)
        )
        orig_msg = result.scalar_one_or_none()
        if not orig_msg or orig_msg.role != "assistant":
            raise HTTPException(
                status_code=400, detail="Message not found or not an assistant message"
            )

        # Resolve model with fallback chain — no hardcoded fallback
        raw_model = req.model or orig_msg.model or chat.model
        if not raw_model:
            default = get_default_model()
            if default:
                raw_model = default["id"]
            else:
                raise HTTPException(
                    status_code=400,
                    detail="No model selected. Set a default model in Admin > Settings or select one from the model picker.",
                )
        effective_model = _resolve_model(raw_model, search_mode=False)
        model_info = _validate_model(effective_model)

        api_key = get_setting("openrouter_api_key")
        if not api_key:
            raise HTTPException(
                status_code=400, detail="No OpenRouter API key configured."
            )

        chain, file_path_map = await HistoryService.build_for_regenerate(db, chat, orig_msg)
        history, _ = await _build_history_dicts(chain, file_path_map, False, db)

        search_enabled = get_bool_setting("search_enabled", False)
        tool_gating_enabled = get_bool_setting("tool_gating_enabled", True)
        regen_locale, regen_location = PromptBuilder.resolve_runtime_context(request, user)
        system_prompt = PromptBuilder.build(
            tool_gating_enabled=tool_gating_enabled,
            locale=regen_locale, location=regen_location,
            search_enabled=search_enabled, search_mode=False,
            sandbox_available=sandbox_manager.available,
        )
        if workspace.instructions:
            system_prompt = (
                system_prompt
                + "\n\nWORKSPACE INSTRUCTIONS (apply throughout this workspace):\n"
                + workspace.instructions
            ).strip()
        # Inject RAG context using the last user message in the chain
        last_user_msg = next((m.content for m in reversed(chain) if m.role == "user"), "")
        if last_user_msg:
            system_prompt = await PromptBuilder.inject_rag(
                system_prompt,
                last_user_msg,
                chat.id,
                user.id,
                set(),
                db,
                workspace_id=chat.workspace_id,
            )
        if system_prompt:
            history.insert(0, {"role": "system", "content": system_prompt})

        # Truncate history to fit model context window
        history = _truncate_history(history, model_info)

        model_supports_tools = model_info.get("supports_tools", True)

        new_msg = Message(
            chat_id=chat.id, role="assistant", content="",
            model=effective_model, parent_id=orig_msg.parent_id,
        )
        db.add(new_msg)
        await db.flush()
        run = ChatRun(
            chat_id=chat.id,
            user_id=user.id,
            assistant_message_id=new_msg.id,
            status="running",
            model=effective_model,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        await db.commit()

        chat_id_str = str(chat.id)
        new_msg_id = str(new_msg.id)
        run_id = run.id
        user_id = user.id

        async def generate():
            yield sse_event(
                "chat",
                {"chat_id": chat_id_str, "message_id": new_msg_id, "run_id": str(run_id)},
            )

            orchestrator = StreamOrchestrator(
                messages=list(history),
                model=effective_model,
                base_url="",
                api_key=api_key,
                tool_gating_enabled=tool_gating_enabled,
                search_enabled=search_enabled,
                search_mode=False,
                sandbox_available=sandbox_manager.available,
                loaded_skills=set(),
                supports_tools=model_supports_tools,
                context_length=model_info.get("context_length", 0),
            )

            full_content = ""
            full_reasoning = ""
            last_usage = None
            tool_executions: list[dict] = []
            search_images: list[dict] = []

            async for sse_frame in orchestrator.run(
                chat_id=chat_id_str, user_id=user_id, max_rounds=12
            ):
                ev_type, data = _parse_sse_frame(sse_frame)
                if ev_type == "content":
                    full_content += data.get("text", "")
                elif ev_type == "reasoning":
                    full_reasoning += data.get("text", "")
                elif ev_type == "usage":
                    last_usage = _accumulate_usage(last_usage, data)
                elif ev_type == "tool_executing":
                    tool_executions.append(
                        {
                            "id": data.get("id"),
                            "name": data.get("name"),
                            "arguments": data.get("arguments"),
                            "status": "running",
                        }
                    )
                elif ev_type == "tool_result":
                    result = data.get("result")
                    try:
                        result = json.loads(result) if isinstance(result, str) else result
                    except json.JSONDecodeError:
                        pass
                    for execution in tool_executions:
                        if execution.get("id") == data.get("id"):
                            execution.update({"result": result, "status": data.get("status", "completed")})
                            break
                elif ev_type == "search_images":
                    incoming = data.get("images") or []
                    if not data.get("append"):
                        search_images = list(incoming)
                    else:
                        known = {item.get("img_src") for item in search_images}
                        search_images.extend(
                            item for item in incoming if item.get("img_src") not in known
                        )
                    search_images = search_images[:10]
                elif ev_type == "error":
                    yield sse_frame
                    if full_content:
                        await save_assistant_message(
                            new_msg_id, chat_id_str, user_id,
                            full_content, effective_model, last_usage,
                            reasoning=full_reasoning,
                            tool_executions=tool_executions,
                            search_images=search_images,
                        )
                    return
                yield sse_frame

            if not full_content and full_reasoning:
                full_content = full_reasoning
                full_reasoning = ""
                yield sse_event("content", {"text": full_content})

            if last_usage:
                await fetch_generation_cost(api_key, last_usage)

            if full_content:
                await save_assistant_message(
                    new_msg_id, chat_id_str, user_id,
                    full_content, effective_model, last_usage, reasoning=full_reasoning,
                    tool_executions=tool_executions,
                    search_images=search_images,
                )
                from quip.services.telegram_notify import notify_telegram_chat

                asyncio.create_task(notify_telegram_chat(chat, full_content, request))

            yield sse_event("done", {})

        async def tracked_generate():
            error_message = None
            terminal = False
            try:
                async for frame in generate():
                    event_type, event_data = _parse_sse_frame(frame)
                    if event_type == "error":
                        error_message = str(event_data.get("error") or event_data.get("message") or "Generation failed")
                    yield frame
                if error_message:
                    await _set_run_status(run_id, "failed", error_message, db)
                else:
                    await _set_run_status(run_id, "completed", db=db)
                terminal = True
            except asyncio.CancelledError:
                await _set_run_status(run_id, "cancelled", "Client disconnected", db)
                terminal = True
                raise
            except Exception as exc:
                logger.exception("Regeneration run %s failed", run_id)
                await _set_run_status(run_id, "failed", str(exc), db)
                terminal = True
                yield sse_event("error", {"error": "Generation failed"})
            finally:
                if not terminal:
                    await _set_run_status(run_id, "cancelled", "Stream closed before completion", db)

        return StreamingResponse(
            tracked_generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
