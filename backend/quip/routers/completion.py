"""SSE streaming endpoint for chat completions — routes to OpenRouter or Ollama."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from quip.database import get_db, async_session
from quip.models.user import User
from quip.models.chat import Chat, Message
from quip.models.usage import UsageLog
from quip.models.budget import Budget
from quip.schemas.chat import CompletionRequest, RegenerateRequest
from quip.services.permissions import get_current_user
from quip.services.config import get_setting
from quip.providers import openrouter, ollama
from quip.services.artifacts import extract_artifacts
from quip.services.sandbox import sandbox_manager
from quip.models.file import File, DocumentChunk
from quip.services.rag import retrieve_context, format_rag_context
from quip.services.tools import (
    LOAD_SKILL_TOOL,
    WIDGET_TOOL,
    READ_URL_TOOL,
    GENERATE_IMAGE_TOOL,
    SANDBOX_TOOLS,
    SEARCH_TOOLS,
    AccumulatedToolCall,
    accumulate_tool_calls,
    execute_tool_call,
)
from quip.services.skill_store import list_skill_index, get_skill
from quip.services.geo import client_ip, resolve, format_location
from quip.services.research import run_deep_research, ResearchEvent

logger = logging.getLogger(__name__)

ARTIFACT_SKILL_NAMES = (
    "artifact_plot",
    "artifact_chart",
    "artifact_table",
    "artifact_mermaid",
    "artifact_code",
    "artifact_svg",
    "artifact_html",
)


def _parse_accept_language(request: Request) -> Optional[str]:
    """Pull the primary language subtag from the Accept-Language header."""
    header = request.headers.get("accept-language", "")
    if not header:
        return None
    first = header.split(",")[0].split(";")[0].strip()
    if not first:
        return None
    return first.split("-")[0]


def _build_base_prompt(
    enabled_skills: set[str],
    locale: Optional[str] = None,
    location: Optional[str] = None,
) -> str:
    """Assemble the minimal system prompt shown to the model by default.

    Contains a role line, runtime context (date, locale, coarse location),
    a skill index (names + one-liners), and the admin-configured system
    prompt suffix. Detailed capability instructions live in
    `services/skills.py` and are fetched on demand via the `load_skill`
    tool — keeping the default payload small.
    """
    parts: list[str] = [
        "You are QUIP, a helpful AI assistant. "
        "You have named skills you can load on demand with the `load_skill` tool. "
        "When you need details for a capability you don't remember (e.g. how to "
        "format a plot artifact, how to use the sandbox, or the web search "
        "answer style), call `load_skill` with its name before using it. "
        "When the user's message contains an http/https URL, call `read_url` on it "
        "to fetch its content before answering."
    ]

    rt_lines = [f"Current date: {datetime.now(timezone.utc).date().isoformat()}."]
    if locale:
        rt_lines.append(
            f"User interface language: {locale}. Answer in this language unless the user writes in another."
        )
    if location:
        rt_lines.append(
            f"Approximate user location: {location}. Use local units, currency, and conventions when relevant."
        )
    parts.append("\n".join(rt_lines))

    # Fast search: inject full skill body directly — avoids lazy load_skill round-trip
    # that causes some models (e.g. Gemini) to stall after calling load_skill.
    if "fast_search" in enabled_skills:
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
            "SEARCH CITATION RULE: Whenever you use web_search or read_url, you MUST cite every "
            "claim inline with [1], [2], etc. and append a Sources block at the end:\n"
            "---\n"
            "**Sources:**\n"
            "[1] Title - URL\n"
            "[2] Title - URL\n"
            "Translate the 'Sources:' label into the user's language (e.g. 'Источники:' for Russian). "
            "Never fabricate URLs or data — only present what the search actually returned."
        )

    admin = get_setting("system_prompt", "").strip()
    if admin:
        parts.append(admin)

    return "\n\n".join(parts)


def _resolve_runtime_context(request: Request, user: User) -> tuple[Optional[str], Optional[str]]:
    """Return (locale, location) for the current request.

    Locale precedence: user.settings.locale > Accept-Language primary tag > None.
    Location is best-effort — None when the IP is private, the DB is missing,
    or the lookup fails.
    """
    user_settings = user.settings or {}
    locale = user_settings.get("locale") or _parse_accept_language(request)
    ip = client_ip(request)
    location = format_location(resolve(ip)) if ip else None
    return locale, location

router = APIRouter(prefix="/api", tags=["completion"])


async def _load_attachments(file_ids: list[UUID], db: AsyncSession) -> list[dict]:
    """Load file records and return attachment metadata."""
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
    user: User,
    chat: Chat,
    attachments: list[dict],
    db: AsyncSession,
) -> None:
    """Copy uploaded files into the sandbox workspace so the LLM tools can see them."""
    if not attachments:
        return
    if get_setting("sandbox_enabled", "false") != "true":
        return
    if not sandbox_manager.available:
        return

    from quip.routers.files import UPLOAD_DIR

    # Reuse the caller's session — SQLite only permits one writer at a time,
    # so opening a parallel async_session() here deadlocks against the outer
    # request's pending flush. get_or_create will commit on this session,
    # which also persists any earlier pending writes (chat row, etc.) — safe
    # because at this call site we've only added rows we're happy to keep.
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
        host_path = UPLOAD_DIR / storage_path
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


_VIDEO_URL_PATTERNS = [
    r'https?://(?:www\.)?youtube\.com/watch\S+',
    r'https?://youtu\.be/\S+',
    r'https?://(?:www\.)?rutube\.ru/video/\S+',
    r'https?://(?:www\.)?vk\.com/video\S+',
    r'https?://vkvideo\.ru/\S+',
]


def _extract_video_urls(text: str) -> tuple[str, list[str]]:
    """Extract video URLs from text. Returns (cleaned_text, [urls])."""
    import re
    urls = []
    for pattern in _VIDEO_URL_PATTERNS:
        for match in re.findall(pattern, text):
            urls.append(match)
            text = text.replace(match, '')
    return text.strip(), urls


def _build_multimodal_message(msg: dict, attachments: list[dict], is_ollama: bool) -> dict:
    """Transform a message to include image/video content if it has media attachments."""
    from quip.routers.files import UPLOAD_DIR
    import base64

    image_attachments = [a for a in attachments if a.get("file_type") == "image"]
    video_attachments = [a for a in attachments if a.get("file_type") == "video"]
    text = msg.get("content", "")

    # Extract video URLs from message text
    text, video_urls = _extract_video_urls(text)

    has_media = image_attachments or video_attachments or video_urls
    logger.debug(f"_build_multimodal: {len(image_attachments)} images, {len(video_attachments)} videos, {len(video_urls)} urls")

    if not has_media:
        return msg

    if is_ollama:
        # Ollama only supports images
        images = []
        for att in image_attachments:
            storage_path = att.get("storage_path", "")
            if storage_path:
                full_path = UPLOAD_DIR / storage_path
                if full_path.exists():
                    data = full_path.read_bytes()
                    images.append(base64.b64encode(data).decode())
        if images:
            return {**msg, "content": text or msg.get("content", ""), "images": images}
        return msg
    else:
        # OpenRouter / OpenAI format: content as array
        content_parts = []
        # Append file URL hints so the model can reference uploaded images in generate_image calls
        text_with_hints = text
        if image_attachments:
            url_hints = [f"/api/files/{att['file_id']}" for att in image_attachments if att.get("file_id")]
            if url_hints:
                text_with_hints = (text + "\n[Uploaded image URLs: " + ", ".join(url_hints) + "]").strip()
        if text_with_hints:
            content_parts.append({"type": "text", "text": text_with_hints})
        for att in image_attachments:
            storage_path = att.get("storage_path", "")
            if storage_path:
                full_path = UPLOAD_DIR / storage_path
                logger.debug(f"Image: {full_path.name} exists={full_path.exists()}")
                if full_path.exists():
                    data = full_path.read_bytes()
                    b64 = base64.b64encode(data).decode()
                    mime = att.get("content_type", "image/png")
                    content_parts.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    })
        for att in video_attachments:
            storage_path = att.get("storage_path", "")
            if storage_path:
                full_path = UPLOAD_DIR / storage_path
                if full_path.exists():
                    data = full_path.read_bytes()
                    b64 = base64.b64encode(data).decode()
                    mime = att.get("content_type", "video/mp4")
                    content_parts.append({
                        "type": "video_url",
                        "video_url": {"url": f"data:{mime};base64,{b64}"},
                    })
        for url in video_urls:
            content_parts.append({
                "type": "video_url",
                "video_url": {"url": url},
            })
        if len(content_parts) > 1 or (content_parts and content_parts[0].get("type") != "text"):
            return {**msg, "content": content_parts}
        return msg


async def _check_budget(user: User, db: AsyncSession) -> None:
    """Raise 429 if user has exceeded their budget (per-user or global).

    Uses a fresh session to guarantee we read the latest committed usage —
    SQLite's SERIALIZABLE isolation can otherwise hide commits from other
    sessions that occurred after the current session opened its transaction.
    """
    async with async_session() as fresh_db:
        # Check per-user budget, then global budget
        for user_filter in [Budget.user_id == user.id, Budget.user_id.is_(None)]:
            result = await fresh_db.execute(select(Budget).where(user_filter))
            budgets = result.scalars().all()
            if not budgets:
                continue

            # Calculate period start
            now = datetime.now(timezone.utc)

            for budget in budgets:
                if not budget or budget.limit_usd <= 0:
                    continue

                if budget.period == "daily":
                    since = now.replace(hour=0, minute=0, second=0, microsecond=0)
                else:  # monthly
                    since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

                # Sum usage in period
                usage_result = await fresh_db.execute(
                    select(func.coalesce(func.sum(UsageLog.cost), 0))
                    .where(UsageLog.user_id == user.id, UsageLog.created_at >= since)
                )
                current_cost = Decimal(str(usage_result.scalar() or 0))

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


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _is_ollama_model(model: str) -> bool:
    return model.startswith("ollama/")


async def _generate_title(message: str, model: str, api_key: str) -> str | None:
    """Generate a short chat title using a cheap model. Returns None on any failure."""
    prompt = (
        f"Write a very short title (3–5 words max) for a conversation that starts with the message below. "
        f"Use the SAME LANGUAGE as the message. Reply with the title only — no quotes, no punctuation.\n\n"
        f"{message[:300]}"
    )
    try:
        async with httpx.AsyncClient(timeout=8) as client:
            if model.startswith("ollama/"):
                ollama_base = get_setting("ollama_url", "http://localhost:11434")
                r = await client.post(
                    f"{ollama_base}/api/chat",
                    json={
                        "model": model.removeprefix("ollama/"),
                        "messages": [{"role": "user", "content": prompt}],
                        "stream": False,
                    },
                )
                if r.is_success:
                    return r.json()["message"]["content"].strip()
            else:
                r = await client.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={"model": model, "messages": [{"role": "user", "content": prompt}]},
                )
                if r.is_success:
                    return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        pass
    return None


async def _save_assistant_message(
    assistant_msg_id: str,
    chat_id: str,
    user_id,
    content: str,
    model: str,
    usage=None,
    reasoning: str = "",
    tool_executions: list[dict] | None = None,
    search_images: list[dict] | None = None,
    subagent_generations: list[str] | None = None,
):
    """Save the completed assistant message to DB in a fresh session."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Message).where(Message.id == UUID(assistant_msg_id))
            )
            msg = result.scalar_one_or_none()
            if msg:
                artifacts, display_content = extract_artifacts(content)
                msg.content = display_content
                if artifacts:
                    msg.artifacts = artifacts
                if tool_executions:
                    msg.tool_calls = tool_executions
                if usage:
                    msg.token_count = usage.prompt_tokens + usage.completion_tokens
                    msg.cost = usage.cost
                    msg.provider = usage.provider
                if reasoning:
                    msg.meta = {**(msg.meta or {}), "reasoning": reasoning}
                if search_images:
                    msg.meta = {**(msg.meta or {}), "search_images": search_images}
                if subagent_generations:
                    msg.meta = {**(msg.meta or {}), "subagent_generations": subagent_generations}
                msg.model = model

            if usage:
                log = UsageLog(
                    user_id=user_id,
                    chat_id=UUID(chat_id),
                    message_id=UUID(assistant_msg_id),
                    model=model,
                    provider=usage.provider,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cached_tokens=usage.cached_tokens,
                    cost=usage.cost,
                    is_byok=usage.is_byok,
                    generation_id=usage.generation_id,
                )
                db.add(log)

            await db.commit()
    except Exception as e:
        logger.error(f"Failed to save assistant message: {e}")


@router.post("/chat/completions")
async def chat_completion(
    req: CompletionRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    is_ollama = _is_ollama_model(req.model)

    # Budget enforcement
    await _check_budget(user, db)

    if is_ollama:
        ollama_url = get_setting("ollama_url", "http://localhost:11434")
    else:
        api_key = get_setting("openrouter_api_key")
        if not api_key:
            raise HTTPException(status_code=400, detail="No OpenRouter API key configured. Add one in Admin > Settings.")

    # Get or create chat
    is_new_chat = False
    if req.chat_id:
        result = await db.execute(select(Chat).where(Chat.id == req.chat_id, Chat.user_id == user.id))
        chat = result.scalar_one_or_none()
        if not chat:
            raise HTTPException(status_code=404, detail="Chat not found")
    else:
        is_new_chat = True
        title = req.message[:50] + ("..." if len(req.message) > 50 else "")
        chat = Chat(user_id=user.id, title=title, model=req.model)
        db.add(chat)
        await db.flush()

    # Determine parent for the new user message
    if req.branch_from_message_id:
        # Branch edit: look up the source message to get its parent_id.
        # The new message becomes a sibling of the source message (same parent, including None for roots).
        source_msg_result = await db.execute(
            select(Message).where(Message.id == req.branch_from_message_id, Message.chat_id == chat.id)
        )
        source_msg = source_msg_result.scalar_one_or_none()
        user_parent_id = source_msg.parent_id if source_msg else None
    else:
        # Normal flow: find the leaf of the active branch.
        # Can't use ORDER BY created_at on SQLite — it has 1-second precision,
        # so a user message and its assistant response (created within the same
        # second) are indistinguishable and ordering becomes non-deterministic.
        # Instead, find the leaf = a message that no other message has as parent.
        all_msgs_result = await db.execute(
            select(Message).where(Message.chat_id == chat.id)
        )
        all_msgs = list(all_msgs_result.scalars().all())
        if all_msgs:
            parent_ids = {m.parent_id for m in all_msgs if m.parent_id is not None}
            leaves = [m for m in all_msgs if m.id not in parent_ids]
            # If there are multiple leaves (branched chat), pick the most recently created.
            # Sub-second ties among leaves are rare because leaves from different branches
            # are typically created seconds apart (user interaction required).
            leaves.sort(key=lambda m: m.created_at)
            user_parent_id = leaves[-1].id if leaves else None
        else:
            user_parent_id = None

    # Load file attachments if provided
    logger.debug(f"Completion: file_ids={req.file_ids}")
    attachments = await _load_attachments(req.file_ids, db) if req.file_ids else []
    logger.debug(f"Loaded {len(attachments)} attachments")

    # Make uploaded files visible to the sandbox so list_files/read_file can see them.
    await _copy_attachments_to_sandbox(user, chat, attachments, db)

    # Link files to chat if uploaded before chat existed, update chunks too
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

    # Save user message (with attachment metadata in meta)
    user_meta = {}
    if attachments:
        # Store without storage_path in meta (that's internal)
        user_meta["attachments"] = [
            {k: v for k, v in a.items() if k != "storage_path"}
            for a in attachments
        ]
    user_msg = Message(
        chat_id=chat.id, role="user", content=req.message,
        parent_id=user_parent_id,
        meta=user_meta or None,
    )
    db.add(user_msg)
    await db.flush()

    # Build message history (with multimodal support for images)
    # For branch edits: walk ancestry chain from user_msg to root (correct branch only).
    # For normal flow: use all messages ordered by created_at (supports legacy chats).
    if req.branch_from_message_id:
        all_msgs_result = await db.execute(
            select(Message).where(Message.chat_id == chat.id)
        )
        id_to_msg = {m.id: m for m in all_msgs_result.scalars().all()}
        chain: list[Message] = []
        curr: Message | None = id_to_msg.get(user_msg.id)
        while curr:
            chain.append(curr)
            curr = id_to_msg.get(curr.parent_id) if curr.parent_id else None
        chain.reverse()
        messages_for_history = chain
    else:
        msg_result = await db.execute(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
        )
        messages_for_history = list(msg_result.scalars().all())

    history = []
    all_history_attachments: list[dict] = []  # all user attachments across history for sandbox sync
    for m in messages_for_history:
        if not m.content:
            continue
        msg_dict = {"role": m.role, "content": m.content}
        # Check for image attachments in message meta
        msg_attachments = (m.meta or {}).get("attachments", [])
        # Add storage_path from DB for image rendering
        if msg_attachments:
            file_ids_in_msg = [UUID(a["file_id"]) for a in msg_attachments if a.get("file_id")]
            if file_ids_in_msg:
                file_result = await db.execute(select(File).where(File.id.in_(file_ids_in_msg)))
                file_map = {str(f.id): f.storage_path for f in file_result.scalars().all()}
                enriched = [{**a, "storage_path": file_map.get(a["file_id"], "")} for a in msg_attachments]
                msg_dict = _build_multimodal_message(msg_dict, enriched, is_ollama)
                if m.role == "user":
                    all_history_attachments.extend(enriched)
        # Inject previously generated image URLs into assistant message content so the model
        # can reference them in follow-up generate_image calls (multi-turn editing).
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

    # Sync all user attachments from conversation history into sandbox workspace (idempotent).
    # This ensures every file the user ever attached is available when the model calls sandbox tools,
    # regardless of which message it came from.
    if all_history_attachments:
        await _copy_attachments_to_sandbox(user, chat, all_history_attachments, db)

    # Fast search mode bypasses normal tool/prompt assembly — only web_search + read_url,
    # Perplexity-style prompt, no artifacts, no sandbox, tighter round budget.
    search_mode = (
        req.mode_hint == "search"
        and get_setting("search_enabled", "false") == "true"
    )

    # Admin can configure cheap model overrides for search/research to reduce cost.
    # chat.model keeps req.model so the UI shows the user's chosen model.
    effective_model = req.model
    if search_mode:
        _sm = get_setting("search_model", "")
        if _sm:
            effective_model = _sm
    elif req.deep_research:
        _rm = get_setting("research_model", "")
        if _rm:
            effective_model = _rm

    # Assemble skill index — the model only sees names + one-liners here.
    # Full bodies arrive on demand via the `load_skill` tool.
    enabled_skills: set[str] = set()
    if search_mode:
        enabled_skills.add("fast_search")
    else:
        if get_setting("search_enabled", "false") == "true":
            enabled_skills.add("web_search")
        if get_setting("artifacts_enabled", "true") == "true":
            enabled_skills.update(ARTIFACT_SKILL_NAMES)
        if get_setting("sandbox_enabled", "false") == "true" and sandbox_manager.available:
            enabled_skills.add("sandbox")
    # Image generation
    if get_setting("image_model", ""):
        enabled_skills.add("image_generation")
    # Add widget skills from skill_store
    from quip.services.skill_store import _skills_cache as _sc
    for _sid, _sk in _sc.items():
        if _sk.enabled and not _sk.is_internal and _sk.category == "widget":
            enabled_skills.add(_sid)

    locale, location = _resolve_runtime_context(request, user)
    system_prompt = _build_base_prompt(enabled_skills, locale=locale, location=location)

    # RAG context injection
    if get_setting("rag_enabled", "true") == "true":
        try:
            rag_chunks = await retrieve_context(req.message, chat.id, db)
            if rag_chunks:
                rag_context = format_rag_context(rag_chunks)
                system_prompt = (system_prompt + "\n\n" + rag_context).strip()
        except Exception as e:
            logger.warning(f"RAG retrieval failed: {e}")

    if system_prompt:
        history.insert(0, {"role": "system", "content": system_prompt})

    # Create placeholder assistant message (child of user message)
    assistant_msg = Message(chat_id=chat.id, role="assistant", content="", model=req.model, parent_id=user_msg.id)
    db.add(assistant_msg)
    await db.flush()
    await db.commit()

    chat_id = str(chat.id)
    user_msg_id = str(user_msg.id)
    assistant_msg_id = str(assistant_msg.id)
    user_id = user.id
    user_parent_id_str = str(user_msg.parent_id) if user_msg.parent_id else None

    # Check if sandbox tools are enabled
    sandbox_enabled = (
        get_setting("sandbox_enabled", "false") == "true"
        and sandbox_manager.available
    )
    tools_for_api: list[dict] = [LOAD_SKILL_TOOL, WIDGET_TOOL, READ_URL_TOOL]
    if get_setting("image_model", ""):
        tools_for_api.append(GENERATE_IMAGE_TOOL)
    if search_mode:
        # Fast search mode — web_search + read_url only, no sandbox/artifacts
        tools_for_api.extend(SEARCH_TOOLS)
    else:
        if sandbox_enabled:
            tools_for_api.extend(SANDBOX_TOOLS)
        if get_setting("search_enabled", "false") == "true":
            tools_for_api.extend(SEARCH_TOOLS)
    tools = tools_for_api
    logger.info("Tools for API: %s", [t["function"]["name"] for t in tools] if tools else None)

    async def generate():
        full_content = ""
        full_reasoning = ""
        last_usage = None
        used_model = req.model
        messages_for_api = list(history)
        sandbox = None
        max_rounds = 3 if search_mode else 12
        all_tool_executions: list[dict] = []
        accumulated_images: dict[str, dict] = {}
        # Per-session cache — repeated load_skill calls for the same name
        # return a cheap "already_loaded" hint instead of repeating the body.
        loaded_skills: set[str] = set()

        yield _sse("chat", {"chat_id": chat_id, "user_message_id": user_msg_id, "message_id": assistant_msg_id, "user_parent_id": user_parent_id_str})

        # --- Deep Research mode ---
        if req.deep_research and get_setting("search_enabled", "false") == "true" and get_setting("research_enabled", "true") == "true":
            queue: asyncio.Queue[ResearchEvent] = asyncio.Queue()

            async def _emit(event: ResearchEvent) -> None:
                await queue.put(event)

            research_kwargs: dict = {
                "query": req.message,
                "emit": _emit,
                "model": effective_model,
                "is_ollama": _is_ollama_model(effective_model),
                "locale": locale,
                "location": location,
            }
            if is_ollama:
                research_kwargs["ollama_url"] = ollama_url
            else:
                research_kwargs["api_key"] = api_key

            task = asyncio.create_task(run_deep_research(**research_kwargs))
            last_usage_data: dict | None = None
            research_subagent_generations: list[str] = []

            def _relay(event: ResearchEvent) -> tuple[str, dict] | None:
                """Map a ResearchEvent to the SSE (name, data) pair to emit."""
                nonlocal last_usage_data
                t = event.type
                if t == "content":
                    return ("content", event.data)
                if t == "reasoning":
                    return ("reasoning", event.data)
                if t == "status":
                    return ("research_status", event.data)
                if t == "usage":
                    last_usage_data = event.data
                    gens = event.data.get("subagent_generations")
                    if isinstance(gens, list):
                        research_subagent_generations.extend(str(g) for g in gens if g)
                    return ("usage", event.data)
                if t == "error":
                    return ("error", event.data)
                if t == "finish":
                    return ("finish", event.data)
                if t in ("subagent_spawned", "subagent_progress", "subagent_result", "subagent_error"):
                    return (t, event.data)
                return None

            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=0.1)
                    except asyncio.TimeoutError:
                        if task.done():
                            while not queue.empty():
                                event = queue.get_nowait()
                                if event.type == "content":
                                    full_content += event.data.get("text", "")
                                elif event.type == "reasoning":
                                    full_reasoning += event.data.get("text", "")
                                relayed = _relay(event)
                                if relayed:
                                    yield _sse(*relayed)
                            break
                        continue

                    if event.type == "content":
                        full_content += event.data.get("text", "")
                    elif event.type == "reasoning":
                        full_reasoning += event.data.get("text", "")
                    elif event.type == "done":
                        break

                    relayed = _relay(event)
                    if relayed:
                        yield _sse(*relayed)

                # Check for task exception
                if task.done() and task.exception():
                    logger.error("Deep research task failed: %s", task.exception())
                    yield _sse("error", {"message": str(task.exception())})
            except Exception as e:
                logger.error("Deep research stream error: %s", e)
                yield _sse("error", {"message": str(e)})

            # If model sent everything as reasoning with no content, promote it
            if not full_content and full_reasoning:
                full_content = full_reasoning
                full_reasoning = ""
                yield _sse("content", {"text": full_content})

            # Reconstruct UsageInfo from event data for saving
            if last_usage_data:
                from quip.providers.openrouter import UsageInfo
                gen_id = last_usage_data.get("generation_id", "")
                last_usage = UsageInfo(
                    prompt_tokens=last_usage_data.get("prompt_tokens", 0),
                    completion_tokens=last_usage_data.get("completion_tokens", 0),
                    cached_tokens=last_usage_data.get("cached_tokens", 0),
                    cost=last_usage_data.get("cost", 0.0),
                    provider=last_usage_data.get("provider", ""),
                    generation_id=gen_id,
                )
                # Fetch cost from OpenRouter generation endpoint if not in stream
                if not is_ollama and gen_id and not last_usage.cost:
                    try:
                        gen = await openrouter.get_generation(gen_id, api_key)
                        if gen:
                            last_usage.cost = gen.get("total_cost", 0.0) or 0.0
                            last_usage.prompt_tokens = last_usage.prompt_tokens or gen.get("native_tokens_prompt", 0)
                            last_usage.completion_tokens = last_usage.completion_tokens or gen.get("native_tokens_completion", 0)
                            last_usage.provider = last_usage.provider or gen.get("provider_name", "")
                    except Exception:
                        pass

            if full_content:
                await _save_assistant_message(
                    assistant_msg_id, chat_id, user_id,
                    full_content, used_model, last_usage,
                    reasoning=full_reasoning,
                    subagent_generations=research_subagent_generations or None,
                )

            yield _sse("done", {})
            return
        # --- End Deep Research mode ---

        for round_num in range(max_rounds):
            round_content = ""
            round_reasoning = ""
            accumulated_tool_calls: list[AccumulatedToolCall] = []

            # Route to the appropriate provider
            if _is_ollama_model(effective_model):
                ollama_model = effective_model.removeprefix("ollama/")
                stream = ollama.stream_completion(
                    messages=messages_for_api,
                    model=ollama_model,
                    base_url=ollama_url,
                    tools=tools,
                )
            else:
                stream = openrouter.stream_completion(
                    messages=messages_for_api,
                    model=effective_model,
                    api_key=api_key,
                    tools=tools,
                )

            async for chunk in stream:
                if chunk.error:
                    yield _sse("error", {"message": chunk.error})
                    if full_content:
                        await _save_assistant_message(
                            assistant_msg_id, chat_id, user_id,
                            full_content, used_model, last_usage,
                            reasoning=full_reasoning,
                        )
                    return

                if chunk.reasoning:
                    round_reasoning += chunk.reasoning
                    yield _sse("reasoning", {"text": chunk.reasoning})

                if chunk.content:
                    round_content += chunk.content
                    yield _sse("content", {"text": chunk.content})

                if chunk.tool_calls:
                    accumulate_tool_calls(accumulated_tool_calls, chunk.tool_calls)

                if chunk.model:
                    used_model = chunk.model

                if chunk.finish_reason:
                    yield _sse("finish", {"reason": chunk.finish_reason})

                if chunk.usage:
                    last_usage = chunk.usage
                    yield _sse("usage", {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "cached_tokens": chunk.usage.cached_tokens,
                        "cost": chunk.usage.cost,
                        "provider": chunk.usage.provider,
                    })

            full_content += round_content
            full_reasoning += round_reasoning

            # No tool calls — we're done
            if not accumulated_tool_calls:
                break

            # --- Tool execution loop ---
            # Append assistant message with tool_calls to API history
            assistant_api_msg: dict = {"role": "assistant"}
            if round_content:
                assistant_api_msg["content"] = round_content
            assistant_api_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function_name,
                        "arguments": tc.function_arguments,
                    },
                }
                for tc in accumulated_tool_calls
            ]
            messages_for_api.append(assistant_api_msg)

            # Get or create sandbox only if a sandbox tool is being called
            _SANDBOX_TOOL_NAMES = {"sandbox_execute", "sandbox_install", "sandbox_write_file", "sandbox_read_file", "sandbox_list_files"}
            if not sandbox and any(tc.function_name in _SANDBOX_TOOL_NAMES for tc in accumulated_tool_calls):
                async with async_session() as sandbox_db:
                    sandbox = await sandbox_manager.get_or_create(user_id, sandbox_db)
                    await sandbox_manager.ensure_chat_dir(sandbox, chat_id)

            # Emit all executing events up-front so the UI shows every call as
            # running in parallel.
            for tc in accumulated_tool_calls:
                yield _sse("tool_executing", {
                    "id": tc.id,
                    "name": tc.function_name,
                    "arguments": tc.function_arguments,
                })

            # Run every tool call concurrently. Each gets its own DB session so
            # transactions don't clash. asyncio.gather preserves input order in
            # results regardless of completion order, so downstream processing
            # (image accumulation, message history append) stays deterministic.
            async def _run_one_tool(tc: AccumulatedToolCall) -> str:
                async with async_session() as tool_db:
                    try:
                        return await execute_tool_call(
                            sandbox_manager, sandbox, chat_id,
                            tc.function_name, tc.function_arguments,
                            db=tool_db,
                            loaded_skills=loaded_skills,
                        )
                    except Exception as e:
                        return json.dumps({"error": f"{type(e).__name__}: {e}"})

            tool_results = await asyncio.gather(
                *(_run_one_tool(tc) for tc in accumulated_tool_calls)
            )

            # Process results in stable order
            for tc, result_str in zip(accumulated_tool_calls, tool_results):
                try:
                    parsed_result = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    parsed_result = {"stdout": str(result_str), "stderr": "", "exit_code": 0, "files_created": []}

                tool_status = "error" if parsed_result.get("error") or parsed_result.get("exit_code", 0) != 0 else "completed"

                yield _sse("tool_result", {
                    "id": tc.id,
                    "name": tc.function_name,
                    "result": result_str,
                    "status": tool_status,
                })

                all_tool_executions.append({
                    "id": tc.id,
                    "name": tc.function_name,
                    "arguments": tc.function_arguments,
                    "status": tool_status,
                    "result": parsed_result,
                })

                if tc.function_name == "web_search" and isinstance(parsed_result, dict):
                    for img in parsed_result.get("images") or []:
                        if not isinstance(img, dict):
                            continue
                        src = img.get("img_src")
                        if src and src not in accumulated_images:
                            accumulated_images[src] = {
                                "img_src": src,
                                "source_url": img.get("source_url") or src,
                                "title": img.get("title") or "",
                            }

                messages_for_api.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result_str,
                })

            # Emit accumulated image snapshot once after the parallel batch so
            # the frontend has URLs before the model streams content with
            # search-image:K markers.
            if search_mode and accumulated_images:
                yield _sse("search_images", {"images": list(accumulated_images.values())[:10]})

            # Continue loop — provider will be called again with tool results

        # If model sent everything as reasoning with no content, promote it
        if not full_content and full_reasoning:
            full_content = full_reasoning
            full_reasoning = ""
            yield _sse("content", {"text": full_content})

        # Fetch cost from generation endpoint if not provided in stream
        if not is_ollama and last_usage and last_usage.generation_id and not last_usage.cost:
            try:
                gen = await openrouter.get_generation(last_usage.generation_id, api_key)
                if gen:
                    last_usage.cost = gen.get("total_cost", 0.0) or 0.0
                    if gen.get("native_tokens_prompt"):
                        last_usage.prompt_tokens = last_usage.prompt_tokens or gen["native_tokens_prompt"]
                    if gen.get("native_tokens_completion"):
                        last_usage.completion_tokens = last_usage.completion_tokens or gen["native_tokens_completion"]
                    last_usage.cached_tokens = last_usage.cached_tokens or gen.get("native_tokens_cached", 0)
                    last_usage.provider = last_usage.provider or gen.get("provider_name", "")
            except Exception:
                pass

        # Emit final image set for the grid before done
        top_images = list(accumulated_images.values())[:10] if (search_mode and accumulated_images) else None
        if top_images:
            yield _sse("search_images", {"images": top_images})

        # Always save after streaming completes
        if full_content:
            await _save_assistant_message(
                assistant_msg_id, chat_id, user_id,
                full_content, used_model, last_usage,
                reasoning=full_reasoning,
                tool_executions=all_tool_executions or None,
                search_images=top_images,
            )

        # AI title generation for new chats
        if is_new_chat:
            _title_model = get_setting("title_model", "")
            if _title_model:
                new_title = await _generate_title(
                    req.message, _title_model, get_setting("openrouter_api_key", "")
                )
                if new_title:
                    async with async_session() as _tdb:
                        _chat = await _tdb.get(Chat, chat.id)
                        if _chat:
                            _chat.title = new_title[:200]
                            await _tdb.commit()
                    yield _sse("title", {"title": new_title})

        yield _sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/chat/regenerate")
async def regenerate_message(
    req: RegenerateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate an assistant message — creates a new sibling response."""
    # Budget enforcement
    await _check_budget(user, db)

    # Verify chat ownership
    result = await db.execute(select(Chat).where(Chat.id == req.chat_id, Chat.user_id == user.id))
    chat = result.scalar_one_or_none()
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Find the original assistant message
    result = await db.execute(select(Message).where(Message.id == req.message_id, Message.chat_id == req.chat_id))
    orig_msg = result.scalar_one_or_none()
    if not orig_msg or orig_msg.role != "assistant":
        raise HTTPException(status_code=400, detail="Message not found or not an assistant message")

    model = req.model or orig_msg.model or chat.model or "anthropic/claude-sonnet-4"
    is_ollama = _is_ollama_model(model)

    if is_ollama:
        ollama_url = get_setting("ollama_url", "http://localhost:11434")
    else:
        api_key = get_setting("openrouter_api_key")
        if not api_key:
            raise HTTPException(status_code=400, detail="No OpenRouter API key configured.")

    # Build history by walking the ancestry chain from orig_msg's parent back to root.
    # Can't use created_at comparisons: SQLite's func.now() has 1-second precision,
    # and siblings/user messages created within the same second would collide.
    # Walking parent_id links gives the exact conversation branch leading to orig_msg.
    all_msgs_result = await db.execute(
        select(Message).where(Message.chat_id == req.chat_id)
    )
    id_to_msg = {m.id: m for m in all_msgs_result.scalars().all()}
    chain: list[Message] = []
    curr: Message | None = id_to_msg.get(orig_msg.parent_id) if orig_msg.parent_id else None
    while curr:
        chain.append(curr)
        curr = id_to_msg.get(curr.parent_id) if curr.parent_id else None
    chain.reverse()

    history = []
    regen_attachments_for_sandbox: list[dict] = []
    for m in chain:
        if not m.content:
            continue
        msg_dict = {"role": m.role, "content": m.content}
        msg_attachments = (m.meta or {}).get("attachments", [])
        if msg_attachments:
            file_ids_in_msg = [UUID(a["file_id"]) for a in msg_attachments if a.get("file_id")]
            if file_ids_in_msg:
                file_result = await db.execute(select(File).where(File.id.in_(file_ids_in_msg)))
                file_map = {str(f.id): f.storage_path for f in file_result.scalars().all()}
                enriched = [{**a, "storage_path": file_map.get(a["file_id"], "")} for a in msg_attachments]
                msg_dict = _build_multimodal_message(msg_dict, enriched, is_ollama)
                if m.role == "user":
                    regen_attachments_for_sandbox.extend(enriched)
        history.append(msg_dict)

    # Re-sync uploaded files into the sandbox workspace (idempotent).
    await _copy_attachments_to_sandbox(user, chat, regen_attachments_for_sandbox, db)

    regen_enabled_skills: set[str] = set()
    if get_setting("search_enabled", "false") == "true":
        regen_enabled_skills.add("web_search")
    if get_setting("artifacts_enabled", "true") == "true":
        regen_enabled_skills.update(ARTIFACT_SKILL_NAMES)
    if get_setting("sandbox_enabled", "false") == "true" and sandbox_manager.available:
        regen_enabled_skills.add("sandbox")
    # Add widget skills from skill_store
    from quip.services.skill_store import _skills_cache as _sc
    for _sid, _sk in _sc.items():
        if _sk.enabled and not _sk.is_internal and _sk.category == "widget":
            regen_enabled_skills.add(_sid)
    regen_locale, regen_location = _resolve_runtime_context(request, user)
    system_prompt = _build_base_prompt(
        regen_enabled_skills, locale=regen_locale, location=regen_location
    )
    if system_prompt:
        history.insert(0, {"role": "system", "content": system_prompt})

    # Create new assistant message (sibling of the original)
    new_msg = Message(
        chat_id=chat.id,
        role="assistant",
        content="",
        model=model,
        parent_id=orig_msg.parent_id,
    )
    db.add(new_msg)
    await db.flush()
    await db.commit()

    chat_id = str(chat.id)
    new_msg_id = str(new_msg.id)
    user_id = user.id

    regen_sandbox_enabled = (
        get_setting("sandbox_enabled", "false") == "true"
        and sandbox_manager.available
    )
    regen_tools_list: list[dict] = [LOAD_SKILL_TOOL, WIDGET_TOOL, READ_URL_TOOL]
    if get_setting("image_model", ""):
        regen_tools_list.append(GENERATE_IMAGE_TOOL)
    if regen_sandbox_enabled:
        regen_tools_list.extend(SANDBOX_TOOLS)
    if get_setting("search_enabled", "false") == "true":
        regen_tools_list.extend(SEARCH_TOOLS)
    regen_tools = regen_tools_list

    async def generate():
        full_content = ""
        full_reasoning = ""
        last_usage = None
        used_model = model
        all_tool_executions: list[dict] = []
        loaded_skills: set[str] = set()
        sandbox = None
        messages_for_api = list(history)

        yield _sse("chat", {"chat_id": chat_id, "message_id": new_msg_id})

        _SANDBOX_TOOL_NAMES = {"sandbox_execute", "sandbox_install", "sandbox_write_file", "sandbox_read_file", "sandbox_list_files"}

        while True:
            round_content = ""
            round_reasoning = ""
            accumulated_tool_calls: list[AccumulatedToolCall] = []

            if is_ollama:
                ollama_model = model.removeprefix("ollama/")
                stream = ollama.stream_completion(messages=messages_for_api, model=ollama_model, base_url=ollama_url, tools=regen_tools)
            else:
                stream = openrouter.stream_completion(messages=messages_for_api, model=model, api_key=api_key, tools=regen_tools)

            async for chunk in stream:
                if chunk.error:
                    yield _sse("error", {"message": chunk.error})
                    if full_content:
                        await _save_assistant_message(new_msg_id, chat_id, user_id, full_content, used_model, last_usage, reasoning=full_reasoning, tool_executions=all_tool_executions or None)
                    return

                if chunk.reasoning:
                    round_reasoning += chunk.reasoning
                    yield _sse("reasoning", {"text": chunk.reasoning})

                if chunk.content:
                    round_content += chunk.content
                    yield _sse("content", {"text": chunk.content})

                if chunk.tool_calls:
                    accumulate_tool_calls(accumulated_tool_calls, chunk.tool_calls)

                if chunk.model:
                    used_model = chunk.model

                if chunk.finish_reason:
                    yield _sse("finish", {"reason": chunk.finish_reason})

                if chunk.usage:
                    last_usage = chunk.usage
                    yield _sse("usage", {
                        "prompt_tokens": chunk.usage.prompt_tokens,
                        "completion_tokens": chunk.usage.completion_tokens,
                        "cached_tokens": chunk.usage.cached_tokens,
                        "cost": chunk.usage.cost,
                        "provider": chunk.usage.provider,
                    })

            full_content += round_content
            full_reasoning += round_reasoning

            if not accumulated_tool_calls:
                break

            # Ensure sandbox container exists when a sandbox tool is called
            if not sandbox and any(tc.function_name in _SANDBOX_TOOL_NAMES for tc in accumulated_tool_calls):
                async with async_session() as sandbox_db:
                    sandbox = await sandbox_manager.get_or_create(user_id, sandbox_db)
                    await sandbox_manager.ensure_chat_dir(sandbox, chat_id)

            # Append assistant turn with tool calls to API history
            assistant_api_msg: dict = {"role": "assistant"}
            if round_content:
                assistant_api_msg["content"] = round_content
            assistant_api_msg["tool_calls"] = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function_name, "arguments": tc.function_arguments}}
                for tc in accumulated_tool_calls
            ]
            messages_for_api.append(assistant_api_msg)

            for tc in accumulated_tool_calls:
                yield _sse("tool_executing", {"id": tc.id, "name": tc.function_name, "arguments": tc.function_arguments})

            async def _run_one_tool(tc: AccumulatedToolCall) -> str:
                async with async_session() as tool_db:
                    try:
                        return await execute_tool_call(
                            sandbox_manager, sandbox, chat_id,
                            tc.function_name, tc.function_arguments,
                            db=tool_db, loaded_skills=loaded_skills,
                        )
                    except Exception as e:
                        return json.dumps({"error": f"{type(e).__name__}: {e}"})

            tool_results = await asyncio.gather(*(_run_one_tool(tc) for tc in accumulated_tool_calls))

            for tc, result_str in zip(accumulated_tool_calls, tool_results):
                try:
                    parsed_result = json.loads(result_str)
                except (json.JSONDecodeError, TypeError):
                    parsed_result = {"stdout": str(result_str), "stderr": "", "exit_code": 0, "files_created": []}

                tool_status = "error" if parsed_result.get("error") or parsed_result.get("exit_code", 0) != 0 else "completed"

                yield _sse("tool_result", {"id": tc.id, "name": tc.function_name, "result": result_str, "status": tool_status})

                all_tool_executions.append({"id": tc.id, "name": tc.function_name, "arguments": tc.function_arguments, "status": tool_status, "result": parsed_result})

                messages_for_api.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

        # If model sent everything as reasoning with no content, promote it
        if not full_content and full_reasoning:
            full_content = full_reasoning
            full_reasoning = ""
            yield _sse("content", {"text": full_content})

        # Fetch cost from generation endpoint if not provided in stream
        if not is_ollama and last_usage and last_usage.generation_id and not last_usage.cost:
            try:
                gen = await openrouter.get_generation(last_usage.generation_id, api_key)
                if gen:
                    last_usage.cost = gen.get("total_cost", 0.0) or 0.0
                    if gen.get("native_tokens_prompt"):
                        last_usage.prompt_tokens = last_usage.prompt_tokens or gen["native_tokens_prompt"]
                    if gen.get("native_tokens_completion"):
                        last_usage.completion_tokens = last_usage.completion_tokens or gen["native_tokens_completion"]
                    last_usage.cached_tokens = last_usage.cached_tokens or gen.get("native_tokens_cached", 0)
                    last_usage.provider = last_usage.provider or gen.get("provider_name", "")
            except Exception:
                pass

        if full_content:
            await _save_assistant_message(new_msg_id, chat_id, user_id, full_content, used_model, last_usage, reasoning=full_reasoning, tool_executions=all_tool_executions or None)

        yield _sse("done", {})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
