"""Bounded, citation-safe durable snapshot serialization."""

import json
from typing import Any

from quip.services.chat_run_types import MAX_SNAPSHOT_BYTES, MAX_SOURCE_TITLE_BYTES, MAX_SOURCE_URL_BYTES


def _bounded_json(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[truncated]"
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, dict):
        return {str(key)[:100]: _bounded_json(item, depth=depth + 1) for key, item in list(value.items())[:64]}
    if isinstance(value, (list, tuple)):
        return [_bounded_json(item, depth=depth + 1) for item in value[:100]]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)[:1000]


def _utf8_prefix(value: Any, max_bytes: int) -> tuple[str, bool]:
    text = value if isinstance(value, str) else str(value or "")
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    return encoded[:max_bytes].decode("utf-8", errors="ignore"), True


def _snapshot_json_bytes(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def bounded_snapshot(snapshot: Any) -> dict[str, Any]:
    """Return a size-bounded snapshot without storing partial citation URLs."""
    if not isinstance(snapshot, dict):
        return {"truncated": True}

    truncated = bool(snapshot.get("truncated", False))
    safe: dict[str, Any] = {}
    known = {"sources", "progress", "subagents", "errors", "usage", "truncated"}
    for key, value in snapshot.items():
        key = str(key)[:100]
        if key not in known:
            safe[key] = _bounded_json(value)

    safe_progress: list[dict[str, Any]] = []
    progress = snapshot.get("progress")
    if isinstance(progress, list):
        if len(progress) > 40:
            truncated = True
        for item in progress[-40:]:
            if not isinstance(item, dict):
                truncated = True
                continue
            bounded: dict[str, Any] = {}
            for field_name, byte_limit in (("phase", 80), ("detail", 512)):
                if field_name in item:
                    bounded[field_name], cut = _utf8_prefix(item[field_name], byte_limit)
                    truncated = truncated or cut
            for field_name, byte_limit, max_items in (
                ("sub_queries", 256, 12),
                ("urls_reading", MAX_SOURCE_URL_BYTES, 10),
            ):
                values = item.get(field_name)
                if not isinstance(values, (list, tuple)):
                    continue
                if len(values) > max_items:
                    truncated = True
                collected = []
                for value in values[:max_items]:
                    bounded_value, cut = _utf8_prefix(value, byte_limit)
                    if field_name == "urls_reading" and cut:
                        truncated = True
                        continue
                    collected.append(bounded_value)
                    truncated = truncated or cut
                bounded[field_name] = collected
            for field_name in ("sources_found", "urls_read"):
                value = item.get(field_name)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    bounded[field_name] = value
            safe_progress.append(bounded)
    if safe_progress or "progress" in snapshot:
        safe["progress"] = safe_progress

    safe_subagents: dict[str, dict[str, str]] = {}
    subagents = snapshot.get("subagents")
    if isinstance(subagents, dict):
        entries = list(subagents.items())
        if len(entries) > 8:
            truncated = True
        for task_id, item in entries[-8:]:
            if not isinstance(item, dict):
                truncated = True
                continue
            bounded: dict[str, str] = {}
            for field_name, byte_limit in (("task_id", 80), ("kind", 40), ("status", 24), ("goal", 300)):
                value = item.get(field_name)
                if value is None:
                    continue
                bounded[field_name], cut = _utf8_prefix(value, byte_limit)
                truncated = truncated or cut
            bounded_id, cut = _utf8_prefix(task_id, 80)
            truncated = truncated or cut
            if "task_id" not in bounded:
                bounded["task_id"] = bounded_id
            safe_subagents[bounded_id] = bounded
    if safe_subagents or "subagents" in snapshot:
        safe["subagents"] = safe_subagents

    safe_errors: list[dict[str, str]] = []
    errors = snapshot.get("errors")
    if isinstance(errors, list):
        if len(errors) > 20:
            truncated = True
        for item in errors[-20:]:
            value = item.get("message") if isinstance(item, dict) else item
            message, cut = _utf8_prefix(value, 1000)
            safe_errors.append({"message": message})
            truncated = truncated or cut
    if safe_errors or "errors" in snapshot:
        safe["errors"] = safe_errors

    safe_sources: list[dict[str, str]] = []
    sources = snapshot.get("sources")
    if isinstance(sources, list):
        if len(sources) > 30:
            truncated = True
        for source in sources[:30]:
            if not isinstance(source, dict) or not isinstance(source.get("url"), str):
                truncated = True
                continue
            url, url_cut = _utf8_prefix(source["url"], MAX_SOURCE_URL_BYTES)
            if url_cut:
                # Citation targets stay exact or are omitted; never persist a broken URL prefix.
                truncated = True
                continue
            title, title_cut = _utf8_prefix(source.get("title", ""), MAX_SOURCE_TITLE_BYTES)
            bounded_source = {"title": title, "url": url}
            if isinstance(source.get("snippet"), str) and source["snippet"]:
                snippet, snippet_cut = _utf8_prefix(source["snippet"], 600)
                bounded_source["snippet"] = snippet
                truncated = truncated or snippet_cut
            safe_sources.append(bounded_source)
            truncated = truncated or title_cut
    if safe_sources or "sources" in snapshot:
        safe["sources"] = safe_sources

    if "usage" in snapshot:
        safe["usage"] = _bounded_json(snapshot.get("usage"))

    while _snapshot_json_bytes({**safe, "truncated": truncated}) > MAX_SNAPSHOT_BYTES:
        truncated = True
        if safe.get("sources"):
            safe["sources"].pop()
        elif safe.get("progress"):
            safe["progress"].pop(0)
        elif safe.get("errors"):
            safe["errors"].pop(0)
        elif safe.get("subagents"):
            safe["subagents"].pop(next(iter(safe["subagents"])))
        elif safe.get("usage"):
            usage = safe["usage"]
            if isinstance(usage, dict) and "subagent_generations" in usage:
                usage.pop("subagent_generations", None)
            else:
                safe.pop("usage", None)
        else:
            optional = [key for key in safe if key != "truncated"]
            if not optional:
                return {"truncated": True}
            largest = max(optional, key=lambda key: _snapshot_json_bytes(safe[key]))
            safe.pop(largest, None)

    safe["truncated"] = truncated
    return safe
