import asyncio
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional

from quip.providers.openrouter import UsageInfo


class ResearchLimitReached(RuntimeError):
    """Raised before a new provider/tool call would cross a run bound."""


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
    max_child_agents: int = 8
    max_concurrent_agents: int = 3
    max_runtime_seconds: int = 600
    max_cost_usd: float = 1.0
    max_orchestrator_rounds: int = 20
    max_subagent_rounds: int = 15
    max_web_searches: int = 100
    steering_reader: Callable[[], Awaitable[list[dict[str, Any]]]] | None = None

    handles: dict[str, SubAgentHandle] = field(default_factory=dict)
    result_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_scope: asyncio.Event = field(default_factory=asyncio.Event)
    total_usage: UsageInfo = field(default_factory=UsageInfo)
    subagent_generations: list[str] = field(default_factory=list)
    web_search_count: int = 0
    loaded_skills: set[str] = field(default_factory=set)
    spawned_children: int = 0
    started_at: float = field(default_factory=time.monotonic)
    child_slots: asyncio.Semaphore = field(init=False)
    provider_call_lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)

    def __post_init__(self) -> None:
        self.child_slots = asyncio.Semaphore(max(1, self.max_concurrent_agents))

    def ensure_can_start_call(self) -> None:
        if self.cancel_scope.is_set():
            raise asyncio.CancelledError
        if time.monotonic() - self.started_at >= self.max_runtime_seconds:
            raise ResearchLimitReached("research runtime limit reached")
        if self.total_usage.cost >= self.max_cost_usd:
            raise ResearchLimitReached("research known-cost limit reached")

    @asynccontextmanager
    async def admit_provider_call(self) -> AsyncIterator[None]:
        """Serialize provider streams so reported cost is refreshed before admission."""
        async with self.provider_call_lock:
            self.ensure_can_start_call()
            yield

    def reserve_child(self) -> bool:
        if self.cancel_scope.is_set() or self.spawned_children >= self.max_child_agents:
            return False
        self.spawned_children += 1
        return True

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
