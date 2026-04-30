"""Top-level completion service — orchestrates chat & regenerate flows."""
import json
import logging
from decimal import Decimal
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import async_session
from quip.models.user import User
from quip.models.chat import Chat, Message
from quip.models.usage import UsageLog
from quip.models.budget import Budget
from quip.models.file import File, DocumentChunk
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.core.config import get_setting, get_bool_setting
from quip.services.sandbox import sandbox_manager
from quip.services.multimodal import build_multimodal_message
from quip.services.streaming import is_ollama_model, sse_event
from quip.services.messages_persist import save_assistant_message
from quip.services.title import generate_title
from quip.services.completion.history import HistoryService
from quip.services.completion.prompt import PromptBuilder
from quip.services.completion.stream import StreamOrchestrator, fetch_generation_cost
from quip.services.skill_store import get_skill as get_skill_by_name

logger = logging.getLogger(__name__)

UPLOAD_DIR = None


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
            now = datetime.now(timezone.utc)
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


async def _load_attachments(file_ids: list[UUID], db: AsyncSession) -> list[dict]:
    if not file_ids:
        return []
    result = await db.execute(select(File).where(File.id.in_(file_ids)))
    files = result.scalars().all()
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

        is_ollama = is_ollama_model(req.model)
        await _check_budget(user, db)

        if is_ollama:
            ollama_url = get_setting("ollama_url", "http://localhost:11434")
        else:
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
        else:
            is_new_chat = True
            title = req.message[:50] + ("..." if len(req.message) > 50 else "")
            chat = Chat(user_id=user.id, title=title, model=req.model)
            db.add(chat)
            await db.flush()

        user_parent_id = await CompletionService.determine_parent(
            db, chat, req.branch_from_message_id
        )

        attachments = await _load_attachments(req.file_ids, db) if req.file_ids else []
        await _copy_attachments_to_sandbox(user, chat, attachments, db)

        if attachments and chat:
            file_ids_to_link = [UUID(att["file_id"]) for att in attachments]
            await db.execute(
                update(File)
                .where(File.id.in_(file_ids_to_link), File.chat_id.is_(None))
                .values(chat_id=chat.id)
            )
            await db.execute(
                update(DocumentChunk)
                .where(DocumentChunk.file_id.in_(file_ids_to_link), DocumentChunk.chat_id.is_(None))
                .values(chat_id=chat.id)
            )

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
            messages_for_history, file_path_map, is_ollama, db
        )

        search_enabled = get_bool_setting("search_enabled", False)
        search_mode = req.mode_hint == "search" and search_enabled
        effective_model = PromptBuilder.resolve_model(
            req.model, search_mode=search_mode, deep_research=req.deep_research
        )
        tool_gating_enabled = get_bool_setting("tool_gating_enabled", True)
        locale, location = PromptBuilder.resolve_runtime_context(request, user)
        system_prompt = PromptBuilder.build(
            tool_gating_enabled=tool_gating_enabled,
            locale=locale, location=location,
            search_enabled=search_enabled, search_mode=search_mode,
            sandbox_available=sandbox_manager.available,
        )
        system_prompt = await PromptBuilder.inject_rag(
            system_prompt, req.message, chat.id, inlined_doc_file_ids, db
        )
        if system_prompt:
            history.insert(0, {"role": "system", "content": system_prompt})

        assistant_msg = Message(
            chat_id=chat.id, role="assistant", content="",
            model=req.model, parent_id=user_msg.id,
        )
        db.add(assistant_msg)
        await db.flush()
        await db.commit()

        chat_id_str = str(chat.id)
        user_msg_id = str(user_msg.id)
        assistant_msg_id = str(assistant_msg.id)
        user_id = user.id
        user_parent_id_str = str(user_msg.parent_id) if user_msg.parent_id else None

        async def generate():
            full_content = ""
            full_reasoning = ""
            last_usage = None

            yield sse_event("chat", {
                "chat_id": chat_id_str,
                "user_message_id": user_msg_id,
                "message_id": assistant_msg_id,
                "user_parent_id": user_parent_id_str,
            })

            # Deep Research mode
            if req.deep_research and search_enabled and get_bool_setting("research_enabled", True):
                async for sse_frame in StreamOrchestrator.run_deep_research_stream(
                    query=req.message,
                    model=effective_model,
                    api_key=api_key if not is_ollama else "",
                    ollama_url=ollama_url if is_ollama else "",
                    locale=locale, location=location,
                    is_ollama=is_ollama,
                ):
                    ev_type, data = _parse_sse_frame(sse_frame)
                    if ev_type == "content":
                        full_content += data.get("text", "")
                    elif ev_type == "reasoning":
                        full_reasoning += data.get("text", "")
                    elif ev_type == "usage":
                        last_usage = data
                    yield sse_frame
            else:
                # Normal mode via StreamOrchestrator
                orchestrator = StreamOrchestrator(
                    messages=list(history),
                    model=effective_model,
                    base_url=ollama_url if is_ollama else "",
                    api_key=api_key if not is_ollama else "",
                    tool_gating_enabled=tool_gating_enabled,
                    search_enabled=search_enabled,
                    search_mode=search_mode,
                    sandbox_available=sandbox_manager.available,
                    loaded_skills=set(),
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
                        last_usage = data
                    elif ev_type == "error":
                        yield sse_frame
                        if full_content:
                            await save_assistant_message(
                                assistant_msg_id, chat_id_str, user_id,
                                full_content, req.model, last_usage,
                                reasoning=full_reasoning,
                            )
                        return
                    yield sse_frame

            if not full_content and full_reasoning:
                full_content = full_reasoning
                full_reasoning = ""
                yield sse_event("content", {"text": full_content})

            # Cost fetch for OpenRouter
            if not is_ollama and last_usage:
                await fetch_generation_cost(is_ollama, api_key, last_usage)

            if full_content:
                await save_assistant_message(
                    assistant_msg_id, chat_id_str, user_id,
                    full_content, req.model, last_usage, reasoning=full_reasoning,
                )

            if is_new_chat:
                _title_model = get_setting("title_model", "")
                if _title_model:
                    new_title = await generate_title(
                        req.message, _title_model, get_setting("openrouter_api_key", "")
                    )
                    if new_title:
                        async with async_session() as _tdb:
                            _chat = await _tdb.get(Chat, chat.id)
                            if _chat:
                                _chat.title = new_title[:200]
                                await _tdb.commit()
                        yield sse_event("title", {"title": new_title})

            yield sse_event("done", {})

        return StreamingResponse(
            generate(),
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

        result = await db.execute(
            select(Message).where(Message.id == req.message_id, Message.chat_id == req.chat_id)
        )
        orig_msg = result.scalar_one_or_none()
        if not orig_msg or orig_msg.role != "assistant":
            raise HTTPException(
                status_code=400, detail="Message not found or not an assistant message"
            )

        model = req.model or orig_msg.model or chat.model or "anthropic/claude-sonnet-4"
        is_ollama = is_ollama_model(model)

        if is_ollama:
            ollama_url = get_setting("ollama_url", "http://localhost:11434")
        else:
            api_key = get_setting("openrouter_api_key")
            if not api_key:
                raise HTTPException(
                    status_code=400, detail="No OpenRouter API key configured."
                )

        chain, file_path_map = await HistoryService.build_for_regenerate(db, chat, orig_msg)
        history, _ = await _build_history_dicts(chain, file_path_map, is_ollama, db)

        search_enabled = get_bool_setting("search_enabled", False)
        tool_gating_enabled = get_bool_setting("tool_gating_enabled", True)
        regen_locale, regen_location = PromptBuilder.resolve_runtime_context(request, user)
        system_prompt = PromptBuilder.build(
            tool_gating_enabled=tool_gating_enabled,
            locale=regen_locale, location=regen_location,
            search_enabled=search_enabled, search_mode=False,
            sandbox_available=sandbox_manager.available,
        )
        # Inject RAG context using the last user message in the chain
        last_user_msg = next((m.content for m in reversed(chain) if m.role == "user"), "")
        if last_user_msg:
            system_prompt = await PromptBuilder.inject_rag(
                system_prompt, last_user_msg, chat.id, set(), db
            )
        if system_prompt:
            history.insert(0, {"role": "system", "content": system_prompt})

        new_msg = Message(
            chat_id=chat.id, role="assistant", content="",
            model=model, parent_id=orig_msg.parent_id,
        )
        db.add(new_msg)
        await db.flush()
        await db.commit()

        chat_id_str = str(chat.id)
        new_msg_id = str(new_msg.id)
        user_id = user.id

        async def generate():
            yield sse_event("chat", {"chat_id": chat_id_str, "message_id": new_msg_id})

            orchestrator = StreamOrchestrator(
                messages=list(history),
                model=model,
                base_url=ollama_url if is_ollama else "",
                api_key=api_key if not is_ollama else "",
                tool_gating_enabled=tool_gating_enabled,
                search_enabled=search_enabled,
                search_mode=False,
                sandbox_available=sandbox_manager.available,
                loaded_skills=set(),
            )

            full_content = ""
            full_reasoning = ""
            last_usage = None

            async for sse_frame in orchestrator.run(
                chat_id=chat_id_str, user_id=user_id, max_rounds=12
            ):
                ev_type, data = _parse_sse_frame(sse_frame)
                if ev_type == "content":
                    full_content += data.get("text", "")
                elif ev_type == "reasoning":
                    full_reasoning += data.get("text", "")
                elif ev_type == "usage":
                    last_usage = data
                elif ev_type == "error":
                    yield sse_frame
                    if full_content:
                        await save_assistant_message(
                            new_msg_id, chat_id_str, user_id,
                            full_content, model, last_usage,
                            reasoning=full_reasoning,
                        )
                    return
                yield sse_frame

            if not full_content and full_reasoning:
                full_content = full_reasoning
                full_reasoning = ""
                yield sse_event("content", {"text": full_content})

            if not is_ollama and last_usage:
                await fetch_generation_cost(is_ollama, api_key, last_usage)

            if full_content:
                await save_assistant_message(
                    new_msg_id, chat_id_str, user_id,
                    full_content, model, last_usage, reasoning=full_reasoning,
                )

            yield sse_event("done", {})

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
