# backend/quip/services/config.py
"""Backward-compat re-exports. Use quip.core.config instead."""

from quip.core.config import (  # noqa: F401
    get_all_settings,
    get_bool_setting,
    get_setting,
    load_settings,
    save_settings,
    set_setting,
)
