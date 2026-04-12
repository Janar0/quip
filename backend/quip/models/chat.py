import uuid

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text, ForeignKey, Numeric, Uuid, JSON, func

from quip.database import Base


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(500), default="New Chat")
    model = Column(String(255))
    pinned = Column(Boolean, default=False)
    archived = Column(Boolean, default=False)
    share_id = Column(String(100), unique=True)
    meta = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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
