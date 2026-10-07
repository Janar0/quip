"""HTTP completion lifecycle: prepare, admit, stream and track the durable run."""

import asyncio
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting, get_setting
from quip.database import async_session
from quip.models.chat import Chat, ChatRun, Message
from quip.models.user import User
from quip.routers.models import get_cached_model, get_default_model
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.services.completion.admission import admit_chat_turn
from quip.services.completion.attachments import copy_attachments_to_sandbox
from quip.services.completion.history import HistoryService
from quip.services.completion.preparation import (
    _build_history_dicts,
    _load_attachments,
    _resolve_model,
    _truncate_history,
    _validate_model,
    check_budget,
    determine_parent,
    load_chat_workspace,
    prepare_prompt,
)
from quip.services.completion.prompt import PromptBuilder
from quip.services.completion.results import (
    StreamResult,
    _accumulate_usage,
    _parse_sse_frame,
)
from quip.services.completion.stream import StreamOrchestrator
from quip.services.messages_persist import save_assistant_message
from quip.services.sandbox import sandbox_manager
from quip.services.skill_store import get_skill as get_skill_by_name
from quip.services.streaming import sse_event
from quip.services.title import generate_chat_identity, is_implicit_chat_title

__all__ = [
    "_build_history_dicts",
    "_check_budget",
    "_load_attachments",
    "_resolve_model",
    "_truncate_history",
    "_validate_model",
    "PromptBuilder",
    "_accumulate_usage",
    "_parse_sse_frame",
    "CompletionService",
]

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
    # Voice and completion share the facade's session-factory override.
    await check_budget(user, db, session_factory=async_session)


async def _copy_attachments_to_sandbox(user, chat, attachments, db):
    return await copy_attachments_to_sandbox(
        user,
        chat,
        attachments,
        db,
        sandbox_manager=sandbox_manager,
        get_skill_by_name=get_skill_by_name,
        get_upload_dir=_get_upload_dir,
    )


def _stream_response(frames):
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _tracked_generate(frames, run_id, db):
    error_message = None
    terminal = False
    try:
        async for frame in frames:
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


async def _generate(prompt, *, chat_event, chat, user, request, identity_query=None):
    yield sse_event("chat", chat_event)
    orchestrator = StreamOrchestrator(
        messages=list(prompt.history),
        model=prompt.model,
        base_url=get_setting("ollama_url", "http://localhost:11434"),
        api_key=prompt.api_key,
        tool_gating_enabled=prompt.tool_gating_enabled,
        search_enabled=prompt.search_enabled,
        search_mode=prompt.search_mode,
        sandbox_available=sandbox_manager.available,
        loaded_skills=set(),
        supports_tools=prompt.model_info.get("supports_tools", True),
        context_length=prompt.model_info.get("context_length", 0),
    )
    result = StreamResult()
    frames = orchestrator.run(chat_id=str(chat.id), user_id=user.id, max_rounds=8 if prompt.search_mode else 12)
    async for frame in result.stream(
        frames,
        prompt=prompt,
        save=save_assistant_message,
        message_id=chat_event["message_id"],
        chat_id=str(chat.id),
        user_id=user.id,
    ):
        yield frame
    if result.failed:
        return
    if result.content:
        from quip.services.telegram_notify import notify_telegram_chat

        asyncio.create_task(notify_telegram_chat(chat, result.content, request))
    if identity_query is not None:
        async for frame in _generate_identity(chat, identity_query, prompt.model):
            yield frame
    yield sse_event("done", {})


async def _generate_identity(chat, query, effective_model):
    identity_model = get_setting("title_model", "") or effective_model
    identity = await generate_chat_identity(query, identity_model, get_setting("openrouter_api_key", ""))
    if identity:
        new_title, emoji = identity
        async with async_session() as db:
            saved_chat = await db.get(Chat, chat.id)
            if saved_chat:
                saved_chat.title = new_title[:200]
                saved_chat.meta = {**(saved_chat.meta or {}), "emoji": emoji, "telegram_topic_implicit": False}
                await db.commit()
        yield sse_event("title", {"title": new_title, "emoji": emoji})


async def _research_response(
    *,
    research_manager,
    req,
    prompt,
    chat,
    assistant_msg,
    run_id,
    user_id,
    chat_id_str,
    user_msg_id,
    assistant_msg_id,
    user_parent_id_str,
):
    from quip.services.chat_runs import ChatRunSpec
    from quip.services.research.limits import ResearchLimits
    from quip.services.research.run_manager import ResearchRunSpec

    limits = ResearchLimits.from_config()
    task_spec = ResearchRunSpec(
        run=ChatRunSpec(
            run_id=run_id,
            chat_id=chat.id,
            user_id=user_id,
            assistant_message_id=assistant_msg.id,
            task_kind="research",
            timeout_seconds=limits.max_runtime_seconds,
        ),
        query=req.message,
        model=prompt.model,
        api_key=prompt.api_key,
        is_ollama=prompt.is_ollama,
        ollama_url=get_setting("ollama_url", "http://localhost:11434"),
        locale=prompt.locale,
        location=prompt.location,
    )
    try:
        subscription = await research_manager.start(task_spec)
    except RuntimeError as exc:
        await _set_run_status(run_id, "failed", str(exc))
        raise HTTPException(status_code=503, detail="Deep Research runner is unavailable") from exc

    async def relay_research():
        try:
            yield sse_event(
                "chat",
                {
                    "chat_id": chat_id_str,
                    "user_message_id": user_msg_id,
                    "message_id": assistant_msg_id,
                    "run_id": str(run_id),
                    "task_kind": "research",
                    "user_parent_id": user_parent_id_str,
                },
            )
            async for event in subscription:
                yield sse_event(event["type"], event.get("data", {}))
        finally:
            # Closing the HTTP stream only detaches this listener; the task manager owns execution.
            await subscription.aclose()

    return _stream_response(relay_research())


class CompletionService:
    determine_parent = staticmethod(determine_parent)

    @staticmethod
    async def stream_selected_model(
        messages: list[dict],
        model_id: str,
        *,
        tools: list[dict],
        max_tokens: int = 1_200,
    ):
        """Stream one tool-enabled round through Quip's selected provider seam.

        Internal long-running workers use this instead of reimplementing
        OpenRouter/Ollama routing or creating a second ChatRun/message pair.
        The task owner supplies an explicit, bounded tool list.
        """

        effective_model = _resolve_model(model_id)
        if effective_model != model_id:
            raise HTTPException(status_code=409, detail="Selected model changed")
        model_info = get_cached_model(effective_model)
        if not model_info:
            raise HTTPException(status_code=503, detail="Selected text model is no longer in the catalog")
        if model_info.get("supports_tools") is False:
            raise HTTPException(status_code=503, detail="Selected text model does not support tool calling")

        is_ollama = effective_model.startswith("ollama/")
        api_key = get_setting("openrouter_api_key")
        if not is_ollama and not api_key:
            raise HTTPException(status_code=503, detail="OpenRouter is not configured")

        orchestrator = StreamOrchestrator(
            messages=messages,
            model=effective_model,
            base_url=get_setting("ollama_url", "http://localhost:11434"),
            api_key=api_key,
            tool_gating_enabled=False,
            search_enabled=True,
            search_mode=False,
            sandbox_available=False,
            loaded_skills=set(),
            supports_tools=True,
            context_length=model_info.get("context_length", 0),
            max_tokens=max(64, min(int(max_tokens), 1_200)),
        )
        async for item in orchestrator.stream_with_tools(tools):
            yield item

    @staticmethod
    async def chat_completion(req: CompletionRequest, request, user: User, db: AsyncSession):

        research_mode = req.mode_hint == "research"
        research_manager = None
        if research_mode:
            if not get_bool_setting("research_enabled", False):
                raise HTTPException(status_code=403, detail="Deep Research is disabled by an administrator")
            runner_mode = get_setting("research_runner_mode", "disabled").strip().lower()
            research_manager = getattr(request.app.state, "research_run_manager", None)
            if runner_mode != "single_process" or research_manager is None:
                raise HTTPException(status_code=503, detail="Deep Research runner is not enabled")

        await _check_budget(user, db)

        is_new_chat = not req.chat_id
        chat, workspace = await load_chat_workspace(req, user, db)

        # Personal-workspace adoption can issue UPDATEs even when it changes no
        # rows. Finish that short transaction before document extraction.
        await db.commit()

        user_parent_id = await CompletionService.determine_parent(db, chat, req.branch_from_message_id)

        attachments = (
            await _load_attachments(req.file_ids, user.id, chat.id, chat.workspace_id, db) if req.file_ids else []
        )

        user_meta = {}
        if attachments:
            user_meta["attachments"] = [{k: v for k, v in a.items() if k != "storage_path"} for a in attachments]
        user_msg = Message(
            id=uuid4(),
            chat_id=chat.id,
            role="user",
            content=req.message,
            parent_id=user_parent_id,
            meta=user_meta or None,
        )

        messages_for_history, file_path_map = await HistoryService.build(db, chat, req.branch_from_message_id, user_msg)
        search_enabled = get_bool_setting("search_enabled", False)
        search_mode = req.mode_hint == "search" and search_enabled
        prompt = await prepare_prompt(
            chain=messages_for_history,
            file_path_map=file_path_map,
            model=req.model or workspace.default_model or chat.model or "",
            search_mode=search_mode,
            query=req.message,
            request=request,
            user=user,
            chat=chat,
            workspace=workspace,
            db=db,
        )
        assistant_msg, run, attachments = await admit_chat_turn(
            req=req,
            user=user,
            chat=chat,
            user_msg=user_msg,
            attachments=attachments,
            is_new_chat=is_new_chat,
            user_parent_id=user_parent_id,
            effective_model=prompt.model,
            research_mode=research_mode,
            db=db,
        )

        await _copy_attachments_to_sandbox(user, chat, attachments, db)

        chat_id_str = str(chat.id)
        user_msg_id = str(user_msg.id)
        assistant_msg_id = str(assistant_msg.id)
        run_id = run.id
        user_id = user.id
        user_parent_id_str = str(user_msg.parent_id) if user_msg.parent_id else None

        if research_mode:
            return await _research_response(
                research_manager=research_manager,
                req=req,
                prompt=prompt,
                chat=chat,
                assistant_msg=assistant_msg,
                run_id=run_id,
                user_id=user_id,
                chat_id_str=chat_id_str,
                user_msg_id=user_msg_id,
                assistant_msg_id=assistant_msg_id,
                user_parent_id_str=user_parent_id_str,
            )

        telegram_topic_implicit = (chat.meta or {}).get("telegram_topic_implicit")
        should_generate_telegram_title = chat.source == "telegram" and (
            telegram_topic_implicit
            if "telegram_topic_implicit" in (chat.meta or {})
            else is_implicit_chat_title(chat.title)
        )
        frames = _generate(
            prompt,
            chat=chat,
            user=user,
            request=request,
            identity_query=req.message if is_new_chat or should_generate_telegram_title else None,
            chat_event={
                "chat_id": chat_id_str,
                "user_message_id": user_msg_id,
                "message_id": assistant_msg_id,
                "run_id": str(run_id),
                "task_kind": "chat",
                "user_parent_id": user_parent_id_str,
            },
        )
        return _stream_response(_tracked_generate(frames, run_id, db))

    @staticmethod
    async def regenerate(req: RegenerateRequest, request, user: User, db: AsyncSession):

        await _check_budget(user, db)

        chat, workspace = await load_chat_workspace(req, user, db)

        result = await db.execute(select(Message).where(Message.id == req.message_id, Message.chat_id == req.chat_id))
        orig_msg = result.scalar_one_or_none()
        if not orig_msg or orig_msg.role != "assistant":
            raise HTTPException(status_code=400, detail="Message not found or not an assistant message")

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
        chain, file_path_map = await HistoryService.build_for_regenerate(db, chat, orig_msg)
        last_user_msg = next((m.content for m in reversed(chain) if m.role == "user"), "")
        prompt = await prepare_prompt(
            chain=chain,
            file_path_map=file_path_map,
            model=raw_model,
            search_mode=False,
            query=last_user_msg,
            request=request,
            user=user,
            chat=chat,
            workspace=workspace,
            db=db,
            regenerate=True,
        )

        new_msg = Message(
            chat_id=chat.id,
            role="assistant",
            content="",
            model=prompt.model,
            parent_id=orig_msg.parent_id,
        )
        db.add(new_msg)
        await db.flush()
        run = ChatRun(
            chat_id=chat.id,
            user_id=user.id,
            assistant_message_id=new_msg.id,
            status="running",
            model=prompt.model,
            started_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()
        await db.commit()

        chat_id_str = str(chat.id)
        new_msg_id = str(new_msg.id)
        run_id = run.id
        frames = _generate(
            prompt,
            chat=chat,
            user=user,
            request=request,
            chat_event={"chat_id": chat_id_str, "message_id": new_msg_id, "run_id": str(run_id), "task_kind": "chat"},
        )
        return _stream_response(_tracked_generate(frames, run_id, db))
