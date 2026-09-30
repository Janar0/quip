"""Request and response schemas for authenticated voice calls."""
import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class VoiceCallStartRequest(BaseModel):
    chat_id: UUID
    sdp: str = Field(min_length=1, max_length=131_072)
    type: Literal["offer"]
    camera_enabled: bool = False

    @field_validator("sdp")
    @classmethod
    def require_sdp_session_description(cls, value: str) -> str:
        first_line = value.splitlines()[0].strip() if value.splitlines() else ""
        if first_line != "v=0":
            raise ValueError("Expected a session description offer")
        return value


class VoiceCallStartResponse(BaseModel):
    call_id: UUID
    sdp: str
    type: Literal["answer"] = "answer"


class VoiceCallEndResponse(BaseModel):
    call_id: UUID
    status: Literal["ended"]


class VoiceEventRequest(BaseModel):
    event: dict[str, Any]

    @field_validator("event")
    @classmethod
    def bound_event_size(cls, value: dict[str, Any]) -> dict[str, Any]:
        try:
            size = len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid provider event") from exc
        if size > 64_000:
            raise ValueError("Provider event is too large")
        return value


class VoiceToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_call_id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=80)
    arguments: str = Field(min_length=2, max_length=8_000)


class VoiceToolResponse(BaseModel):
    provider_call_id: str
    name: str
    status: Literal["completed", "failed", "cancelled"]
    result: dict[str, Any]
    replayed: bool = False


class VoiceContextItemResponse(BaseModel):
    source_id: str
    source_type: Literal["chat_message", "document_chunk"]
    speaker: str
    text: str
    title: str | None = None


class VoiceContextResponse(BaseModel):
    chat_id: UUID
    context_version: int
    task_goal: str
    summary: str
    summary_sources: list[str]
    task_state: dict[str, Any]
    recent: list[VoiceContextItemResponse]
    retrieved: list[VoiceContextItemResponse]
    estimated_tokens: int
    instruction: str


class VoiceTaskStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_call_id: str = Field(min_length=1, max_length=160)
    goal: str = Field(min_length=1, max_length=2_000)

    @field_validator("goal")
    @classmethod
    def clean_goal(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Task goal cannot be empty")
        return value


class VoiceTaskSteerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=2_000)

    @field_validator("instruction")
    @classmethod
    def clean_instruction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Instruction cannot be empty")
        return value


class VoiceTaskStartResponse(BaseModel):
    task_id: UUID
    status: str
    model: str
    replayed: bool = False
    steered: bool = False


class VoiceTaskSteerResponse(BaseModel):
    task_id: UUID
    status: str
    revision: int
    context_version: int
    replayed: bool = False
