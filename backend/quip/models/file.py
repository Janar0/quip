"""File and DocumentChunk models for uploads, images, and RAG."""
import uuid

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, Uuid, func

from quip.database import Base


class File(Base):
    __tablename__ = "files"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(
        Uuid,
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
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
    chunk_metadata = Column(JSON, nullable=True)  # {"page": 3, "image_refs": [...], "source": "ocr"|"text"}
    content_hash = Column(String(64), nullable=True, index=True)  # SHA-256 hex — dedup across files
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DocumentImage(Base):
    __tablename__ = "document_images"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    file_id = Column(Uuid, ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True)
    ref = Column(String(64), nullable=False, index=True)  # marker like "img_1"
    page = Column(Integer, nullable=True)
    storage_path = Column(String(1000), nullable=False)
    mime = Column(String(100))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
