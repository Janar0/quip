from quip.services.tools import (
    LOAD_SKILL_TOOL,
    READ_URL_TOOL,
    SEARCH_TOOLS,
    SANDBOX_TOOLS,
)


# --- Spawn tool specs ---

SPAWN_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_search_agent",
        "description": (
            "Launch a search sub-agent to research a goal. Returns a task_id immediately; "
            "the sub-agent runs in parallel and pushes its result into the shared queue. "
            "Use wait_for_any_result to consume results as they arrive."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "The research goal in one or two sentences.",
                },
                "max_queries": {
                    "type": "integer",
                    "default": 30,
                    "description": "Soft budget for web_search calls inside this sub-agent.",
                },
            },
            "required": ["goal"],
        },
    },
}

SPAWN_SANDBOX_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_sandbox_agent",
        "description": (
            "Launch a sandbox sub-agent to run code / build charts / process data. "
            "Returns a task_id immediately."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "What the sub-agent should compute or produce, including any input values.",
                },
            },
            "required": ["task"],
        },
    },
}

SPAWN_ARTIFACT_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_artifact_agent",
        "description": (
            "Launch a single-turn artifact sub-agent that renders a plot / chart / table / "
            "mermaid / svg / html artifact from a short spec. Returns the artifact tag as the result."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": ["plot", "chart", "table", "mermaid", "svg", "html", "code"],
                    "description": "Artifact type.",
                },
                "spec": {
                    "type": "string",
                    "description": "Plain-language or structured spec describing what to render.",
                },
            },
            "required": ["kind", "spec"],
        },
    },
}

WAIT_FOR_ANY_RESULT_TOOL = {
    "type": "function",
    "function": {
        "name": "wait_for_any_result",
        "description": (
            "Block until the next pending sub-agent finishes and return its result. "
            "Does not block the event loop."
        ),
        "parameters": {"type": "object", "properties": {}},
    },
}

COLLECT_AGENT_RESULT_TOOL = {
    "type": "function",
    "function": {
        "name": "collect_agent_result",
        "description": "Non-blocking snapshot of a specific sub-agent's status and result.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
            },
            "required": ["task_id"],
        },
    },
}

LIST_AGENTS_TOOL = {
    "type": "function",
    "function": {
        "name": "list_agents",
        "description": "List all sub-agents in this research session with their status.",
        "parameters": {"type": "object", "properties": {}},
    },
}

ORCHESTRATOR_TOOLS = [
    LOAD_SKILL_TOOL,
    SPAWN_SEARCH_TOOL,
    SPAWN_SANDBOX_TOOL,
    SPAWN_ARTIFACT_TOOL,
    WAIT_FOR_ANY_RESULT_TOOL,
    COLLECT_AGENT_RESULT_TOOL,
    LIST_AGENTS_TOOL,
]
