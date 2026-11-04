from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Uuid

from quip.database import Base


class OidcCode(Base):
    """A single-use OpenID Connect authorization code, stored only as its hash."""

    __tablename__ = "oidc_codes"

    code_hash = Column(String(64), primary_key=True)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    redirect_uri = Column(String(500), nullable=False)
    code_challenge = Column(String(128), nullable=False)
    nonce = Column(String(255))
    expires_at = Column(Integer, nullable=False, index=True)
    consumed = Column(Boolean, nullable=False, default=False)
