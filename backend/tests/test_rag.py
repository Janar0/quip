"""Tests for RAG — cosine similarity, retrieval, and context formatting."""
import pytest
from uuid import UUID
from unittest.mock import patch, AsyncMock

from quip.services.rag import cosine_similarity, format_rag_context, retrieve_context
from quip.services.config import set_setting
from quip.models.file import File, DocumentChunk
from quip.models.user import User
from quip.models.chat import Chat


# ── Unit tests ──────────────────────────────────────────────────────────────


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.5]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


def test_format_rag_context():
    chunks = [
        {"filename": "doc.pdf", "content": "Hello world", "chunk_index": 0, "score": 0.9},
        {"filename": "notes.md", "content": "Important note", "chunk_index": 1, "score": 0.7},
    ]
    result = format_rag_context(chunks)
    assert "[Retrieved Context]" in result
    assert "[1] doc.pdf:" in result
    assert "Hello world" in result
    assert "[2] notes.md:" in result
    assert "[/Retrieved Context]" in result


def test_format_rag_context_empty():
    assert format_rag_context([]) == ""


# ── Integration test ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_context_ranks_by_similarity(db_session):
    """Seed 3 chunks with known embeddings → retrieve top 2 → ranked correctly."""
    # Create user + chat + file
    user = User(email="rag@test.dev", username="raguser", name="RAG Tester", role="admin")
    db_session.add(user)
    await db_session.flush()

    chat = Chat(user_id=user.id, title="RAG test")
    db_session.add(chat)
    await db_session.flush()

    file_rec = File(
        user_id=user.id, chat_id=chat.id, filename="test.txt",
        content_type="text/plain", size=100, file_type="document",
        storage_path="fake/path.txt", embedding_status="completed",
    )
    db_session.add(file_rec)
    await db_session.flush()

    # Three chunks with orthogonal embeddings
    chunks_data = [
        ("Python is a programming language", [1.0, 0.0, 0.0]),
        ("The weather is sunny today", [0.0, 1.0, 0.0]),
        ("Machine learning uses data", [0.7, 0.0, 0.7]),
    ]
    for i, (text, emb) in enumerate(chunks_data):
        db_session.add(DocumentChunk(
            file_id=file_rec.id, chat_id=chat.id,
            chunk_index=i, content=text,
            embedding=emb, token_count=10,
        ))
    await db_session.commit()

    # Query vector close to chunk 0 (Python)
    with patch("quip.services.rag.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.9, 0.1, 0.0]]):
        results = await retrieve_context("What is Python?", chat.id, db_session, top_k=2)

    assert len(results) == 2
    assert "Python" in results[0]["content"]
    assert results[0]["score"] > results[1]["score"]


@pytest.mark.asyncio
async def test_retrieve_context_no_documents(db_session):
    """Chat with no embedded documents → empty results."""
    user = User(email="empty@test.dev", username="emptyuser", name="E", role="admin")
    db_session.add(user)
    await db_session.flush()

    chat = Chat(user_id=user.id, title="Empty chat")
    db_session.add(chat)
    await db_session.commit()

    results = await retrieve_context("anything", chat.id, db_session)
    assert results == []
