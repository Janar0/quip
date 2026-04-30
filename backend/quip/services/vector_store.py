# backend/quip/services/vector_store.py
"""Backward-compat re-exports. Use quip.core.vector_store instead."""
from quip.core.vector_store import (  # noqa: F401
    VectorStore,
    SQLiteVectorStore,
    HNSWVectorStore,
    get_vector_store,
)
