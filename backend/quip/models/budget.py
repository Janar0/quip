import uuid

from sqlalchemy import Column, String, DateTime, Numeric, Uuid, ForeignKey, func

from quip.database import Base


class Budget(Base):
    """Per-user or global budget limits.

    user_id=null → global limit for all users.
    period: 'daily', 'monthly'
    """
    __tablename__ = "budgets"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    period = Column(String(20), nullable=False, default="monthly")  # daily, monthly
    limit_usd = Column(Numeric(10, 2), nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
