"""External API dispatcher for API-backed widgets."""
import httpx
import re
from quip.core.config import get_setting
from quip.models.skill import Skill
from quip.skills import HANDLERS


def _resolve_placeholders(value: str, params: dict) -> str:
    """Resolve {{params.key}} and {{SETTING:key}} placeholders in strings."""
    def replacer(m):
        ref = m.group(1)
        if ref.startswith("SETTING:"):
            setting_key = ref[8:]
            return get_setting(setting_key, "")
        if ref.startswith("params."):
            param_key = ref[7:]
            return str(params.get(param_key, ""))
        return m.group(0)
    return re.sub(r"\{\{(.+?)\}\}", replacer, value)


def _extract_jsonpath(data, path: str):
    """Simple JSONPath-lite: $.key.subkey.0.field"""
    if not isinstance(path, str) or not path.startswith("$."):
        return data.get(path, None) if isinstance(data, dict) else None
    keys = path[2:].split(".")
    current = data
    for key in keys:
        if isinstance(current, list):
            try:
                current = current[int(key)]
            except (IndexError, ValueError):
                return None
        elif isinstance(current, dict):
            current = current.get(key)
        else:
            return None
        if current is None:
            return None
    return current


async def execute_widget_api(skill: Skill, params: dict) -> dict:
    """Call external API based on skill.api_config and map response.

    Checks HANDLERS first — skills can register custom handlers for
    complex API logic (multi-call, response parsing).
    """
    handler = HANDLERS.get(skill.id)
    if handler:
        return await handler(params)

    config = skill.api_config or {}
    url = _resolve_placeholders(config.get("url", ""), params)
    method = config.get("method", "GET").upper()

    headers = {}
    for k, v in (config.get("headers") or {}).items():
        headers[k] = _resolve_placeholders(v, params)

    query_params = {}
    for k, v in (config.get("params_mapping") or {}).items():
        query_params[k] = _resolve_placeholders(v, params)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.request(method, url, params=query_params, headers=headers)
        resp.raise_for_status()
        raw = resp.json()

    mapping = config.get("response_mapping")
    if not mapping:
        return raw

    result = {}
    for out_key, json_path in mapping.items():
        if isinstance(json_path, str) and json_path.startswith("$."):
            result[out_key] = _extract_jsonpath(raw, json_path)
        elif isinstance(json_path, dict):
            arr_path = json_path.get("_array", "")
            arr_data = _extract_jsonpath(raw, arr_path) or []
            item_map = json_path.get("_map", {})
            result[out_key] = [
                {k: _extract_jsonpath(item, v) for k, v in item_map.items()}
                for item in arr_data
            ]
        else:
            result[out_key] = json_path
    return result
