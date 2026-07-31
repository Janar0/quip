import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func

from quip.database import Base


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    workspace_id = Column(
        Uuid,
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String(500), default="New Chat")
    model = Column(String(255))
    source = Column(String(20), nullable=False, default="web", index=True)
    external_chat_id = Column(String(100), index=True)
    external_thread_id = Column(String(100), index=True)
    pinned = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    share_id = Column(String(100), unique=True)
    meta = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    @property
    def emoji(self) -> str | None:
        """Optional chat emoji stored alongside other chat metadata."""
        value = (self.meta or {}).get("emoji")
        return value if isinstance(value, str) else None


class Message(Base):
    __tablename__ = "messages"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_id = Column(Uuid, ForeignKey("messages.id"))
    role = Column(String(20), nullable=False)  # user, assistant, system, tool
    content = Column(Text)
    model = Column(String(255))
    provider = Column(String(100))
    tool_calls = Column(JSON)
    artifacts = Column(JSON)
    token_count = Column(Integer)
    cost = Column(Numeric(12, 8))
    meta = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChatRun(Base):
    """Durable lifecycle record for one assistant generation."""

    __tablename__ = "chat_runs"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    chat_id = Column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    assistant_message_id = Column(
        Uuid,
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String(20), nullable=False, default="queued", index=True)
    model = Column(String(255))
    error = Column(Text)
    run_metadata = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True))
    finished_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
