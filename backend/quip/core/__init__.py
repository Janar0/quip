"""QUIP core — shared infrastructure: vector utils, vector store, config, skill manifest."""

from quip.core.config import get_all_settings, get_bool_setting, get_setting, load_settings, save_settings, set_setting
from quip.core.skill_manifest import SkillDef, SkillManifest, SkillSettingField
from quip.core.vector_store import HNSWVectorStore, SQLiteVectorStore, VectorStore, get_vector_store
from quip.core.vector_utils import cosine_similarity

__all__ = [
    "cosine_similarity",
    "VectorStore",
    "SQLiteVectorStore",
    "HNSWVectorStore",
    "get_vector_store",
    "get_setting",
    "get_bool_setting",
    "set_setting",
    "get_all_settings",
    "load_settings",
    "save_settings",
    "SkillDef",
    "SkillManifest",
    "SkillSettingField",
]
