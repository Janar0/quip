"""Persistent metadata for direct-media voice calls and their Quip tool calls."""
import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid, func

from quip.database import Base


class VoiceCall(Base):
    __tablename__ = "voice_calls"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(40), nullable=False, default="qwen")
    model = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="connecting", index=True)
    error_code = Column(String(80))
    context_version = Column(String(80))
    camera_enabled = Column(Boolean, nullable=False, default=False)
    client_usage = Column(JSON, nullable=False, default=dict)
    meta = Column(JSON, nullable=False, default=dict)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    connected_at = Column(DateTime(timezone=True))
    ended_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class VoiceToolCall(Base):
    __tablename__ = "voice_tool_calls"
    __table_args__ = (
        UniqueConstraint("voice_call_id", "provider_call_id", name="uq_voice_tool_call_provider_id"),
    )

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    voice_call_id = Column(Uuid, ForeignKey("voice_calls.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_call_id = Column(String(160), nullable=False)
    function_name = Column(String(80), nullable=False)
    arguments_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    result = Column(JSON)
    result_message_id = Column(Uuid, ForeignKey("messages.id", ondelete="SET NULL"))
    error_code = Column(String(80))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True))
