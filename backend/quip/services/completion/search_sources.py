"""Build the Search mode sources footer from retrieved tool metadata only."""

from __future__ import annotations

import base64
import ipaddress
import json
import re
from urllib.parse import urlsplit, urlunsplit

_SOURCE_HEADER = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:\*\*|__)?(?:Sources|Источники):?(?:\*\*|__)?\s*$",
    re.IGNORECASE,
)
_SOURCE_ENTRY = re.compile(
    r"^(?:https?://\S+|\[[^\]]+\]\(https?://[^)\s]+\))$",
    re.IGNORECASE,
)
_LISTED_SOURCE_ENTRY = re.compile(
    r"^(?:\[\d{1,3}\]\s+|[-*+]\s+|\d{1,3}[.)]\s+).*(?:https?://|javascript:|data:)\S+.*$",
    re.IGNORECASE,
)
_UNNUMBERED_SOURCE_ENTRY = re.compile(
    r"^.{1,300}\s+[-–—]\s+(?:https?://|javascript:|data:)\S+\s*$",
    re.IGNORECASE,
)
_FENCE_OPEN = re.compile(r"^ {0,3}(`{3,}|~{3,})")


def _canonical_http_url(value: object) -> tuple[str, str, str] | None:
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or "\\" in candidate or any(char.isspace() or ord(char) < 32 for char in candidate):
        return None

    try:
        parsed = urlsplit(candidate)
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except ValueError:
        return None
    if scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return None

    try:
        host = hostname.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    if ":" in hostname:
        try:
            ipaddress.IPv6Address(hostname)
        except ValueError:
            return None
        netloc_host = f"[{host}]"
    else:
        if not re.fullmatch(r"[a-z0-9.-]+", host) or host.startswith(".") or ".." in host:
            return None
        netloc_host = host

    if port == (80 if scheme == "http" else 443):
        port = None
    netloc = netloc_host + (f":{port}" if port is not None else "")
    canonical = urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))
    return canonical, host, candidate


def _source_metadata(tool_executions: list[dict] | None) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    seen: set[str] = set()
    for execution in tool_executions or []:
        if not isinstance(execution, dict) or execution.get("name") != "web_search":
            continue
        if execution.get("status") != "completed":
            continue
        result = execution.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                continue
        if not isinstance(result, dict) or result.get("status") not in {"success", "partial"}:
            continue
        rows = result.get("results")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            canonical = _canonical_http_url(row.get("url"))
            if canonical is None:
                continue
            dedupe_key, domain, url = canonical
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            raw_title = row.get("title")
            title = raw_title.strip() if isinstance(raw_title, str) else ""
            title = " ".join(title.split())[:300] or domain
            sources.append((title, url))
    return sources


def _is_source_entry(line: str) -> bool:
    line = line.strip()
    return not line or bool(
        _LISTED_SOURCE_ENTRY.fullmatch(line)
        or _UNNUMBERED_SOURCE_ENTRY.fullmatch(line)
        or _SOURCE_ENTRY.fullmatch(line)
    )


def _strip_model_sources_block(answer: str) -> str:
    lines = answer.strip().splitlines()
    if not lines:
        return ""

    output: list[str] = []
    in_fence: tuple[str, int] | None = None
    index = 0
    while index < len(lines):
        line = lines[index]
        fence = _FENCE_OPEN.match(line)
        if in_fence:
            output.append(line)
            if fence and fence.group(1)[0] == in_fence[0] and len(fence.group(1)) >= in_fence[1]:
                in_fence = None
            index += 1
            continue
        if fence:
            in_fence = (fence.group(1)[0], len(fence.group(1)))
            output.append(line)
            index += 1
            continue
        if not _SOURCE_HEADER.fullmatch(line.strip()):
            output.append(line)
            index += 1
            continue

        # Remove a separator that introduces this model-authored section, but
        # leave answer prose and fenced examples around it intact.
        if output and output[-1].strip() == "---":
            output.pop()
            while output and not output[-1].strip():
                output.pop()

        index += 1
        blank_lines: list[str] = []
        found_entries = False
        while index < len(lines):
            candidate = lines[index]
            candidate_fence = _FENCE_OPEN.match(candidate)
            if candidate_fence:
                output.extend(blank_lines)
                break
            if not candidate.strip():
                blank_lines.append(candidate)
                index += 1
                continue
            if candidate.strip() == "---":
                blank_lines.clear()
                index += 1
                continue
            if _is_source_entry(candidate):
                found_entries = found_entries or bool(candidate.strip())
                blank_lines.clear()
                index += 1
                continue
            output.extend(blank_lines)
            break

    return "\n".join(output).strip()


def append_retrieved_sources(answer: str, tool_executions: list[dict] | None, locale: str | None = None) -> str:
    """Replace any model-authored footer with unique safe search result URLs."""
    body = _strip_model_sources_block(answer)
    sources = _source_metadata(tool_executions)
    if not sources:
        return body

    heading = "Источники" if (locale or "").lower().startswith("ru") else "Sources"
    entries = []
    for index, (title, url) in enumerate(sources, 1):
        encoded_title = base64.urlsafe_b64encode(title.encode("utf-8", errors="replace")).decode("ascii").rstrip("=")
        entries.append(f"[{index}] quip-source-v1:{encoded_title} - {url}")
    footer = f"---\n**{heading}:**\n" + "\n".join(entries)
    return f"{body}\n\n{footer}" if body else footer
