"""Vector storage backends for RAG chunk similarity search.

Two backends:
- SQLiteVectorStore: Brute-force cosine in Python (default, zero dependencies)
- HNSWVectorStore: In-memory ANN via hnswlib (optional, ~100x faster search)

Set VECTOR_STORE=hnswlib to enable the HNSW backend.
"""
from __future__ import annotations

import logging
import math
import os
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class VectorStore(ABC):
    """Abstract base for vector similarity search backends.
    
    All methods are synchronous (called via asyncio.to_thread for CPU-bound work).
    """

    @abstractmethod
    def rebuild(self, chunks: list) -> None:
        """(Re)build the index from a list of (chunk_obj, filename, content_hash) tuples."""

    @abstractmethod
    def search(
        self,
        query_vec: list[float],
        chunks: list,
        top_k: int,
    ) -> list[dict]:
        """Return top_k results as list of dicts with score, content, etc."""

    @abstractmethod
    def clear(self) -> None:
        """Release index memory."""


class SQLiteVectorStore(VectorStore):
    """Brute-force cosine similarity — current behavior. No index needed."""

    def __init__(self):
        self._rows: list = []

    def rebuild(self, chunks: list) -> None:
        self._rows = list(chunks)

    def search(
        self,
        query_vec: list[float],
        chunks: list,
        top_k: int,
    ) -> list[dict]:
        rows = chunks if chunks else self._rows
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
        return scored[:top_k]

    def clear(self) -> None:
        self._rows.clear()


class HNSWVectorStore(VectorStore):
    """In-memory ANN index via hnswlib. Pip-installable, no system deps."""

    def __init__(self, space: str = "cosine", dim: int = 1536):
        self._space = space
        self._dim = dim
        self._index = None
        self._id_to_chunk: dict[int, object] = {}
        self._next_id = 0

    def rebuild(self, chunks: list) -> None:
        try:
            import hnswlib
        except ImportError:
            logger.warning("hnswlib not installed — falling back to brute-force")
            return

        self._id_to_chunk.clear()
        self._next_id = 0

        vectors = []
        ids = []
        for chunk, filename, content_hash in chunks:
            if not chunk.embedding:
                continue
            dim = len(chunk.embedding)
            if self._dim != dim:
                self._dim = dim

            idx = self._next_id
            self._next_id += 1
            vectors.append(chunk.embedding)
            ids.append(idx)
            self._id_to_chunk[idx] = (chunk, filename, content_hash)

        if not vectors:
            return

        self._index = hnswlib.Index(space=self._space, dim=self._dim)
        self._index.init_index(
            max_elements=len(vectors),
            ef_construction=200,
            M=16,
        )
        self._index.add_items(vectors, ids)
        self._index.set_ef(50)
        logger.info("HNSW index built with %d vectors (dim=%d)", len(vectors), self._dim)

    def search(
        self,
        query_vec: list[float],
        chunks: list,
        top_k: int,
    ) -> list[dict]:
        if self._index is None or not self._id_to_chunk:
            # Fall back to brute-force
            store = SQLiteVectorStore()
            store.rebuild(chunks)
            return store.search(query_vec, chunks, top_k)

        labels, distances = self._index.knn_query(
            [query_vec], k=min(top_k * 2, self._index.element_count)
        )
        results = []
        for label, dist in zip(labels[0], distances[0]):
            if label < 0:
                continue
            entry = self._id_to_chunk.get(int(label))
            if not entry:
                continue
            chunk, filename, content_hash = entry
            results.append({
                "content": chunk.content,
                "filename": filename,
                "file_id": str(chunk.file_id),
                "chunk_index": chunk.chunk_index,
                "metadata": chunk.chunk_metadata or {},
                "content_hash": content_hash,
                "score": float(1.0 - dist if dist <= 1.0 else 1.0 / (1.0 + dist)),
            })
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def clear(self) -> None:
        self._index = None
        self._id_to_chunk.clear()
        self._next_id = 0


_vector_store: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Return the configured vector store singleton."""
    global _vector_store
    if _vector_store is None:
        backend = os.getenv("VECTOR_STORE", "").lower()
        if backend == "hnswlib":
            _vector_store = HNSWVectorStore()
            logger.info("Using HNSW vector store (ann)")
        else:
            _vector_store = SQLiteVectorStore()
            logger.info("Using brute-force vector store (sqlite)")
    return _vector_store
