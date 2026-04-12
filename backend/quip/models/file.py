"""File and DocumentChunk models for uploads, images, and RAG."""
import uuid

from sqlalchemy import Column, String, Integer, Text, DateTime, ForeignKey, Uuid, JSON, func

from quip.database import Base


class File(Base):
    __tablename__ = "files"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=True, index=True)
    filename = Column(String(500), nullable=False)
    content_type = Column(String(200))
    size = Column(Integer)
    file_type = Column(String(20))  # "image" or "document"
    storage_path = Column(String(1000), nullable=False)
    hash = Column(String(64))
    embedding_status = Column(String(20), default="pending")  # pending/processing/completed/failed/skipped
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    file_id = Column(Uuid, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id = Column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=True, index=True)
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    embedding = Column(JSON)
    token_count = Column(Integer)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
