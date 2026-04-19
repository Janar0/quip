"""Skill: weather — Get current weather and forecast for any location. Use when user asks about weat"""

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
    <div class="ww-temp">{{temp}}°</div>
    <div class="ww-details">
      <div>Feels like {{feels_like}}°</div>
      <div>Humidity {{humidity}}%</div>
      <div>Wind {{wind_speed}} m/s {{wind_dir}}</div>
      <div>Pressure {{pressure}} mmHg</div>
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
    'template_css': """.widget-card .widget-weather { padding: 1rem; font-family: system-ui, sans-serif; }
.widget-card .ww-header { margin-bottom: 0.75rem; }
.widget-card .ww-city { font-size: 1.1rem; font-weight: 600; color: var(--quip-text, #e2e8f0); }
.widget-card .ww-condition { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); text-transform: capitalize; }
.widget-card .ww-current { display: flex; align-items: center; gap: 1rem; margin-bottom: 1rem; }
.widget-card .ww-icon { font-size: 3rem; line-height: 1; }
.widget-card .ww-temp { font-size: 2.5rem; font-weight: 700; color: var(--quip-text, #e2e8f0); }
.widget-card .ww-details { font-size: 0.8rem; color: var(--quip-text-muted, #64748b); line-height: 1.6; }
.widget-card .ww-forecast { display: flex; gap: 0.25rem; border-top: 1px solid var(--quip-border, #1e293b); padding-top: 0.75rem; }
.widget-card .ww-day { flex: 1; text-align: center; padding: 0.5rem 0.25rem; border-radius: 0.5rem; }
.widget-card .ww-day:hover { background: var(--quip-hover, rgba(148,163,184,0.08)); }
.widget-card .ww-day-name { font-size: 0.75rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.25rem; }
.widget-card .ww-day-icon { font-size: 1.5rem; line-height: 1; }
.widget-card .ww-day-temp { font-size: 0.9rem; font-weight: 600; color: var(--quip-text, #e2e8f0); }
.widget-card .ww-day-min { font-size: 0.75rem; color: var(--quip-text-muted, #64748b); }""",
    'settings_schema': [
        {'key': 'gismeteo_api_key', 'label': 'Gismeteo API key', 'type': 'password', 'default': '',
         'help': 'Required. Get one at https://gismeteo.ru/api/.'},
    ],
    'default_settings': {'gismeteo_api_key': ''},
}
