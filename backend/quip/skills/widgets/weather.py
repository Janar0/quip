"""Skill: weather — Get current weather and forecast for any location. Use when user asks about weat"""
import httpx
from datetime import datetime
from quip.services.config import get_setting


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

    city = (current.get("city") or {}).get("name") or city_fallback
    temp = (current.get("temperature") or {}).get("air", {}).get("C")
    feels_like = (current.get("temperature") or {}).get("comfort", {}).get("C")
    humidity = (current.get("humidity") or {}).get("percent")
    wind_speed = (current.get("wind") or {}).get("speed", {}).get("m_s")
    wind_dir = (current.get("wind") or {}).get("direction", {}).get("scale_8", "")
    pressure = (current.get("pressure") or {}).get("mm_hg_atm")
    condition = (current.get("description") or {}).get("full", "")
    icon_emoji = (current.get("icon") or {}).get("emoji", "\U0001f324")

    forecast = []
    for item in forecast_list[:5]:
        temp_max = (item.get("temperature") or {}).get("air", {}).get("max", {}).get("C")
        temp_min = (item.get("temperature") or {}).get("air", {}).get("min", {}).get("C")
        day_condition = (item.get("description") or {}).get("full", "")
        day_emoji = (item.get("icon") or {}).get("emoji", "\U0001f324")
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


async def _handler(params: dict) -> dict:
    return await _fetch_weather(params)


SKILL = {
    'id': 'weather',
    'name': 'Weather',
    'description': 'Get current weather and forecast for any location. Use when user asks about weather.',
    'category': 'widget',
    'icon': 'M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41M12 6a6 6 0 100 12 6 6 0 000-12z',
    'type': 'api',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'handler': _handler,
    'prompt_instructions': """Widget: weather — show current weather + forecast via Gismeteo.

Call: use_widget(name="weather", params={"lat": 55.75, "lon": 37.62, "city": "Moscow"})
- lat/lon: geographic coordinates (required). Use known values or search for them first.
- city: human-readable city name for display purposes.

Common coordinates:
  Moscow: 55.75, 37.62 | Saint Petersburg: 59.93, 30.32 | Novosibirsk: 54.99, 82.90
  London: 51.51, -0.13 | New York: 40.71, -74.01 | Tokyo: 35.69, 139.69
  Berlin: 52.52, 13.40 | Paris: 48.85, 2.35 | Beijing: 39.90, 116.40

The widget renders a card with current conditions + 5-day forecast.
After the widget, briefly summarize the weather in 1-2 sentences.""",
    'data_schema': {'city': 'string — city name', 'temp': 'number — current temperature °C', 'feels_like': 'number — feels-like temperature °C', 'humidity': 'number — humidity %', 'wind_speed': 'number — wind speed m/s', 'wind_dir': 'string — wind direction (N/NE/E/SE/S/SW/W/NW)', 'pressure': 'number — pressure mmHg', 'condition': 'string — weather condition text', 'icon_emoji': 'string — weather emoji', 'forecast': [{'day': 'string', 'temp_max': 'number', 'temp_min': 'number', 'condition': 'string', 'icon_emoji': 'string'}]},
    'api_config': {'url': 'https://api.gismeteo.net/v3/weather/current/', 'method': 'GET', '_note': 'Special handling in widget_api.py _fetch_weather() — uses lat/lon + X-Gismeteo-Token'},
    'template_html': """<div class="widget-weather">
  <div class="ww-header">
    <div class="ww-city">{{city}}</div>
    <div class="ww-condition">{{condition}}</div>
  </div>
  <div class="ww-current">
    <div class="ww-icon">{{icon_emoji}}</div>
    <div class="ww-temp">{{temp}}°C</div>
    <div class="ww-details">
      <div class="ww-detail-row"><span class="ww-label">Feels like</span> <span class="ww-val">{{feels_like}}°</span></div>
      <div class="ww-detail-row"><span class="ww-label">Humidity</span> <span class="ww-val">{{humidity}}%</span></div>
      <div class="ww-detail-row"><span class="ww-label">Wind</span> <span class="ww-val">{{wind_speed}} m/s {{wind_dir}}</span></div>
      <div class="ww-detail-row"><span class="ww-label">Pressure</span> <span class="ww-val">{{pressure}} mmHg</span></div>
    </div>
  </div>
  {{#forecast}}
  <div class="ww-forecast">
    {{#forecast}}
    <div class="ww-day">
      <div class="ww-day-name">{{day}}</div>
      <div class="ww-day-icon">{{icon_emoji}}</div>
      <div class="ww-day-temp">{{temp_max}}°</div>
      <div class="ww-day-min">{{temp_min}}°</div>
    </div>
    {{/forecast}}
  </div>
  {{/forecast}}
</div>""",
    'template_css': """.widget-card .widget-weather {
  padding: 1.5rem;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--quip-glass-bg, rgba(22,22,26,0.42));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  border-radius: var(--quip-radius, 12px);
}
.widget-card .ww-header {
  margin-bottom: 1rem;
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.widget-card .ww-city {
  font-size: 1.25rem;
  font-weight: 700;
  color: var(--quip-text, #f5f5f5);
}
.widget-card .ww-condition {
  font-size: 0.85rem;
  color: var(--quip-text-dim, #a3a3a3);
  text-transform: lowercase;
}
.widget-card .ww-current {
  display: flex;
  align-items: center;
  gap: 1.25rem;
  margin-bottom: 1rem;
  padding: 1rem;
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  border-radius: 10px;
}
.widget-card .ww-icon { font-size: 3.2rem; line-height: 1; }
.widget-card .ww-temp {
  font-size: 2.75rem;
  font-weight: 800;
  color: var(--quip-text, #f5f5f5);
  line-height: 1;
  letter-spacing: -0.02em;
}
.widget-card .ww-details {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  flex: 1;
}
.widget-card .ww-detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 0.8rem;
  gap: 1rem;
}
.widget-card .ww-label { color: var(--quip-text-muted, #6b6b74); }
.widget-card .ww-val { color: var(--quip-text-dim, #a3a3a3); font-weight: 500; }
.widget-card .ww-forecast {
  display: flex;
  gap: 0;
  border-top: 1px solid var(--quip-glass-border-strong, rgba(255,255,255,0.12));
  padding-top: 0.75rem;
}
.widget-card .ww-day {
  flex: 1;
  text-align: center;
  padding: 0.6rem 0.25rem;
  border-radius: 8px;
  transition: background 0.15s;
}
.widget-card .ww-day:hover { background: var(--quip-glass-highlight, rgba(255,255,255,0.08)); }
.widget-card .ww-day-name {
  font-size: 0.75rem;
  color: var(--quip-text-muted, #6b6b74);
  margin-bottom: 0.3rem;
  font-weight: 500;
}
.widget-card .ww-day-icon { font-size: 1.5rem; line-height: 1; margin-bottom: 0.2rem; }
.widget-card .ww-day-temp { font-size: 0.95rem; font-weight: 700; color: var(--quip-text, #f5f5f5); }
.widget-card .ww-day-min { font-size: 0.75rem; color: var(--quip-text-muted, #6b6b74); }""",
    'settings_schema': [
        {'key': 'gismeteo_api_key', 'label': 'Gismeteo API key', 'type': 'password', 'default': '',
         'help': 'Required. Get one at https://gismeteo.ru/api/.'},
    ],
    'default_settings': {'gismeteo_api_key': ''},
}
