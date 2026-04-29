"""Tool call dispatch and execution."""
import asyncio
import json
import logging

from quip.database import async_session
from quip.services.tools import (
    AccumulatedToolCall,
    accumulate_tool_calls,
    run_tool_call,
    SANDBOX_TOOL_NAMES,
)
from quip.services.sandbox import sandbox_manager

logger = logging.getLogger(__name__)


class ToolExecutor:
    """Dispatches and executes tool calls from LLM responses."""

    @staticmethod
    async def ensure_sandbox(
        user_id, chat_id: str, sandbox=None
    ):
        """Lazy-init sandbox container when a sandbox tool is requested."""
        if sandbox is not None:
            return sandbox
        try:
            async with async_session() as sandbox_db:
                sb = await sandbox_manager.get_or_create(user_id, sandbox_db)
                await sandbox_manager.ensure_chat_dir(sb, chat_id)
                return sb
        except Exception as e:
            logger.warning("Failed to get/create sandbox: %s", e)
            return None

    @staticmethod
    async def execute(
        accumulated_tool_calls: list[AccumulatedToolCall],
        sandbox,
        chat_id: str,
        loaded_skills: set[str],
        user_id,
    ) -> tuple:
        """Execute tool calls concurrently. Returns (sandbox, list of (tc_name, parsed_result, raw_json))."""
        need_sandbox = any(
            tc.function_name in SANDBOX_TOOL_NAMES
            for tc in accumulated_tool_calls
        )
        if need_sandbox and not sandbox:
            sandbox = await ToolExecutor.ensure_sandbox(user_id, chat_id, sandbox)

        raw_results = await asyncio.gather(
            *(
                run_tool_call(
                    tc,
                    sandbox_manager=sandbox_manager,
                    sandbox=sandbox,
                    chat_id=chat_id,
                    loaded_skills=loaded_skills,
                )
                for tc in accumulated_tool_calls
            )
        )

        parsed: list[tuple[str, dict, str]] = []
        for tc, raw in zip(accumulated_tool_calls, raw_results):
            try:
                parsed_result = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                parsed_result = {
                    "stdout": str(raw),
                    "stderr": "",
                    "exit_code": 0,
                    "files_created": [],
                }
            parsed.append((tc.function_name, parsed_result, raw))

        return sandbox, parsed

    @staticmethod
    def accumulate_search_data(
        results: list[tuple[str, dict, str]],
        accumulated_images: dict[str, dict],
        accumulated_sources: list[dict],
    ) -> tuple[dict[str, dict], list[dict]]:
        """Collect image URLs and sources from web_search results."""
        for name, parsed, _raw in results:
            if name != "web_search" or not isinstance(parsed, dict):
                continue
            for img in parsed.get("images") or []:
                if not isinstance(img, dict):
                    continue
                src = img.get("img_src")
                if src and src not in accumulated_images:
                    accumulated_images[src] = {
                        "img_src": src,
                        "source_url": img.get("source_url") or src,
                        "title": img.get("title") or "",
                    }
            for r in parsed.get("results") or []:
                if isinstance(r, dict) and r.get("url"):
                    url = r["url"]
                    if not any(s.get("url") == url for s in accumulated_sources):
                        accumulated_sources.append({
                            "title": r.get("title", "") or url,
                            "url": url,
                        })
        return accumulated_images, accumulated_sources
