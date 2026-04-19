"""Tool definitions and dispatch for OpenRouter/Ollama function calling.

Tool descriptions are intentionally terse. Detailed usage instructions live in
the skill registry (services/skill_store.py) and are fetched on demand via the
`load_skill` tool. This keeps the default tool payload small.
"""
import json
from dataclasses import dataclass, field
from typing import Optional

from quip.providers.openrouter import ToolCallDelta
from quip.services.sandbox import SandboxManager, ExecutionResult


SANDBOX_TOOL_NAMES = {
    "sandbox_execute",
    "sandbox_install",
    "sandbox_write_file",
    "sandbox_read_file",
    "sandbox_list_files",
}


LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "Fetch detailed instructions for a named skill from the skill registry. "
            "Call this before using a capability whose specifics you don't remember "
            "(e.g. `sandbox`, `artifact_plot`, `web_search`, `fast_search`)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "The skill name, from the 'Available skills' index in the system prompt.",
                },
            },
            "required": ["name"],
        },
    },
}


SANDBOX_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_execute",
            "description": "Run code in an isolated sandbox (Python/Node/bash). Call load_skill('sandbox') for details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "The code to execute"},
                    "language": {
                        "type": "string",
                        "enum": ["python", "javascript", "bash"],
                        "description": "Programming language",
                    },
                },
                "required": ["code", "language"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_install",
            "description": "Install packages in the sandbox. See load_skill('sandbox').",
            "parameters": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Package names to install",
                    },
                    "manager": {
                        "type": "string",
                        "enum": ["pip", "npm"],
                        "default": "pip",
                        "description": "Package manager",
                    },
                },
                "required": ["packages"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_write_file",
            "description": "Write a file to the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_read_file",
            "description": "Read a file from the sandbox workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path relative to workspace root"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sandbox_list_files",
            "description": "List files in the sandbox workspace directory.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path relative to workspace root",
                        "default": ".",
                    },
                },
            },
        },
    },
]

SEARCH_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web. Call load_skill('web_search') for usage details.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query — specific and concise",
                    },
                },
                "required": ["query"],
            },
        },
    },
]

READ_URL_TOOL = {
    "type": "function",
    "function": {
        "name": "read_url",
        "description": (
            "Fetch the full content of a web page. "
            "Use proactively when the user shares an http/https link in their message. "
            "Also use to read a specific page from search results."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch",
                },
            },
            "required": ["url"],
        },
    },
}

GENERATE_MUSIC_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_music",
        "description": "Generate AI music/audio. Call load_skill('music_generation') for details.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Detailed description of the music: genre, instruments, BPM, mood, atmosphere",
                },
            },
            "required": ["prompt"],
        },
    },
}

GENERATE_IMAGE_TOOL = {
    "type": "function",
    "function": {
        "name": "generate_image",
        "description": "Generate or edit images with AI. Call load_skill('image_generation') for details.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Text description of the image to generate or edit",
                },
                "image_urls": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: URLs of reference images to edit or style-transfer from",
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["1:1", "16:9", "9:16", "4:3", "3:4"],
                    "description": "Aspect ratio of the output image (default: 1:1)",
                },
                "image_size": {
                    "type": "string",
                    "enum": ["0.5K", "1K", "2K", "4K"],
                    "description": "Resolution (default: 1K)",
                },
                "hidden": {
                    "type": "boolean",
                    "description": (
                        "If true, the generated image is NOT rendered as a standalone preview in the chat. "
                        "Use this when you plan to embed the image into a widget (e.g. recipe hero) or "
                        "insert it inline in your text yourself via markdown. Default: false."
                    ),
                },
            },
            "required": ["prompt"],
        },
    },
}

WIDGET_TOOL = {
    "type": "function",
    "function": {
        "name": "use_widget",
        "description": (
            "Render a visual widget card in the chat. "
            "For API widgets: pass params. For content widgets: pass data with all fields filled. "
            "Call load_skill(name) first with the widget name from the 'Available skills' index "
            "to get its data schema, then call use_widget."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Widget template name from the skill index",
                },
                "params": {
                    "type": "object",
                    "description": "Query parameters for API widgets",
                },
                "data": {
                    "type": "object",
                    "description": "Complete data object for content widgets",
                },
            },
            "required": ["name"],
        },
    },
}


@dataclass
class AccumulatedToolCall:
    """A complete tool call accumulated from streaming deltas."""
    index: int = 0
    id: str = ""
    function_name: str = ""
    function_arguments: str = ""


def accumulate_tool_calls(
    accumulated: list[AccumulatedToolCall], deltas: list[ToolCallDelta]
) -> None:
    """Merge streaming tool call deltas into accumulated tool calls."""
    for delta in deltas:
        # Find or create the accumulated entry for this index
        existing = None
        for tc in accumulated:
            if tc.index == delta.index:
                existing = tc
                break

        if existing is None:
            existing = AccumulatedToolCall(index=delta.index)
            accumulated.append(existing)

        # Merge fields — id and name come once, arguments accumulate
        if delta.id:
            existing.id = delta.id
        if delta.function_name:
            existing.function_name = delta.function_name
        existing.function_arguments += delta.function_arguments


def _normalize_widget_strings(obj):
    """Convert literal backslash-n sequences into real newlines recursively.
    Models sometimes emit "\\n" inside JSON string values instead of "\n"."""
    if isinstance(obj, str):
        return obj.replace("\\n", "\n").replace("\\t", "\t")
    if isinstance(obj, list):
        return [_normalize_widget_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _normalize_widget_strings(v) for k, v in obj.items()}
    return obj


async def execute_tool_call(
    manager: SandboxManager,
    sandbox,
    chat_id: str,
    tool_name: str,
    arguments_json: str,
    db=None,
    loaded_skills: Optional[set[str]] = None,
) -> str:
    """Dispatch a tool call to the sandbox manager. Returns JSON result string."""
    try:
        args = json.loads(arguments_json) if arguments_json else {}
    except json.JSONDecodeError:
        return json.dumps({"error": f"Invalid JSON arguments: {arguments_json[:200]}"})

    try:
        # Skill registry lookup — returns full skill body as tool result
        if tool_name == "load_skill":
            from quip.services.skill_store import get_skill
            name = args.get("name", "").strip()
            if not name:
                return json.dumps({"error": "missing skill name"})
            if loaded_skills is not None and name in loaded_skills:
                return json.dumps({
                    "skill": name,
                    "already_loaded": True,
                    "hint": "You already loaded this skill earlier in the conversation — see the previous tool result.",
                })
            skill = get_skill(name)
            if not skill or not skill.enabled or skill.is_internal:
                return json.dumps({"error": f"unknown skill: {name}"})
            if loaded_skills is not None:
                loaded_skills.add(name)
            result = {"skill": skill.id, "instructions": skill.prompt_instructions}
            if skill.category == "widget" and skill.data_schema:
                result["data_schema"] = skill.data_schema
                result["widget_type"] = skill.type
            return json.dumps(result)

        # Search tools (no sandbox needed)
        if tool_name == "web_search":
            from quip.services.search import web_search
            results, images = await web_search(args.get("query", ""))
            return json.dumps({
                "results": [
                    {"title": r.title, "url": r.url, "snippet": r.snippet, "content": r.content}
                    for r in results
                ],
                "images": [
                    {"img_src": i.img_src, "source_url": i.source_url, "title": i.title}
                    for i in images
                ],
            })

        elif tool_name == "read_url":
            from quip.services.scraper import read_url
            content = await read_url(args.get("url", ""))
            return json.dumps({"content": content, "url": args.get("url", "")})

        # Sandbox tools
        elif tool_name == "sandbox_execute":
            result = await manager.execute(
                sandbox,
                chat_id,
                code=args.get("code", ""),
                language=args.get("language", "python"),
            )
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
                "files_created": result.files_created,
            })

        elif tool_name == "sandbox_install":
            result = await manager.install_packages(
                sandbox,
                packages=args.get("packages", []),
                manager=args.get("manager", "pip"),
                db=db,
            )
            return json.dumps({
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.exit_code,
            })

        elif tool_name == "sandbox_write_file":
            content = args.get("content", "")
            await manager.write_file(sandbox, chat_id, args["path"], content.encode())
            return json.dumps({"status": "ok", "path": args["path"]})

        elif tool_name == "sandbox_read_file":
            data = await manager.read_file(sandbox, chat_id, args["path"])
            # Try text, fall back to indicating binary
            try:
                text = data.decode("utf-8")
                if len(text) > 50000:
                    text = text[:50000] + "\n... (truncated)"
                return json.dumps({"content": text, "path": args["path"]})
            except UnicodeDecodeError:
                return json.dumps({"content": f"(binary file, {len(data)} bytes)", "path": args["path"]})

        elif tool_name == "sandbox_list_files":
            files = await manager.list_files(sandbox, chat_id, args.get("path", "."))
            return json.dumps({
                "files": [
                    {"name": f.name, "path": f.path, "size": f.size, "is_dir": f.is_dir}
                    for f in files
                ]
            })

        elif tool_name == "generate_image":
            from quip.services.image_gen import generate_image
            from quip.services.config import get_setting
            from quip.services.skill_store import get_skill_setting
            model = get_skill_setting("image_generation", "model", "") or "google/gemini-2.0-flash-exp:free"
            api_key = get_setting("openrouter_api_key", "")
            result = await generate_image(
                prompt=args.get("prompt", ""),
                image_urls=args.get("image_urls") or [],
                aspect_ratio=args.get("aspect_ratio", "1:1"),
                image_size=args.get("image_size", "1K"),
                model=model,
                api_key=api_key,
                db=db,
            )
            if args.get("hidden"):
                result["hidden"] = True
            return json.dumps(result)

        elif tool_name == "generate_music":
            from quip.services.music_gen import generate_music
            from quip.services.config import get_setting
            api_key = get_setting("openrouter_api_key", "")
            result = await generate_music(
                prompt=args.get("prompt", ""),
                api_key=api_key,
            )
            return json.dumps(result)

        elif tool_name == "use_widget":
            from quip.services.skill_store import get_skill
            from quip.services.widget_api import execute_widget_api
            widget_name = args.get("name", "")
            skill = get_skill(widget_name)
            if not skill or skill.category != "widget" or not skill.enabled or skill.is_internal:
                return json.dumps({"error": f"Unknown widget: {widget_name}"})

            if skill.type == "api":
                data = await execute_widget_api(skill, args.get("params", {}))
            else:
                data = args.get("data", {})
                # Post-processing for poll: compute percent
                if widget_name == "poll":
                    total = sum(o.get("votes", 0) for o in data.get("options", []))
                    for o in data.get("options", []):
                        o["percent"] = round(o["votes"] / total * 100) if total > 0 else 0
                    data["total_votes"] = total

            data = _normalize_widget_strings(data)

            return json.dumps({
                "widget": True,
                "template": widget_name,
                "data": data,
            })

        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})

    except ValueError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"Execution error: {str(e)}"})



async def run_tool_call(
    tc: AccumulatedToolCall,
    *,
    sandbox_manager: SandboxManager,
    sandbox,
    chat_id: str,
    loaded_skills: set[str],
) -> str:
    """Execute one accumulated tool call inside its own DB session.

    Centralizes error wrapping so chat_completion and regenerate_message share
    one implementation instead of duplicating the nested helper.
    """
    from quip.database import async_session

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
