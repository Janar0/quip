"""Request and response schemas for authenticated voice calls."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class VoiceCallStartRequest(BaseModel):
    chat_id: UUID
    sdp: str = Field(min_length=1, max_length=131_072)
    type: Literal["offer"]

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
