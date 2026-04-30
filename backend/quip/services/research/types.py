import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from quip.providers.openrouter import UsageInfo


# --- Orchestrator limits ---
ORCHESTRATOR_MAX_ROUNDS = 20
SUB_AGENT_MAX_ROUNDS = 15
SESSION_WEB_SEARCH_BUDGET = 100


# --- Events ---

@dataclass
class ResearchEvent:
    """Queued event — either a status update or a content chunk."""
    type: str
    data: dict = field(default_factory=dict)


StatusCallback = Callable[[ResearchEvent], Awaitable[None]]


# --- Session state ---

@dataclass
class SubAgentHandle:
    task_id: str
    kind: str  # "search" | "sandbox" | "artifact"
    task: asyncio.Task
    status: str = "running"  # running | done | error | cancelled
    result: Optional[dict] = None
    usage: Optional[UsageInfo] = None
    started_at: float = field(default_factory=time.monotonic)


@dataclass
class ResearchSession:
    query: str
    emit: StatusCallback
    model: str
    is_ollama: bool
    api_key: str
    ollama_url: str
    locale: Optional[str] = None
    location: Optional[str] = None

    handles: dict[str, SubAgentHandle] = field(default_factory=dict)
    result_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_scope: asyncio.Event = field(default_factory=asyncio.Event)
    total_usage: UsageInfo = field(default_factory=UsageInfo)
    subagent_generations: list[str] = field(default_factory=list)
    web_search_count: int = 0
    loaded_skills: set[str] = field(default_factory=set)

    def next_task_id(self, kind: str) -> str:
        return f"{kind}-{uuid.uuid4().hex[:8]}"

    def add_usage(self, u: Optional[UsageInfo]) -> None:
        if not u:
            return
        self.total_usage.prompt_tokens += u.prompt_tokens
        self.total_usage.completion_tokens += u.completion_tokens
        self.total_usage.cached_tokens += u.cached_tokens
        self.total_usage.cost += u.cost or 0.0
        if u.generation_id:
            self.subagent_generations.append(u.generation_id)
        if u.provider and not self.total_usage.provider:
            self.total_usage.provider = u.provider
