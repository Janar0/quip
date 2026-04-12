"""RAG retrieval — cosine similarity search over document chunks."""
import logging
import math
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.models.file import File, DocumentChunk
from quip.services.config import get_setting
from quip.services.embeddings import get_embeddings

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def retrieve_context(
    query: str,
    chat_id: UUID,
    db: AsyncSession,
    top_k: int | None = None,
) -> list[dict]:
    """Retrieve top-K relevant document chunks for a query within a chat."""
    if top_k is None:
        top_k = int(get_setting("rag_top_k", "5"))

    # Check if chat has any embedded documents
    has_docs = await db.execute(
        select(File.id).where(
            File.chat_id == chat_id,
            File.file_type == "document",
            File.embedding_status == "completed",
        ).limit(1)
    )
    if not has_docs.scalar_one_or_none():
        return []

    # Embed the query
    query_embeddings = await get_embeddings([query])
    if not query_embeddings:
        return []
    query_vec = query_embeddings[0]

    # Load all chunks for this chat
    result = await db.execute(
        select(DocumentChunk, File.filename)
        .join(File, DocumentChunk.file_id == File.id)
        .where(
            DocumentChunk.chat_id == chat_id,
            DocumentChunk.embedding.isnot(None),
        )
    )
    rows = result.all()

    if not rows:
        return []

    # Compute similarities
    scored = []
    for chunk, filename in rows:
        if not chunk.embedding:
            continue
        score = cosine_similarity(query_vec, chunk.embedding)
        scored.append({
            "content": chunk.content,
            "filename": filename,
            "chunk_index": chunk.chunk_index,
            "score": score,
        })

    # Sort by score descending, take top-K
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]


def format_rag_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context block for prompt injection."""
    if not chunks:
        return ""

    lines = ["[Retrieved Context]"]
    for i, chunk in enumerate(chunks, 1):
        lines.append(f"[{i}] {chunk['filename']}:")
        lines.append(chunk["content"])
        lines.append("---")
    lines.append("[/Retrieved Context]")
    lines.append("Use the above context to answer the user's question. Cite sources by filename when relevant.")
    return "\n".join(lines)
