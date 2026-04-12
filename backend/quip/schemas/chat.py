from pydantic import BaseModel, ConfigDict, model_validator
from uuid import UUID
from datetime import datetime
from typing import Optional
from decimal import Decimal


class ChatCreate(BaseModel):
    title: Optional[str] = "New Chat"
    model: Optional[str] = None


class ChatUpdate(BaseModel):
    title: Optional[str] = None
    model: Optional[str] = None
    pinned: Optional[bool] = None
    archived: Optional[bool] = None


class ChatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str
    model: Optional[str] = None
    pinned: bool
    archived: bool
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    chat_id: UUID
    parent_id: Optional[UUID] = None
    role: str
    content: Optional[str] = None
    reasoning: Optional[str] = None
    model: Optional[str] = None
    provider: Optional[str] = None
    token_count: Optional[int] = None
    cost: Optional[Decimal] = None
    artifacts: Optional[list[dict]] = None
    tool_calls: Optional[list[dict]] = None
    meta: Optional[dict] = None
    created_at: datetime

    attachments: Optional[list[dict]] = None
    search_images: Optional[list[dict]] = None

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


class ChatWithMessages(ChatResponse):
    messages: list[MessageResponse] = []


class CompletionRequest(BaseModel):
    """Request for chat completion — sent from frontend."""
    chat_id: Optional[UUID] = None  # None = create new chat
    model: str
    message: str  # user's message text
    file_ids: list[UUID] = []  # attached file IDs
    deep_research: bool = False  # use deep research pipeline
    mode_hint: Optional[str] = None  # "auto" | "search" | "research" — fast search mode dispatch
    branch_from_message_id: Optional[UUID] = None  # branch edit: create sibling of this message


class RegenerateRequest(BaseModel):
    """Regenerate an assistant response — creates a sibling branch."""
    chat_id: UUID
    message_id: UUID  # the assistant message to regenerate
    model: Optional[str] = None  # optional: use different model
