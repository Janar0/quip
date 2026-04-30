"""RAG retrieval — similarity search over document chunks with MMR re-ranking.

Pipeline:
  embed query → score chunks via configured VectorStore → dedup by content_hash →
  MMR re-rank for diversity → format context with token budget → inject
"""
import asyncio
import logging
import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from quip.core.vector_utils import cosine_similarity
from quip.models.file import DocumentChunk, File
from quip.core.config import get_setting
from quip.services.embeddings import get_embeddings
from quip.core.vector_store import get_vector_store

logger = logging.getLogger(__name__)

# Hard cap on chunks scanned per query — keeps similarity computation bounded
# even for chats with thousands of embedded chunks. For pgvector, switch to
# DB-side `<=>` ordering and drop this cap.
MAX_CHUNKS_SCANNED = 1000

# MMR pool: fetch 2× top_k candidates from cosine, then re-rank for diversity.
# Balances relevance (cosine score) against redundancy (max similarity to any
# already-selected chunk).
MMR_POOL_MULTIPLIER = 2

# Default MMR lambda — higher = more relevance, lower = more diversity.
MMR_LAMBDA_DEFAULT = 0.7

# Max tokens for formatted RAG context. At ~4 chars/token for English, 3000
# tokens ≈ 12KB of text — enough for 5-8 dense chunks without blowing context.
FORMAT_MAX_TOKENS = 3000


def _score_rows(query_vec: list[float], rows: list) -> list[dict]:
    """CPU-bound: score every chunk against the query. Run in a thread."""
    scored: list[dict] = []
    for chunk, filename, content_hash in rows:
        if not chunk.embedding:
            continue
        scored.append({
            "content": chunk.content,
            "filename": filename,
            "file_id": str(chunk.file_id),
            "chunk_index": chunk.chunk_index,
            "metadata": chunk.chunk_metadata or {},
            "content_hash": content_hash,
            "score": cosine_similarity(query_vec, chunk.embedding),
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored


def _mmr_rerank(scored: list[dict], top_k: int, lambda_param: float) -> list[dict]:
    """Maximal Marginal Relevance re-ranking.

    Greedily selects chunks that balance cosine relevance with the query
    (first term) against maximum similarity to already-selected chunks
    (second term). lambda=1 → pure relevance, lambda=0 → pure diversity.
    """
    if len(scored) <= top_k:
        return scored

    # Build pairwise similarity cache: jaccard on word sets (fast, no embedding needed)
    def word_set(text: str) -> set[str]:
        return set(text.lower().split())

    ws = {i: word_set(c["content"]) for i, c in enumerate(scored) if c["content"]}

    def jaccard(i: int, j: int) -> float:
        si, sj = ws.get(i), ws.get(j)
        if not si or not sj:
            return 0.0
        inter = len(si & sj)
        union = len(si | sj)
        return inter / union if union > 0 else 0.0

    selected: list[dict] = [scored[0]]  # Always pick highest-relevance first
    available = set(range(1, len(scored)))
    selected_indices = [0]

    while len(selected) < top_k and available:
        best_idx = -1
        best_mmr = -float("inf")
        for i in available:
            relevance = scored[i]["score"]
            max_sim = max((jaccard(i, si) for si in selected_indices), default=0.0)
            mmr = lambda_param * relevance - (1 - lambda_param) * max_sim
            if mmr > best_mmr:
                best_mmr = mmr
                best_idx = i
        if best_idx < 0:
            break
        selected.append(scored[best_idx])
        selected_indices.append(best_idx)
        available.discard(best_idx)

    return selected


async def retrieve_context(
    query: str,
    chat_id: UUID,
    db: AsyncSession,
    top_k: int | None = None,
) -> list[dict]:
    """Retrieve top-K relevant document chunks for a query.

    When `rag_cross_chat` is enabled, searches ALL embedded chunks regardless
    of chat_id. Otherwise scoped to the current chat.
    """
    t0 = time.monotonic()
    if top_k is None:
        top_k = int(get_setting("rag_top_k", "5"))
    cross_chat = get_setting("rag_cross_chat", "false").lower() in ("true", "1", "yes")

    mmr_lambda = float(get_setting("rag_mmr_lambda", str(MMR_LAMBDA_DEFAULT)))

    # Check for any embeddable docs
    doc_types = ("document", "image", "archive")
    exists_q = select(File.id).where(
        File.file_type.in_(doc_types),
        File.embedding_status == "completed",
    )
    if not cross_chat:
        exists_q = exists_q.where(File.chat_id == chat_id)
    has_docs = await db.execute(exists_q.limit(1))
    if not has_docs.scalar_one_or_none():
        logger.debug("RAG: no completed documents for chat=%s", chat_id)
        return []

    # Embed query
    query_embeddings = await get_embeddings([query])
    if not query_embeddings:
        logger.warning("RAG: embedding returned empty for query=%r", query[:80])
        return []
    query_vec = query_embeddings[0]
    t_embed = time.monotonic()

    # Fetch chunks (include content_hash for dedup)
    chunk_q = (
        select(DocumentChunk, File.filename, DocumentChunk.content_hash)
        .join(File, DocumentChunk.file_id == File.id)
        .where(
            DocumentChunk.embedding.isnot(None),
            File.embedding_status == "completed",
        )
    )
    if not cross_chat:
        chunk_q = chunk_q.where(DocumentChunk.chat_id == chat_id)
    chunk_q = chunk_q.limit(MAX_CHUNKS_SCANNED)

    result = await db.execute(chunk_q)
    rows = result.all()
    t_fetch = time.monotonic()

    if not rows:
        logger.debug("RAG: no embedded chunks for chat=%s", chat_id)
        return []

    # Score via configured VectorStore (CPU-bound, offloaded to thread)
    fetch_pool_size = top_k * MMR_POOL_MULTIPLIER
    store = get_vector_store()
    scored = await asyncio.to_thread(store.search, query_vec, rows, fetch_pool_size)
    t_score = time.monotonic()

    # Dedup by content_hash — keep highest score per hash
    seen_hashes: set[str] = set()
    deduped: list[dict] = []
    dupes = 0
    for c in scored:
        ch = c.get("content_hash") or ""
        if ch and ch in seen_hashes:
            dupes += 1
            continue
        if ch:
            seen_hashes.add(ch)
        deduped.append(c)
    if dupes:
        logger.debug("RAG: deduplicated %d chunks by content_hash", dupes)

    # MMR re-rank over a larger pool, then take top_k
    pool = deduped[:fetch_pool_size]
    if len(pool) > top_k:
        top = _mmr_rerank(pool, top_k, mmr_lambda)
    else:
        top = pool[:top_k]
    t_rerank = time.monotonic()

    # Archive markers (no embedding → not ranked, always appended)
    arch_q = (
        select(DocumentChunk, File.filename, DocumentChunk.content_hash)
        .join(File, DocumentChunk.file_id == File.id)
        .where(
            DocumentChunk.embedding.is_(None),
            File.file_type == "archive",
        )
    )
    if not cross_chat:
        arch_q = arch_q.where(DocumentChunk.chat_id == chat_id)
    arch_result = await db.execute(arch_q)
    for chunk, filename, chash in arch_result.all():
        top.append({
            "content": chunk.content,
            "filename": filename,
            "file_id": str(chunk.file_id),
            "chunk_index": chunk.chunk_index,
            "metadata": chunk.chunk_metadata or {"source": "archive"},
            "content_hash": chash,
            "score": 0.0,
        })

    elapsed = (time.monotonic() - t0) * 1000
    if top:
        scores = [c.get("score", 0) for c in top if c.get("score", 0) > 0]
        score_summary = (
            f"top={scores[0]:.3f} avg={sum(scores)/len(scores):.3f}" if scores else "no scores"
        )
        logger.info(
            "RAG: query=%r chat=%s chunks_scanned=%d retrieved=%d "
            "dedup_dropped=%d scores=[%s] "
            "timings(ms)=embed=%.0f fetch=%.0f score=%.0f rerank=%.0f total=%.0f",
            query[:80], str(chat_id)[:8], len(rows), len(top),
            dupes, score_summary,
            (t_embed - t0) * 1000, (t_fetch - t_embed) * 1000,
            (t_score - t_fetch) * 1000, (t_rerank - t_score) * 1000,
            elapsed,
        )

    return top


def format_rag_context(chunks: list[dict], max_tokens: int = FORMAT_MAX_TOKENS) -> str:
    """Format retrieved chunks into a context block for prompt injection.

    Truncates to roughly `max_tokens` by dropping the lowest-scoring chunks
    and capping each chunk's content length.
    """
    if not chunks:
        return ""

    # Separate ranked chunks from archive markers (score=0, source=archive)
    ranked = [c for c in chunks if c.get("metadata", {}).get("source") != "archive"]
    archive = [c for c in chunks if c.get("metadata", {}).get("source") == "archive"]

    # Build context, tracking estimated tokens (~4 chars/token)
    estimated_tokens = 0
    lines: list[str] = ["[Retrieved Context]"]
    has_images = False
    has_archive = False
    included = 0

    # Per-chunk overhead: header line + separator (~60 chars ≈ 15 tokens)
    CHUNK_OVERHEAD_TOKENS = 15
    FOOTER_TOKENS = 80  # closing tag + instructions

    chunk_budget = max_tokens - FOOTER_TOKENS

    for chunk in ranked:
        meta = chunk.get("metadata") or {}
        head = f"[{included + 1}] {chunk['filename']} (file_id={chunk.get('file_id', '')})"
        if meta.get("page") is not None:
            head += f", page {meta['page']}"
        if meta.get("source") == "ocr":
            head += " [ocr]"
        if meta.get("image_refs"):
            has_images = True

        # Available tokens for this chunk's content
        available = chunk_budget - estimated_tokens - CHUNK_OVERHEAD_TOKENS
        if available <= 0:
            break

        content = chunk["content"]
        # Truncate content if it exceeds the remaining budget
        content_chars = available * 4
        if len(content) > content_chars:
            content = content[:content_chars] + "…"

        lines.append(head + ":")
        lines.append(content)
        lines.append("---")
        estimated_tokens += CHUNK_OVERHEAD_TOKENS + len(content) // 4
        included += 1

    # Archive markers — always include (usually just 1-2 short lines)
    for chunk in archive:
        has_archive = True
        lines.append(f"[archive] {chunk['filename']}:")
        lines.append(chunk["content"])
        lines.append("---")

    lines.append("[/Retrieved Context]")

    if included > 0 or archive:
        lines.append(
            "Use the above context to answer the user's question. "
            "Cite sources by filename when relevant."
        )
    if has_images:
        lines.append(
            "If a chunk references `[image: img_N]` and you need to see that image, "
            "call `get_document_image(ref=\"img_N\", file_id=\"<file_id>\")` to retrieve it."
        )
    if has_archive:
        lines.append(
            "Files marked `[archive: ...]` are uploaded but NOT extracted. "
            "Use sandbox tools (e.g. `unzip`, `tar -xf`) on "
            "`/workspace/<chat_id>/uploads/<filename>` to explore."
        )

    result = "\n".join(lines)

    if included == 0 and not archive:
        return ""

    logger.debug("RAG context: %d chunks, ~%d chars", included + len(archive), len(result))
    return result
