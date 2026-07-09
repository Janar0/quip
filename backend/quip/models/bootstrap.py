from sqlalchemy import Boolean, Column, DateTime, Integer, Uuid, func

from quip.database import Base


class BootstrapState(Base):
    """Single-row guard that makes first-admin creation atomic."""

    __tablename__ = "bootstrap_state"

    id = Column(Integer, primary_key=True, default=1)
    completed = Column(Boolean, nullable=False, default=False)
    claimed_by = Column(Uuid)
    completed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
