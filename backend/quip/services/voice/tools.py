"""Authenticated, idempotent allowlisted tools for live Qwen voice calls."""
import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.config import get_bool_setting
from quip.models.chat import Message
from quip.models.user import User
from quip.models.voice import VoiceToolCall
from quip.services.voice.common import get_latest_leaf_message_id, get_owned_call

logger = logging.getLogger(__name__)

MAX_TOOL_CALLS_PER_CALL = 10
MAX_SEARCHES_PER_CALL = 5
MAX_TOOL_SECONDS = 30
MAX_RESULT_CHARS = 8_000
ALLOWED_TOOLS = {"web_search", "read_url"}


def _parse_arguments(name: str, raw_arguments: str) -> tuple[dict, str]:
    try:
        args = json.loads(raw_arguments)
    except (json.JSONDecodeError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Tool arguments must be valid JSON") from exc
    if not isinstance(args, dict):
        raise HTTPException(status_code=422, detail="Tool arguments must be an object")
    required_key = "query" if name == "web_search" else "url"
    if set(args) != {required_key} or not isinstance(args[required_key], str):
        raise HTTPException(status_code=422, detail="Invalid tool arguments")
    value = args[required_key].strip()
    max_length = 400 if name == "web_search" else 2048
    if not value or len(value) > max_length:
        raise HTTPException(status_code=422, detail="Invalid tool arguments")
    args = {required_key: value}
    canonical = json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return args, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def _check_search_gate() -> None:
    if not get_bool_setting("search_enabled", False):
        raise HTTPException(status_code=403, detail="Web search is disabled")
    from quip.services.skill_store import get_skill

    skill = get_skill("web_search")
    if not skill or not skill.enabled or skill.is_internal:
        raise HTTPException(status_code=403, detail="Web search is disabled")


async def _run_tool(name: str, args: dict) -> dict:
    if name == "web_search":
        from quip.services.search import web_search

        results, _images = await web_search(args["query"], max_results=5)
        bounded = []
        for result in results[:5]:
            bounded.append({
                "title": str(result.title or "")[:250],
                "url": str(result.url or "")[:2048],
                "snippet": str(result.snippet or result.content or "")[:1200],
            })
        return {"results": bounded}

    from quip.services.scraper import read_url

    content = await read_url(args["url"], max_chars=MAX_RESULT_CHARS)
    return {"url": args["url"], "content": str(content)[:MAX_RESULT_CHARS]}


async def run_voice_web_tool(name: str, args: dict) -> dict:
    """Run the same bounded Quip web tools for a call or delegated text run.

    This pure execution entry deliberately has no VoiceCall ownership check:
    long-running delegated work must survive its originating call ending. Its
    caller still supplies an authenticated, owner-scoped task context.
    """
    if name not in ALLOWED_TOOLS:
        return {"status": "failed", "error_code": "unsupported_tool", "result": {"error": "unsupported_tool"}}
    try:
        normalized, _arguments_hash = _parse_arguments(
            name, json.dumps(args, ensure_ascii=False)
        )
        if name == "web_search":
            await _check_search_gate()
        result = await asyncio.wait_for(
            _run_tool(name, normalized), timeout=MAX_TOOL_SECONDS
        )
        status, error_code = "completed", None
    except HTTPException as exc:
        result = {"error": "tool_permission_denied" if exc.status_code == 403 else "invalid_tool_input"}
        status, error_code = "failed", result["error"]
    except asyncio.TimeoutError:
        result = {"error": "tool_timeout"}
        status, error_code = "failed", "tool_timeout"
    except ValueError:
        result = {"error": "unsafe_or_invalid_url" if name == "read_url" else "invalid_tool_input"}
        status, error_code = "failed", "invalid_tool_input"
    except Exception:  # noqa: BLE001
        logger.exception("Voice web tool %s failed", name)
        result = {"error": "tool_execution_failed"}
        status, error_code = "failed", "tool_execution_failed"

    encoded = json.dumps(result, ensure_ascii=False, default=str)
    if len(encoded) > MAX_RESULT_CHARS:
        result = {"content": encoded[: MAX_RESULT_CHARS - 20] + "…[truncated]"}
    return {"status": status, "error_code": error_code, "result": result}


async def _save_result_message(db: AsyncSession, call, provider_call_id: str, result: dict) -> UUID:
    message = Message(
        id=uuid4(),
        chat_id=call.chat_id,
        parent_id=await get_latest_leaf_message_id(db, call.chat_id),
        role="tool",
        content=json.dumps(result, ensure_ascii=False),
        model=call.model,
        provider="qwen",
        meta={
            "source": "qwen_voice_tool",
            "voice_call_id": str(call.id),
            "provider_call_id": provider_call_id,
        },
        created_at=datetime.now(UTC),
    )
    db.add(message)
    await db.flush()
    return message.id


async def execute_voice_tool(
    db: AsyncSession,
    user: User,
    call_id: UUID,
    *,
    provider_call_id: str,
    name: str,
    raw_arguments: str,
) -> dict:
    call = await get_owned_call(db, call_id, user.id)
    if call is None:
        raise HTTPException(status_code=404, detail="Voice call not found")
    if call.status != "active":
        raise HTTPException(status_code=409, detail="Voice call is not active")
    if name not in ALLOWED_TOOLS:
        raise HTTPException(status_code=422, detail="Unsupported voice tool")
    args, arguments_hash = _parse_arguments(name, raw_arguments)
    if name == "web_search":
        await _check_search_gate()
    existing = await db.scalar(
        select(VoiceToolCall).where(
            VoiceToolCall.voice_call_id == call.id,
            VoiceToolCall.provider_call_id == provider_call_id,
        )
    )
    if existing is not None:
        if existing.arguments_hash != arguments_hash or existing.function_name != name:
            raise HTTPException(status_code=409, detail="Tool call ID was reused with different arguments")
        if existing.status == "pending":
            raise HTTPException(status_code=409, detail="Tool call is already running")
        return {
            "provider_call_id": provider_call_id,
            "name": name,
            "status": existing.status,
            "result": existing.result or {"error": "tool_result_unavailable"},
            "replayed": True,
        }

    rows = list((await db.scalars(
        select(VoiceToolCall).where(VoiceToolCall.voice_call_id == call.id)
    )).all())
    if len(rows) >= MAX_TOOL_CALLS_PER_CALL:
        raise HTTPException(status_code=429, detail="Voice tool call limit reached")
    if name == "web_search" and sum(row.function_name == "web_search" for row in rows) >= MAX_SEARCHES_PER_CALL:
        raise HTTPException(status_code=429, detail="Voice search limit reached")
    if any(row.status == "pending" for row in rows):
        raise HTTPException(status_code=409, detail="Another voice tool is already running")

    tool_call = VoiceToolCall(
        voice_call_id=call.id,
        provider_call_id=provider_call_id,
        function_name=name,
        arguments_hash=arguments_hash,
        status="pending",
    )
    db.add(tool_call)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(
            select(VoiceToolCall).where(
                VoiceToolCall.voice_call_id == call.id,
                VoiceToolCall.provider_call_id == provider_call_id,
            )
        )
        if existing and existing.arguments_hash == arguments_hash and existing.status != "pending":
            return {
                "provider_call_id": provider_call_id,
                "name": name,
                "status": existing.status,
                "result": existing.result or {"error": "tool_result_unavailable"},
                "replayed": True,
            }
        raise HTTPException(status_code=409, detail="Another voice tool is already running") from None

    execution = await run_voice_web_tool(name, args)
    result = execution["result"]
    status = execution["status"]
    error_code = execution["error_code"]
    result = json.loads(json.dumps(result, ensure_ascii=False, default=str))
    encoded = json.dumps(result, ensure_ascii=False)
    if len(encoded) > MAX_RESULT_CHARS:
        result = {"content": encoded[: MAX_RESULT_CHARS - 20] + "…[truncated]"}
    tool_call.status = status
    tool_call.result = result
    tool_call.error_code = error_code
    tool_call.finished_at = datetime.now(UTC)
    tool_call.result_message_id = await _save_result_message(db, call, provider_call_id, result)
    await db.commit()
    return {
        "provider_call_id": provider_call_id,
        "name": name,
        "status": status,
        "result": result,
        "replayed": False,
    }
