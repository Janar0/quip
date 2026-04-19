"""External API dispatcher for API-backed widgets."""
import httpx
import re
from datetime import datetime
from quip.services.config import get_setting
from quip.models.skill import Skill


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
    """Call external API based on skill.api_config and map response."""
    # Special-case skills with multiple API calls
    if skill.id == "weather":
        return await _fetch_weather(params)

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

    # Map response to template data schema
    mapping = config.get("response_mapping")
    if not mapping:
        return raw  # pass through if no mapping defined

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
            result[out_key] = json_path  # literal value
    return result


async def _fetch_weather(params: dict) -> dict:
    """Fetch current weather + forecast from Gismeteo."""
    from quip.services.skill_store import get_skill_setting
    api_key = get_skill_setting("weather", "gismeteo_api_key", "") or get_setting("gismeteo_api_key", "")
    if not api_key:
        return {"error": "gismeteo_api_key is not configured — ask an admin to set it in Settings → Tools."}

    lat = params.get("lat") or params.get("latitude")
    lon = params.get("lon") or params.get("longitude")
    city_fallback = params.get("city", "")

    if not lat or not lon:
        return {"error": "lat and lon are required for the weather widget"}

    headers = {"X-Gismeteo-Token": api_key}

    async with httpx.AsyncClient(timeout=10) as client:
        r1 = await client.get(
            "https://api.gismeteo.net/v3/weather/current/",
            params={"latitude": lat, "longitude": lon},
            headers=headers,
        )
        r1.raise_for_status()
        current_raw = r1.json()

        r2 = await client.get(
            "https://api.gismeteo.net/v3/weather/forecast/h24/",
            params={"latitude": lat, "longitude": lon},
            headers=headers,
        )
        r2.raise_for_status()
        forecast_raw = r2.json()

    current = current_raw.get("data", {})
    forecast_list = forecast_raw.get("data", [])

    # Parse current conditions
    city = (current.get("city") or {}).get("name") or city_fallback
    temp = (current.get("temperature") or {}).get("air", {}).get("C")
    feels_like = (current.get("temperature") or {}).get("comfort", {}).get("C")
    humidity = (current.get("humidity") or {}).get("percent")
    wind_speed = (current.get("wind") or {}).get("speed", {}).get("m_s")
    wind_dir = (current.get("wind") or {}).get("direction", {}).get("scale_8", "")
    pressure = (current.get("pressure") or {}).get("mm_hg_atm")
    condition = (current.get("description") or {}).get("full", "")
    icon_emoji = (current.get("icon") or {}).get("emoji", "🌤")

    # Parse forecast — each item is one day
    forecast = []
    for item in forecast_list[:5]:
        temp_max = (item.get("temperature") or {}).get("air", {}).get("max", {}).get("C")
        temp_min = (item.get("temperature") or {}).get("air", {}).get("min", {}).get("C")
        day_condition = (item.get("description") or {}).get("full", "")
        day_emoji = (item.get("icon") or {}).get("emoji", "🌤")
        date_str = (item.get("date") or {}).get("local", "")

        day_name = ""
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                day_name = dt.strftime("%a")
            except Exception:
                day_name = date_str[:3]

        forecast.append({
            "day": day_name,
            "temp_max": round(temp_max) if temp_max is not None else "—",
            "temp_min": round(temp_min) if temp_min is not None else "—",
            "condition": day_condition,
            "icon_emoji": day_emoji,
        })

    return {
        "city": city,
        "temp": round(temp) if temp is not None else "—",
        "feels_like": round(feels_like) if feels_like is not None else "—",
        "humidity": humidity,
        "wind_speed": wind_speed,
        "wind_dir": wind_dir,
        "pressure": pressure,
        "condition": condition,
        "icon_emoji": icon_emoji,
        "forecast": forecast,
    }
