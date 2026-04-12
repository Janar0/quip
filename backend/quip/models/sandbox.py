import uuid

from sqlalchemy import Column, String, DateTime, Uuid, ForeignKey, func

from quip.database import Base


class Sandbox(Base):
    __tablename__ = "sandboxes"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    container_id = Column(String(100))
    container_name = Column(String(200))
    volume_name = Column(String(200))
    image_tag = Column(String(300))
    status = Column(String(20), default="created")
    last_active_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())
