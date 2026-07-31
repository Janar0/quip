"""Telegram chat bridge.

The bridge deliberately talks to the Bot API over HTTP instead of adding a
second LLM integration. Every Telegram turn is routed through the same
CompletionService as the WebUI, so tools, RAG, budgets, usage accounting and
message persistence stay consistent across clients.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from sqlalchemy import and_, delete, or_, select

from quip.core.config import get_setting
from quip.database import async_session
from quip.models.chat import Chat
from quip.models.user import TelegramLinkToken, TelegramUpdate, User
from quip.routers.models import get_default_model
from quip.schemas.chat import CompletionRequest
from quip.services.artifacts import extract_artifacts
from quip.services.completion import CompletionService
from quip.services.completion.service import _parse_sse_frame
from quip.services.telegram_auth import (
    TelegramAuthError,
    consume_telegram_link,
    create_telegram_claim,
    unlink_telegram,
)
from quip.services.telegram_media import (
    TelegramMedia,
    TelegramMediaError,
    describe_media,
    media_prompt,
    persist_media,
)
from quip.services.telegram_widgets import widget_to_markdown
from quip.services.title import fallback_chat_emoji
from quip.services.workspaces import ensure_personal_workspace

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}"
POLL_TIMEOUT = 25
DRAFT_INTERVAL = 0.35
MAX_MESSAGE_LENGTH = 4096


class TelegramAPIError(RuntimeError):
    """A rejected Telegram Bot API request."""


class TelegramBotAPI:
    def __init__(self, token: str):
        self.token = token
        self.client = httpx.AsyncClient(
            base_url=TELEGRAM_API.format(token=token),
            timeout=httpx.Timeout(40.0, connect=10.0),
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def download_file(self, file_path: str) -> bytes:
        response = await self.client.get(
            f"https://api.telegram.org/file/bot{self.token}/{file_path}",
            timeout=httpx.Timeout(45.0, connect=10.0),
        )
        response.raise_for_status()
        return response.content

    async def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        response = await self.client.post(f"/{method}", json=payload or {})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise TelegramAPIError(body.get("description") or f"Telegram {method} failed")
        return body.get("result")


def _thread_key(message: dict[str, Any]) -> str:
    """Return a stable key for a private chat or a private-chat topic."""
    return str(message.get("message_thread_id") or 0)


def _allowed_user_ids() -> set[str]:
    raw = get_setting("telegram_allowed_user_ids", "")
    return {item for item in re.split(r"[\s,]+", raw.strip()) if item}


def _thread_payload(chat_id: int | str, thread_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"chat_id": chat_id}
    if thread_id != "0":
        payload["message_thread_id"] = int(thread_id)
    return payload


def _edit_payload(chat_id: int | str, message_id: int) -> dict[str, Any]:
    """Parameters for editMessageText (message_thread_id is not accepted there)."""
    return {"chat_id": chat_id, "message_id": message_id}


def _split_text(text: str, limit: int = MAX_MESSAGE_LENGTH - 80) -> list[str]:
    """Split long output at a natural boundary before Telegram's hard limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > limit:
        cut = max(remaining.rfind("\n", 0, limit), remaining.rfind(" ", 0, limit))
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        chunks.append(remaining)
    return chunks


_MDV2_SPECIAL = set("_*[]()~`>#+-=|{}.!\\")


_SOURCE_LINE = re.compile(
    r"^(\s*)\[(\d+)\]\s+(.+?)\s+-\s+(https?://\S+)\s*$", re.MULTILINE
)


def _normalize_telegram_markdown(markdown: str) -> str:
    """Turn common search source lines into Markdown links."""
    def replace(match: re.Match[str]) -> str:
        prefix, number, title, url = match.groups()
        return f"{prefix}[{number}] [{title}]({url.rstrip('.,;')})"

    return _SOURCE_LINE.sub(replace, markdown)


def _telegram_display_text(text: str) -> tuple[str, list[dict]]:
    """Remove WebUI-only artifact tags before sending text to Telegram."""
    artifacts, cleaned = extract_artifacts(text)
    cleaned = re.sub(r"<artifact\b[^>]*>.*$", "", cleaned, flags=re.DOTALL).rstrip()
    return cleaned, artifacts


def _escape_markdown_v2(text: str) -> str:
    return "".join(f"\\{char}" if char in _MDV2_SPECIAL else char for char in text)


def markdown_to_markdown_v2(markdown: str) -> str:
    """Convert the common Markdown emitted by LLMs to safe Telegram MarkdownV2.

    Telegram's parser is intentionally strict. The converter keeps the useful
    subset (headings, emphasis, links, lists and code) and escapes everything
    else. If a future Markdown construct is not recognized it remains readable
    as plain text rather than making the whole Telegram message fail.
    """

    markdown = _normalize_telegram_markdown(markdown)
    protected: list[str] = []

    def protect(value: str) -> str:
        marker = f"\x00{len(protected)}\x00"
        protected.append(value)
        return marker

    def fenced_code(match: re.Match[str]) -> str:
        language = match.group(1) or ""
        code = match.group(2).strip("\n").replace("```", "\\`\\`\\`")
        return protect(f"```{language}\n{code}\n```")

    result = re.sub(r"```([\w+-]*)\n?(.*?)```", fenced_code, markdown, flags=re.DOTALL)

    def inline_code(match: re.Match[str]) -> str:
        code = match.group(1).replace("`", "\\`")
        return protect(f"`{code}`")

    result = re.sub(r"`([^`\n]+)`", inline_code, result)

    def link(match: re.Match[str]) -> str:
        label = _escape_markdown_v2(match.group(1))
        url = match.group(2).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        return protect(f"[{label}]({url})")

    # A greedy URL capture keeps balanced parentheses commonly found in
    # documentation links (e.g. ``/a_(b)``) inside the URL.
    result = re.sub(r"\[([^\]\n]+)\]\(([^\n]+)\)", link, result)

    def heading(match: re.Match[str]) -> str:
        return protect(f"*{_escape_markdown_v2(match.group(1).strip())}*")

    result = re.sub(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", heading, result, flags=re.MULTILINE)

    def bold(match: re.Match[str]) -> str:
        return protect(f"*{_escape_markdown_v2(match.group(1))}*")

    result = re.sub(r"\*\*([^*\n]+)\*\*", bold, result)
    result = re.sub(r"__([^_\n]+)__", bold, result)

    def strike(match: re.Match[str]) -> str:
        return protect(f"~{_escape_markdown_v2(match.group(1))}~")

    result = re.sub(r"~~([^~\n]+)~~", strike, result)

    def italic(match: re.Match[str]) -> str:
        return protect(f"_{_escape_markdown_v2(match.group(1))}_")

    result = re.sub(r"(?<!\w)\*([^*\n]+)\*(?!\w)", italic, result)
    result = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", italic, result)

    result = re.sub(
        r"^\s*>\s?(.*?)\s*$",
        lambda match: f"{protect('>')} {match.group(1)}",
        result,
        flags=re.MULTILINE,
    )
    result = re.sub(r"^\s*[-+*]\s+\[[xX]\]\s+", "☑ ", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*[-+*]\s+\[\s\]\s+", "☐ ", result, flags=re.MULTILINE)
    result = re.sub(r"^\s*[-+*]\s+", "• ", result, flags=re.MULTILINE)
    result = re.sub(r"^(\s*)(\d+)\.\s+", r"\1\2\\. ", result, flags=re.MULTILINE)

    def table(match: re.Match[str]) -> str:
        rows = []
        for row in match.group(0).splitlines():
            if re.fullmatch(r"\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*", row):
                continue
            rows.append(row.strip())
        fence = chr(96) * 3
        return protect(f"{fence}\n{chr(10).join(rows)}\n{fence}") if rows else ""

    result = re.sub(
        r"(?:^[ \t]*\|.*\|[ \t]*\n?){2,}",
        table,
        result,
        flags=re.MULTILINE,
    )

    result = _escape_markdown_v2(result)
    for index, value in enumerate(protected):
        result = result.replace(f"\x00{index}\x00", value)
    return result


class TelegramBotService:
    """Long-polling Telegram worker owned by the FastAPI lifespan."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._worker_task: asyncio.Task | None = None
        self._api: TelegramBotAPI | None = None
        self._lifecycle_lock = asyncio.Lock()
        self._thread_locks: dict[tuple[str, str], asyncio.Lock] = {}
        self._last_maintenance = 0.0

    async def start(self) -> None:
        await self.reconfigure()

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            task = self._task
            self._task = None
            if task:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            worker = self._worker_task
            self._worker_task = None
            if worker:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
            if self._api:
                await self._api.close()
                self._api = None

    async def reconfigure(self) -> None:
        async with self._lifecycle_lock:
            old_task = self._task
            self._task = None
            if old_task:
                old_task.cancel()
                with suppress(asyncio.CancelledError):
                    await old_task
            old_worker = self._worker_task
            self._worker_task = None
            if old_worker:
                old_worker.cancel()
                with suppress(asyncio.CancelledError):
                    await old_worker
            if self._api:
                await self._api.close()
                self._api = None

            token = get_setting("telegram_bot_token", "").strip()
            if not token:
                logger.info("Telegram bridge disabled: telegram_bot_token is not configured")
                return

            self._api = TelegramBotAPI(token)
            self._worker_task = asyncio.create_task(self._process_update_queue(), name="quip-telegram-worker")
            self._task = asyncio.create_task(self._poll(), name="quip-telegram-poll")
            logger.info("Telegram bridge enabled")

    async def _poll(self) -> None:
        assert self._api is not None
        api = self._api
        offset = 0
        backoff = 1
        try:
            with suppress(TelegramAPIError):
                await api.call("deleteWebhook", {"drop_pending_updates": False})
            with suppress(TelegramAPIError):
                await api.call(
                    "setMyCommands",
                    {
                        "commands": [
                            {"command": "start", "description": "Войти и открыть чат"},
                            {"command": "new", "description": "Сбросить текущую тему"},
                            {"command": "search", "description": "Поиск в интернете"},
                            {"command": "model", "description": "Показать модель"},
                            {"command": "unlink", "description": "Отвязать Telegram"},
                            {"command": "help", "description": "Помощь"},
                        ]
                    },
                )

            while True:
                try:
                    updates = await api.call(
                        "getUpdates",
                        {
                            "offset": offset,
                            "timeout": POLL_TIMEOUT,
                            "allowed_updates": ["message"],
                        },
                    )
                    backoff = 1
                    for update in updates or []:
                        await self._enqueue_update(update)
                        offset = max(offset, int(update.get("update_id", 0)) + 1)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Telegram polling failed; retrying")
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 30)
        except asyncio.CancelledError:
            raise

    async def _enqueue_update(self, payload: dict[str, Any]) -> None:
        update_id = int(payload.get("update_id", -1))
        if update_id < 0:
            return
        async with async_session() as db:
            existing = await db.get(TelegramUpdate, update_id)
            if existing is None:
                db.add(TelegramUpdate(update_id=update_id, payload=payload))
                try:
                    await db.commit()
                except Exception:
                    await db.rollback()
                    # A second poller/process may have inserted the same update.
                    existing = await db.get(TelegramUpdate, update_id)
                    if existing is None:
                        raise

    async def _claim_update(self) -> tuple[int, dict[str, Any], int] | None:
        now = datetime.now(UTC)
        stale_before = now - timedelta(minutes=5)
        async with async_session() as db:
            result = await db.execute(
                select(TelegramUpdate)
                .where(
                    or_(
                        TelegramUpdate.status == "pending",
                        and_(
                            TelegramUpdate.status == "processing",
                            TelegramUpdate.locked_at < stale_before,
                        ),
                    ),
                    or_(TelegramUpdate.available_at.is_(None), TelegramUpdate.available_at <= now),
                )
                .order_by(TelegramUpdate.update_id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            row.status = "processing"
            row.locked_at = now
            row.attempts = (row.attempts or 0) + 1
            await db.commit()
            return row.update_id, row.payload, row.attempts

    async def _finish_update(self, update_id: int, attempts: int, error: str | None = None) -> None:
        async with async_session() as db:
            row = await db.get(TelegramUpdate, update_id)
            if row is None:
                return
            if error and attempts < 5:
                row.status = "pending"
                row.available_at = datetime.now(UTC) + timedelta(seconds=min(30, attempts * 5))
                row.last_error = error[:1000]
            elif error:
                row.status = "failed"
                row.last_error = error[:1000]
                row.processed_at = datetime.now(UTC)
            else:
                row.status = "processed"
                row.processed_at = datetime.now(UTC)
                row.last_error = None
            row.locked_at = None
            await db.commit()

    async def _process_update_queue(self) -> None:
        while True:
            try:
                item = await self._claim_update()
                if item is None:
                    if time.monotonic() - self._last_maintenance > 600:
                        await self._run_maintenance()
                        self._last_maintenance = time.monotonic()
                    await asyncio.sleep(0.5)
                    continue
                update_id, payload, attempts = item
                try:
                    message = payload.get("message")
                    if message:
                        await self._handle_message(message)
                except Exception as exc:
                    logger.exception("Telegram update %s failed", update_id)
                    await self._finish_update(update_id, attempts, str(exc))
                else:
                    await self._finish_update(update_id, attempts)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram update worker failed; retrying")
                await asyncio.sleep(1)

    async def _run_maintenance(self) -> None:
        """Keep durable queue and one-time auth tokens from growing forever."""
        now = datetime.now(UTC)
        async with async_session() as db:
            await db.execute(
                delete(TelegramUpdate).where(
                    TelegramUpdate.status.in_({"processed", "failed"}),
                    TelegramUpdate.processed_at < now - timedelta(days=14),
                )
            )
            await db.execute(delete(TelegramLinkToken).where(TelegramLinkToken.expires_at < now))
            await db.commit()

    async def _handle_message(self, message: dict[str, Any]) -> None:
        chat = message.get("chat") or {}
        if chat.get("type") != "private":
            return
        media = describe_media(message)
        text = (message.get("text") or message.get("caption") or "").strip()
        topic_created = message.get("forum_topic_created") or {}
        topic_edited = message.get("forum_topic_edited") or {}
        if not text and media is None and not topic_created and not topic_edited:
            return

        chat_id = chat.get("id")
        sender = message.get("from") or {}
        sender_id = str(sender.get("id", ""))
        thread_id = _thread_key(message)
        if chat_id is None or not sender_id:
            return

        lock_key = (str(chat_id), thread_id)
        lock = self._thread_locks.setdefault(lock_key, asyncio.Lock())
        try:
            async with lock:
                await self._handle_locked_message(
                    message, text, int(chat_id), sender, sender_id, thread_id, media
                )
        finally:
            if not lock.locked() and self._thread_locks.get(lock_key) is lock:
                self._thread_locks.pop(lock_key, None)

    async def _handle_locked_message(
        self,
        message: dict[str, Any],
        text: str,
        chat_id: int,
        sender: dict[str, Any],
        sender_id: str,
        thread_id: str,
        media: TelegramMedia | None = None,
    ) -> None:
        api = self._api
        if api is None:
            return

        topic_created = message.get("forum_topic_created") or {}
        topic_edited = message.get("forum_topic_edited") or {}
        command, argument = self._command(text)
        topic_name = str(
            topic_edited.get("name") or topic_created.get("name") or ""
        ).strip() or None
        topic_name_implicit: bool | None = (
            bool(topic_created.get("is_name_implicit"))
            if topic_created
            else (False if topic_edited and topic_name else None)
        )
        topic_event = bool(topic_created or topic_edited)
        if command == "/start" and argument.startswith("link_"):
            await self._link_user(chat_id, thread_id, sender_id, sender, argument)
            return

        async with async_session() as db:
            user = await self._get_linked_user(sender_id, db)
            if user is None:
                if command == "/start":
                    await self._send_telegram_auth_link(chat_id, thread_id, sender_id, db)
                    return
                await self._send_text(
                    chat_id,
                    thread_id,
                    "Для подключения откройте /start — бот выдаст ссылку на вход в QUIP.",
                    markdown=False,
                )
                return

            allowed = _allowed_user_ids()
            if allowed and sender_id not in allowed:
                await self._send_text(
                    chat_id,
                    thread_id,
                    "Доступ ограничен администратором Telegram. Обратитесь к администратору QUIP.",
                    markdown=False,
                )
                return

            if command == "/unlink":
                await unlink_telegram(db, user)
                await self._send_text(
                    chat_id, thread_id, "Telegram отвязан от QUIP. Для повторного подключения используйте WebUI.", markdown=False
                )
                return

            if command in {"/start", "/help"}:
                await self._send_text(chat_id, thread_id, self._help_text(), markdown=False)
                return
            if command in {"/new", "/reset"}:
                await self._archive_current_chat(user, chat_id, thread_id, db)
                await self._send_text(
                    chat_id, thread_id, "Готово. Следующее сообщение начнёт новый чат QUIP.", markdown=False
                )
                return
            if command == "/threads":
                await self._send_text(
                    chat_id,
                    thread_id,
                    "Включите Threaded Mode у бота через @BotFather. Каждый Telegram-тред будет отдельным чатом QUIP.",
                    markdown=False,
                )
                return

            if topic_event and not text and media is None:
                if topic_name:
                    await self._get_or_create_chat(
                        user,
                        chat_id,
                        thread_id,
                        db,
                        topic_name=topic_name,
                        topic_name_implicit=topic_name_implicit,
                    )
                return

            current_chat = await self._get_or_create_chat(
                user,
                chat_id,
                thread_id,
                db,
                topic_name=topic_name,
                topic_name_implicit=topic_name_implicit,
            )
            if command == "/model":
                await self._send_text(
                    chat_id,
                    thread_id,
                    f"Модель этого чата: {current_chat.model or self._default_model() or 'не выбрана'}",
                    markdown=False,
                )
                return

            mode_hint = "search" if command == "/search" else None
            prompt = argument if command in {"/search", "/ask"} else text
            file_ids = []
            if media is not None:
                try:
                    file_record = await persist_media(db, user, current_chat, media, api)
                except (TelegramMediaError, TelegramAPIError, httpx.HTTPError) as exc:
                    await self._send_text(
                        chat_id,
                        thread_id,
                        f"Не удалось принять вложение: {exc}",
                        markdown=False,
                    )
                    return
                file_ids.append(file_record.id)
            if not prompt:
                prompt = media_prompt(media) if media is not None else ""
            if not prompt:
                await self._send_text(chat_id, thread_id, "После команды нужен текст запроса.", markdown=False)
                return

            await self._run_completion(
                api,
                current_chat,
                user,
                prompt,
                mode_hint,
                chat_id,
                thread_id,
                file_ids,
            )

    async def _link_user(
        self,
        chat_id: int,
        thread_id: str,
        sender_id: str,
        sender: dict[str, Any],
        raw_token: str,
    ) -> None:
        try:
            async with async_session() as db:
                user = await consume_telegram_link(db, raw_token, sender_id, sender)
        except TelegramAuthError as exc:
            await self._send_text(
                chat_id,
                thread_id,
                str(exc),
                markdown=False,
            )
            return
        await self._send_text(
            chat_id,
            thread_id,
            f"Telegram привязан к аккаунту {user.name}. Теперь этот чат использует ваш аккаунт QUIP.",
            markdown=False,
        )

    @staticmethod
    def _public_app_url() -> str:
        configured = get_setting("public_app_url", "").strip()
        if configured:
            return configured.rstrip("/")
        redirect_uri = get_setting("telegram_login_redirect_uri", "").strip()
        suffix = "/api/auth/telegram/callback"
        if redirect_uri.endswith(suffix):
            return redirect_uri[: -len(suffix)].rstrip("/")
        return ""

    async def _send_telegram_auth_link(
        self,
        chat_id: int,
        thread_id: str,
        telegram_user_id: str,
        db,
    ) -> None:
        base_url = self._public_app_url()
        if not base_url:
            await self._send_text(
                chat_id,
                thread_id,
                "Администратору нужно настроить PUBLIC_APP_URL — адрес WebUI, доступный из Telegram.",
                markdown=False,
            )
            return

        raw_token, _ = await create_telegram_claim(db, telegram_user_id)
        link = f"{base_url}/api/auth/telegram/claim?token={quote(raw_token, safe='')}"
        api = self._api
        if api is None:
            return
        try:
            await api.call(
                "sendMessage",
                {
                    **_thread_payload(chat_id, thread_id),
                    "text": "Войдите в QUIP или откройте уже выполненный WebUI-сеанс — Telegram привяжется автоматически.",
                    "reply_markup": {"inline_keyboard": [[{"text": "Войти в QUIP", "url": link}]]},
                },
            )
        except (TelegramAPIError, httpx.HTTPError):
            await self._send_text(chat_id, thread_id, f"Ссылка для входа в QUIP: {link}", markdown=False)

    @staticmethod
    def _command(text: str) -> tuple[str | None, str]:
        if not text.startswith("/"):
            return None, text
        parts = text.split(maxsplit=1)
        command = parts[0].split("@", 1)[0].lower()
        return command, parts[1].strip() if len(parts) > 1 else ""

    @staticmethod
    def _help_text() -> str:
        return (
            "QUIP в Telegram\n\n"
            "/start — войти или открыть чат\n"
            "Просто напишите вопрос — ответ будет идти потоком.\n\n"
            "Новая тема Telegram — отдельный чат QUIP.\n"
            "/new — сбросить текущую тему в режиме без тредов\n"
            "/search запрос — поиск в интернете\n"
            "/model — текущая модель\n"
            "/threads — как включить треды\n"
            "/unlink — отвязать Telegram\n"
            "/help — эта справка"
        )

    @staticmethod
    def _default_model() -> str:
        configured = get_setting("telegram_model") or get_setting("default_model")
        if configured:
            return configured
        cached = get_default_model()
        return str(cached.get("id")) if cached and cached.get("id") else ""

    async def _get_linked_user(self, sender_id: str, db) -> User | None:
        result = await db.execute(
            select(User).where(
                User.telegram_user_id == sender_id,
                User.is_active.is_(True),
                User.role != "pending",
            )
        )
        return result.scalar_one_or_none()

    async def _get_or_create_chat(
        self,
        user: User,
        chat_id: int,
        thread_id: str,
        db,
        topic_name: str | None = None,
        topic_name_implicit: bool | None = None,
    ) -> Chat:
        result = await db.execute(
            select(Chat)
            .where(
                Chat.user_id == user.id,
                Chat.source == "telegram",
                Chat.external_chat_id == str(chat_id),
                Chat.external_thread_id == thread_id,
                Chat.archived.is_(False),
            )
            .order_by(Chat.updated_at.desc())
            .limit(1)
        )
        current = result.scalar_one_or_none()
        if current:
            if topic_name and topic_name_implicit is not None:
                current.title = topic_name[:500]
                current.meta = {
                    **(current.meta or {}),
                    "emoji": current.emoji or fallback_chat_emoji(topic_name),
                    "telegram_topic_implicit": topic_name_implicit,
                }
                await db.commit()
            return current

        workspace = await ensure_personal_workspace(user, db)
        current = Chat(
            user_id=user.id,
            workspace_id=workspace.id,
            title=(topic_name or "Telegram Chat")[:500],
            model=self._default_model() or None,
            source="telegram",
            external_chat_id=str(chat_id),
            external_thread_id=thread_id,
            meta=(
                {
                    "emoji": fallback_chat_emoji(topic_name),
                    "telegram_topic_implicit": bool(topic_name_implicit),
                }
                if topic_name
                else None
            ),
        )
        db.add(current)
        await db.commit()
        await db.refresh(current)
        return current

    @staticmethod
    async def _archive_current_chat(user: User, chat_id: int, thread_id: str, db) -> None:
        result = await db.execute(
            select(Chat).where(
                Chat.user_id == user.id,
                Chat.source == "telegram",
                Chat.external_chat_id == str(chat_id),
                Chat.external_thread_id == thread_id,
                Chat.archived.is_(False),
            )
        )
        current = result.scalar_one_or_none()
        if current:
            current.archived = True
            await db.commit()

    async def _run_completion(
        self,
        api: TelegramBotAPI,
        chat: Chat,
        user: User,
        prompt: str,
        mode_hint: str | None,
        telegram_chat_id: int,
        thread_id: str,
        file_ids: list,
    ) -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/chat/completions",
                "headers": [(b"accept-language", b"ru")],
                "query_string": b"",
                "client": ("telegram", 0),
                "server": ("telegram", 443),
                "scheme": "https",
            }
        )
        completion_request = CompletionRequest(
            chat_id=chat.id,
            workspace_id=chat.workspace_id,
            model=chat.model or self._default_model(),
            message=prompt,
            file_ids=file_ids,
            mode_hint=mode_hint,
        )

        draft_id = max(1, int(time.time() * 1000) % 2_000_000_000)
        stream_mode = "rich"
        placeholder_id: int | None = None
        full_text = ""
        error_text = ""
        widget_fallbacks: list[str] = []
        generated_topic_title: str | None = None
        last_update = 0.0

        try:
            try:
                await api.call(
                    "sendRichMessageDraft",
                    {
                        **_thread_payload(telegram_chat_id, thread_id),
                        "draft_id": draft_id,
                        "rich_message": {"markdown": " ", "skip_entity_detection": True},
                    },
                )
            except (TelegramAPIError, httpx.HTTPError):
                stream_mode = "plain"
                try:
                    await api.call(
                        "sendMessageDraft",
                        {
                            **_thread_payload(telegram_chat_id, thread_id),
                            "draft_id": draft_id,
                            "text": "",
                        },
                    )
                except (TelegramAPIError, httpx.HTTPError):
                    stream_mode = "edit"
                    placeholder = await api.call(
                        "sendMessage",
                        {
                            **_thread_payload(telegram_chat_id, thread_id),
                            "text": "⌛ Думаю…",
                        },
                    )
                    placeholder_id = int(placeholder["message_id"])

            async with async_session() as db:
                response = await CompletionService.chat_completion(
                    completion_request, request, user, db
                )
                async for frame in response.body_iterator:
                    event_type, data = _parse_sse_frame(frame)
                    if event_type == "content":
                        full_text += data.get("text", "")
                    elif event_type == "tool_result":
                        raw_result = data.get("result")
                        try:
                            result = (
                                json.loads(raw_result)
                                if isinstance(raw_result, str)
                                else raw_result
                            )
                        except (TypeError, json.JSONDecodeError):
                            result = None
                        if (
                            data.get("name") == "use_widget"
                            and isinstance(result, dict)
                            and result.get("widget")
                        ):
                            widget_data = result.get("data")
                            if isinstance(widget_data, dict):
                                widget_fallbacks.append(
                                    widget_to_markdown(
                                        str(result.get("template") or "widget"),
                                        widget_data,
                                    )
                                )
                    elif event_type == "title":
                        generated_topic_title = str(data.get("title") or "").strip() or None
                    elif event_type == "error":
                        error_text = str(data.get("error") or data.get("message") or "Generation failed")

                    now = time.monotonic()
                    if full_text and now - last_update >= DRAFT_INTERVAL:
                        preview, _ = _telegram_display_text(full_text)
                        preview = preview[: MAX_MESSAGE_LENGTH - 80]
                        if stream_mode == "rich":
                            try:
                                await api.call(
                                    "sendRichMessageDraft",
                                    {
                                        **_thread_payload(telegram_chat_id, thread_id),
                                        "draft_id": draft_id,
                                        "rich_message": {"markdown": preview, "skip_entity_detection": True},
                                    },
                                )
                            except (TelegramAPIError, httpx.HTTPError):
                                stream_mode = "plain"
                        if stream_mode == "plain":
                            try:
                                await api.call(
                                    "sendMessageDraft",
                                    {
                                        **_thread_payload(telegram_chat_id, thread_id),
                                        "draft_id": draft_id,
                                        "text": preview,
                                    },
                                )
                            except (TelegramAPIError, httpx.HTTPError):
                                stream_mode = "edit"
                        if stream_mode == "edit" and placeholder_id:
                            with suppress(TelegramAPIError, httpx.HTTPError):
                                await api.call(
                                    "editMessageText",
                                    {
                                        **_edit_payload(telegram_chat_id, placeholder_id),
                                        "text": preview,
                                    },
                                )
                        last_update = now

        except HTTPException as exc:
            error_text = str(exc.detail)
        except Exception:
            logger.exception("Telegram completion failed")
            error_text = "Не удалось выполнить запрос. Проверьте настройки QUIP и попробуйте ещё раз."

        if generated_topic_title and thread_id != "0":
            try:
                await api.call(
                    "editForumTopic",
                    {
                        "chat_id": telegram_chat_id,
                        "message_thread_id": int(thread_id),
                        "name": generated_topic_title[:128],
                    },
                )
            except (TelegramAPIError, httpx.HTTPError) as exc:
                logger.warning(
                    "Could not rename Telegram topic %s/%s: %s",
                    telegram_chat_id,
                    thread_id,
                    exc,
                )

        if full_text:
            display_text, artifacts = _telegram_display_text(full_text)
            if display_text and stream_mode == "rich":
                try:
                    await self._finish_rich_response(api, telegram_chat_id, thread_id, display_text)
                except (TelegramAPIError, httpx.HTTPError):
                    await self._finish_response(api, telegram_chat_id, thread_id, display_text, None)
            elif display_text:
                await self._finish_response(api, telegram_chat_id, thread_id, display_text, placeholder_id)
            for artifact in artifacts:
                title = artifact.get("title") or "Artifact"
                body = artifact.get("content") or ""
                fence = chr(96) * 3
                artifact_text = (
                    f"🧩 **{title}**\n\n"
                    f"{fence}{artifact.get('language') or ''}\n{body}\n{fence}"
                )
                await self._send_formatted(api, telegram_chat_id, thread_id, artifact_text)
            for widget in widget_fallbacks:
                await self._send_formatted(api, telegram_chat_id, thread_id, widget)
        elif error_text:
            if placeholder_id:
                with suppress(TelegramAPIError, httpx.HTTPError):
                    await api.call(
                        "editMessageText",
                        {
                            **_edit_payload(telegram_chat_id, placeholder_id),
                            "text": f"Ошибка: {error_text[:3900]}",
                        },
                    )
            else:
                await self._send_text(telegram_chat_id, thread_id, f"Ошибка: {error_text}", markdown=False)

    async def _finish_response(
        self,
        api: TelegramBotAPI,
        chat_id: int,
        thread_id: str,
        text: str,
        placeholder_id: int | None,
    ) -> None:
        chunks = _split_text(text)
        first = markdown_to_markdown_v2(chunks[0])
        if placeholder_id:
            try:
                await api.call(
                    "editMessageText",
                    {
                        **_edit_payload(chat_id, placeholder_id),
                        "text": first or "…",
                        "parse_mode": "MarkdownV2",
                        "link_preview_options": {"is_disabled": True},
                    },
                )
            except (TelegramAPIError, httpx.HTTPError):
                with suppress(TelegramAPIError, httpx.HTTPError):
                    await api.call(
                        "editMessageText",
                        {
                            **_edit_payload(chat_id, placeholder_id),
                            "text": chunks[0][:MAX_MESSAGE_LENGTH],
                        },
                    )
        else:
            await self._send_formatted(api, chat_id, thread_id, chunks[0])

        for chunk in chunks[1:]:
            await self._send_formatted(api, chat_id, thread_id, chunk)

    async def _finish_rich_response(
        self, api: TelegramBotAPI, chat_id: int, thread_id: str, text: str
    ) -> None:
        # Rich messages accept the original Markdown directly and support a
        # much larger payload than legacy sendMessage. Keep a conservative
        # split for unusually long generations and let Telegram render tables,
        # nested quotes and other new Markdown constructs natively.
        for chunk in _split_text(text, 32000):
            chunk = _normalize_telegram_markdown(chunk)
            try:
                await api.call(
                    "sendRichMessage",
                    {
                        **_thread_payload(chat_id, thread_id),
                        "rich_message": {"markdown": chunk, "skip_entity_detection": True},
                    },
                )
            except (TelegramAPIError, httpx.HTTPError):
                await self._send_formatted(api, chat_id, thread_id, chunk)

    async def _send_formatted(
        self, api: TelegramBotAPI, chat_id: int, thread_id: str, text: str
    ) -> None:
        formatted = markdown_to_markdown_v2(text)
        try:
            await api.call(
                "sendMessage",
                {
                    **_thread_payload(chat_id, thread_id),
                    "text": formatted or "…",
                    "parse_mode": "MarkdownV2",
                    "link_preview_options": {"is_disabled": True},
                },
            )
        except (TelegramAPIError, httpx.HTTPError):
            await self._send_text(chat_id, thread_id, text, markdown=False)

    async def _send_text(
        self, chat_id: int, thread_id: str, text: str, *, markdown: bool
    ) -> None:
        api = self._api
        if api is None:
            return
        for chunk in _split_text(text):
            payload = {**_thread_payload(chat_id, thread_id), "text": chunk}
            payload["link_preview_options"] = {"is_disabled": True}
            if markdown:
                payload["parse_mode"] = "MarkdownV2"
            with suppress(TelegramAPIError, httpx.HTTPError):
                await api.call("sendMessage", payload)
