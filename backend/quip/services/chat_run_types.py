"""Shared run contracts and resource limits."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

ACTIVE_STATUSES = ("queued", "running", "cancelling")
CANCELLABLE_STATUSES = ("queued", "running")
TERMINAL_STATUSES = {"completed", "partial", "failed", "cancelled", "interrupted"}
MAX_REPORT_CHARS = 200_000
MAX_SNAPSHOT_BYTES = 48_000
MAX_SOURCE_URL_BYTES = 2_048
MAX_SOURCE_TITLE_BYTES = 512
MAX_STEERING_ITEMS = 4
MAX_STEERING_CHARS = 2_000
SUBSCRIBER_QUEUE_SIZE = 64
RUNNER_LEASE_TTL_SECONDS = 30
RUNNER_HEARTBEAT_INTERVAL_SECONDS = 5
METADATA_WRITE_SEQUENCE_KEY = "_write_sequence"
MAX_METADATA_WRITE_RETRIES = 12


@dataclass(frozen=True)
class ChatRunSpec:
    run_id: UUID
    chat_id: UUID
    user_id: UUID
    assistant_message_id: UUID
    task_kind: str
    context_version: int = 1
    timeout_seconds: int = 600


@dataclass
class RunOutcome:
    status: str = "completed"
    error: str | None = None
    usage: dict[str, Any] | None = None
    reasoning: str = ""
    artifacts: list[dict] | None = None
    subagent_generations: list[str] | None = None


@dataclass(frozen=True)
class RunFinishDecision:
    """Atomic worker/manager handshake for closing steering before persistence."""

    accepted: bool
    status: str
    context_version: int
    steering: list[dict[str, Any]]
