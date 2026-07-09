from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    instructions: str | None = Field(default=None, max_length=20000)
    default_model: str | None = Field(default=None, max_length=255)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    instructions: str | None = Field(default=None, max_length=20000)
    default_model: str | None = Field(default=None, max_length=255)


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    owner_id: UUID
    name: str
    description: str | None = None
    instructions: str | None = None
    default_model: str | None = None
    is_personal: bool
    created_at: datetime
    updated_at: datetime


class WorkspaceFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str | None = None
    size: int | None = None
    file_type: str | None = None
    embedding_status: str | None = None
    created_at: datetime
