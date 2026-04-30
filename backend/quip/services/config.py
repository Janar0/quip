# backend/quip/services/config.py
"""Backward-compat re-exports. Use quip.core.config instead."""
from quip.core.config import (  # noqa: F401
    get_setting,
    get_bool_setting,
    set_setting,
    get_all_settings,
    load_settings,
    save_settings,
)
