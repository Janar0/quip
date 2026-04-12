import uuid

from sqlalchemy import Column, String, Boolean, DateTime, Integer, Numeric, Uuid, ForeignKey, func

from quip.database import Base


class UsageLog(Base):
    __tablename__ = "usage_log"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    chat_id = Column(Uuid, ForeignKey("chats.id"))
    message_id = Column(Uuid, ForeignKey("messages.id"))
    model = Column(String(255), nullable=False)
    provider = Column(String(100))
    prompt_tokens = Column(Integer, nullable=False, default=0)
    completion_tokens = Column(Integer, nullable=False, default=0)
    cached_tokens = Column(Integer, default=0)
    cost = Column(Numeric(12, 8), nullable=False, default=0)
    is_byok = Column(Boolean, default=False)
    generation_id = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
