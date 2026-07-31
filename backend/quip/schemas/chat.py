from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChatCreate(BaseModel):
    title: str | None = "New Chat"
    model: str | None = None
    workspace_id: UUID | None = None


class ChatUpdate(BaseModel):
    title: str | None = None
    model: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    workspace_id: UUID | None = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    workspace_id: UUID | None = None
    title: str
    model: str | None = None
    source: str = "web"
    external_chat_id: str | None = None
    external_thread_id: str | None = None
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_id: UUID
    parent_id: UUID | None = None
    role: str
    content: str | None = None
    reasoning: str | None = None
    model: str | None = None
    provider: str | None = None
    token_count: int | None = None
    cost: Decimal | None = None
    artifacts: list[dict] | None = None
    tool_calls: list[dict] | None = None
    meta: dict | None = None
    created_at: datetime

    attachments: list[dict] | None = None
    search_images: list[dict] | None = None

    @model_validator(mode="after")
    def extract_meta_fields(self):
        if self.meta:
            if self.reasoning is None and "reasoning" in self.meta:
                self.reasoning = self.meta["reasoning"]
            if "attachments" in self.meta:
                self.attachments = self.meta["attachments"]
            if "search_images" in self.meta:
                self.search_images = self.meta["search_images"]
        self.meta = None
        return self


class ChatRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_id: UUID
    assistant_message_id: UUID | None = None
    status: str
    model: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class ChatWithMessages(ChatResponse):
    messages: list[MessageResponse] = Field(default_factory=list)
    runs: list[ChatRunResponse] = Field(default_factory=list)


class CompletionRequest(BaseModel):
    """Request for chat completion — sent from frontend."""
    chat_id: UUID | None = None  # None = create new chat
    workspace_id: UUID | None = None
    model: str
    message: str  # user's message text
    file_ids: list[UUID] = Field(default_factory=list)  # attached file IDs
    mode_hint: str | None = None  # "auto" | "search" — fast search mode dispatch
    branch_from_message_id: UUID | None = None  # branch edit: create sibling of this message
    max_tokens: int | None = None  # optional max tokens for response generation


class RegenerateRequest(BaseModel):
    """Regenerate an assistant response — creates a sibling branch."""
    chat_id: UUID
    message_id: UUID  # the assistant message to regenerate
    model: str | None = None  # optional: use different model
