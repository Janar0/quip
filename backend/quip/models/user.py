import uuid

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Uuid, func

from quip.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    telegram_user_id = Column(String(100), unique=True, index=True)
    name = Column(String(255), nullable=False)
    role = Column(String(20), nullable=False, default="pending")
    profile_image_url = Column(String(500))
    settings = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    last_active_at = Column(DateTime(timezone=True))


class Auth(Base):
    __tablename__ = "auths"

    id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TelegramLinkToken(Base):
    """Short-lived, single-use token for linking a Telegram account."""

    __tablename__ = "telegram_link_tokens"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    telegram_user_id = Column(String(100), nullable=True, index=True)
    token_hash = Column(String(128), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TelegramUpdate(Base):
    """Durable Telegram update queue used by the polling worker."""

    __tablename__ = "telegram_updates"

    update_id = Column(Integer, primary_key=True)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    locked_at = Column(DateTime(timezone=True))
    processed_at = Column(DateTime(timezone=True))
    last_error = Column(String(1000))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False)
    name = Column(String(100))
    expires_at = Column(DateTime(timezone=True))
    last_used_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
