"""Tests for RAG — cosine similarity, MMR, dedup, retrieval, and context formatting."""
from unittest.mock import AsyncMock, patch

import pytest

from quip.core.config import set_setting
from quip.core.vector_utils import cosine_similarity
from quip.models.chat import Chat
from quip.models.file import DocumentChunk, File
from quip.models.user import User
from quip.services.rag import (
    _mmr_rerank,
    _score_rows,
    format_rag_context,
    retrieve_context,
)

# ── Unit tests: cosine ──────────────────────────────────────────────────────


def test_cosine_similarity_identical():
    v = [1.0, 0.0, 0.5]
    assert cosine_similarity(v, v) == pytest.approx(1.0)


def test_cosine_similarity_orthogonal():
    assert cosine_similarity([1, 0, 0], [0, 1, 0]) == pytest.approx(0.0)


def test_cosine_similarity_opposite():
    assert cosine_similarity([1, 0], [-1, 0]) == pytest.approx(-1.0)


def test_cosine_similarity_zero_vector():
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


# ── Unit tests: scoring ────────────────────────────────────────────────────


def test_score_rows_basic():
    """Scores chunks against query, returns sorted by score desc."""
    rows = [
        (FakeChunk(content="Python code", embedding=[1.0, 0.0], chunk_metadata=None),
         "file1.py", "hash1"),
        (FakeChunk(content="Weather report", embedding=[0.0, 1.0], chunk_metadata=None),
         "file2.txt", "hash2"),
    ]
    query_vec = [0.9, 0.1]
    scored = _score_rows(query_vec, rows)
    assert len(scored) == 2
    assert scored[0]["score"] >= scored[1]["score"]
    assert "Python" in scored[0]["content"]
    assert scored[0]["content_hash"] == "hash1"


def test_score_rows_skips_none_embedding():
    """Chunks without embedding are excluded."""
    rows = [
        (FakeChunk(content="A", embedding=None, chunk_metadata=None), "f.txt", "h1"),
        (FakeChunk(content="B", embedding=[1.0, 0.0], chunk_metadata=None), "g.txt", "h2"),
    ]
    scored = _score_rows([1.0, 0.0], rows)
    assert len(scored) == 1
    assert scored[0]["content"] == "B"


# ── Unit tests: MMR ─────────────────────────────────────────────────────────


def test_mmr_diversifies():
    """MMR re-rank picks diverse content over near-duplicate high scores."""
    scored = [
        {"content": "Python is a great programming language for AI", "score": 0.95, "filename": "a.txt"},
        {"content": "Python is an excellent coding language for ML", "score": 0.93, "filename": "b.txt"},
        {"content": "The weather forecast predicts rain", "score": 0.80, "filename": "c.txt"},
        {"content": "Stock market trends show growth today", "score": 0.75, "filename": "d.txt"},
    ]
    result = _mmr_rerank(scored, top_k=3, lambda_param=0.5)
    assert len(result) == 3
    assert result[0]["score"] == 0.95  # Highest relevance first
    # The second pick should NOT be the near-duplicate (0.93)
    # With lambda=0.5, diversity term dominates, so weather (0.80) beats dupe (0.93)
    assert result[1]["content"] != scored[1]["content"]


def test_mmr_lambda_one_is_pure_relevance():
    """lambda=1 → no diversity penalty → same as top-k by score."""
    scored = [
        {"content": "A python guide", "score": 0.9, "filename": "a.txt"},
        {"content": "A python tutorial", "score": 0.85, "filename": "b.txt"},
        {"content": "Weather news", "score": 0.5, "filename": "c.txt"},
    ]
    result = _mmr_rerank(scored, top_k=2, lambda_param=1.0)
    assert len(result) == 2
    assert result[0]["score"] == 0.9
    assert result[1]["score"] == 0.85


def test_mmr_small_pool():
    """If pool ≤ top_k, return as-is."""
    scored = [{"content": "A", "score": 0.9, "filename": "f.txt"}]
    result = _mmr_rerank(scored, top_k=5, lambda_param=0.7)
    assert len(result) == 1


# ── Unit tests: format_rag_context ──────────────────────────────────────────


def test_format_rag_context():
    chunks = [
        {"filename": "doc.pdf", "content": "Hello world", "chunk_index": 0, "score": 0.9,
         "metadata": {}, "file_id": "f1"},
        {"filename": "notes.md", "content": "Important note", "chunk_index": 1, "score": 0.7,
         "metadata": {}, "file_id": "f2"},
    ]
    result = format_rag_context(chunks)
    assert "[Retrieved Context]" in result
    assert "[1] doc.pdf" in result
    assert "Hello world" in result
    assert "[2] notes.md" in result
    assert "[/Retrieved Context]" in result


def test_format_rag_context_empty():
    assert format_rag_context([]) == ""


def test_format_rag_context_token_budget():
    """Long content gets truncated to fit the max_tokens budget."""
    chunks = [
        {"filename": "big.txt", "content": "X" * 20_000, "chunk_index": 0, "score": 0.9,
         "metadata": {}, "file_id": "f1"},
    ]
    result = format_rag_context(chunks, max_tokens=500)
    assert len(result) < 10_000  # Should be way under 20K chars
    assert "…" in result  # Truncation marker


def test_format_rag_context_archive():
    """Archive chunks appear with [archive] marker, not numbered."""
    chunks = [
        {"filename": "bundle.zip", "content": "[archive: bundle.zip — available at /workspace/...]",
         "chunk_index": 0, "score": 0.0, "metadata": {"source": "archive"}, "file_id": "f1"},
    ]
    result = format_rag_context(chunks)
    assert "[archive]" in result


def test_format_rag_context_ocr():
    """OCR source is labelled in chunk header."""
    chunks = [
        {"filename": "scan.pdf", "content": "Scanned text", "chunk_index": 0, "score": 0.8,
         "metadata": {"source": "ocr"}, "file_id": "f1"},
    ]
    result = format_rag_context(chunks)
    assert "[ocr]" in result


# ── Integration tests ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_context_ranks_by_similarity(db_session):
    """Seed 3 chunks with known embeddings → retrieve top 2 → ranked correctly."""
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

    with patch("quip.services.rag.get_embeddings", new_callable=AsyncMock,
               return_value=[[0.9, 0.1, 0.0]]):
        results = await retrieve_context(
            "What is Python?", chat.id, user.id, db_session, top_k=2
        )

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

    results = await retrieve_context("anything", chat.id, user.id, db_session)
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_context_hash_dedup(db_session):
    """Chunks with identical content_hash → only highest-score kept."""
    user = User(email="dedup@test.dev", username="dedup", name="DD", role="admin")
    db_session.add(user)
    await db_session.flush()

    chat = Chat(user_id=user.id, title="Dedup test")
    db_session.add(chat)
    await db_session.flush()

    file_rec = File(
        user_id=user.id, chat_id=chat.id, filename="doc.txt",
        content_type="text/plain", size=50, file_type="document",
        storage_path="f/f.txt", embedding_status="completed",
    )
    db_session.add(file_rec)
    await db_session.flush()

    # Two chunks with identical hash (duplicate content)
    db_session.add_all([
        DocumentChunk(
            file_id=file_rec.id, chat_id=chat.id,
            chunk_index=0, content="Duplicate content here",
            embedding=[1.0, 0.0], token_count=5,
            content_hash="abc123",
        ),
        DocumentChunk(
            file_id=file_rec.id, chat_id=chat.id,
            chunk_index=1, content="Duplicate content here",
            embedding=[0.9, 0.1], token_count=5,
            content_hash="abc123",  # Same hash
        ),
        DocumentChunk(
            file_id=file_rec.id, chat_id=chat.id,
            chunk_index=2, content="Unique different text",
            embedding=[0.5, 0.5], token_count=5,
            content_hash="xyz789",
        ),
    ])
    await db_session.commit()

    with patch("quip.services.rag.get_embeddings", new_callable=AsyncMock,
               return_value=[[1.0, 0.0]]):
        results = await retrieve_context(
            "test", chat.id, user.id, db_session, top_k=5
        )

    # Should have 2 results: duplicate (best score only) + unique
    contents = [r["content"] for r in results]
    assert contents.count("Duplicate content here") == 1


@pytest.mark.asyncio
async def test_cross_chat_rag_never_reads_another_users_chunks(db_session):
    """Cross-chat retrieval remains restricted to the requesting tenant."""
    set_setting("rag_cross_chat", "true")
    owner = User(
        email="rag-owner@test.dev",
        username="rag-owner",
        name="RAG Owner",
        role="user",
    )
    other = User(
        email="rag-other@test.dev",
        username="rag-other",
        name="RAG Other",
        role="user",
    )
    db_session.add_all([owner, other])
    await db_session.flush()

    current_chat = Chat(user_id=owner.id, title="Current")
    owner_other_chat = Chat(user_id=owner.id, title="Owner other chat")
    foreign_chat = Chat(user_id=other.id, title="Foreign chat")
    db_session.add_all([current_chat, owner_other_chat, foreign_chat])
    await db_session.flush()

    owner_file = File(
        user_id=owner.id,
        chat_id=owner_other_chat.id,
        filename="owner.txt",
        content_type="text/plain",
        size=20,
        file_type="document",
        storage_path="owner/owner.txt",
        embedding_status="completed",
    )
    foreign_file = File(
        user_id=other.id,
        chat_id=foreign_chat.id,
        filename="foreign.txt",
        content_type="text/plain",
        size=20,
        file_type="document",
        storage_path="other/foreign.txt",
        embedding_status="completed",
    )
    db_session.add_all([owner_file, foreign_file])
    await db_session.flush()
    db_session.add_all(
        [
            DocumentChunk(
                file_id=owner_file.id,
                chat_id=owner_other_chat.id,
                chunk_index=0,
                content="Owner cross-chat context",
                embedding=[0.0, 1.0],
                token_count=4,
            ),
            DocumentChunk(
                file_id=foreign_file.id,
                chat_id=foreign_chat.id,
                chunk_index=0,
                content="Foreign tenant secret",
                embedding=[1.0, 0.0],
                token_count=4,
            ),
        ]
    )
    await db_session.commit()

    with patch(
        "quip.services.rag.get_embeddings",
        new_callable=AsyncMock,
        return_value=[[1.0, 0.0]],
    ):
        results = await retrieve_context(
            "find context", current_chat.id, owner.id, db_session, top_k=5
        )

    assert [result["content"] for result in results] == [
        "Owner cross-chat context"
    ]


# ── Helper ──────────────────────────────────────────────────────────────────


class FakeChunk:
    """Minimal stand-in for DocumentChunk in unit tests."""
    def __init__(self, content, embedding, chunk_metadata, chunk_index=0, file_id=None):
        self.content = content
        self.embedding = embedding
        self.chunk_metadata = chunk_metadata
        self.chunk_index = chunk_index
        self.file_id = file_id
