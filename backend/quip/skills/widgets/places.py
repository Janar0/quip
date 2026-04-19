"""Skill: places — Show a place/location card with address and map link. Use when user asks about a"""

SKILL = {
    'id': 'places',
    'name': 'Places',
    'description': 'Show a place/location card with address and map link. Use when user asks about a specific place, address, or location.',
    'category': 'widget',
    'icon': 'M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z M12 10a1 1 0 100-2 1 1 0 000 2z',
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """Widget: places — display a location/place card.

Call: use_widget(name="places", data={...})

Data schema:
{
  "name": "Place name",
  "address": "Full address",
  "lat": 55.7558,
  "lon": 37.6173,
  "category": "museum",
  "rating": 4.5,
  "description": "Short description",
  "hours": "10:00 - 22:00",
  "phone": "+7 495 123-45-67",
  "website": "https://example.com"
}

All fields except name and address are optional.
If you know coordinates, include them — the card will show a map link.
Use web_search first to find accurate data about the place.""",
    'data_schema': {'name': 'string', 'address': 'string', 'lat': 'number (optional)', 'lon': 'number (optional)', 'category': 'string (optional)', 'rating': 'number (optional)', 'description': 'string (optional)', 'hours': 'string (optional)', 'phone': 'string (optional)', 'website': 'string (optional)'},
    'api_config': None,
    'template_html': """<div class="widget-places">
  <div class="wp-main">
    <div class="wp-name">{{name}}</div>
    {{#category}}<div class="wp-category">{{category}}</div>{{/category}}
    {{#rating}}<div class="wp-rating">⭐ {{rating}}</div>{{/rating}}
    {{#description}}<div class="wp-description">{{description}}</div>{{/description}}
    <div class="wp-address">📍 {{address}}</div>
    {{#hours}}<div class="wp-detail">🕐 {{hours}}</div>{{/hours}}
    {{#phone}}<div class="wp-detail">📞 {{phone}}</div>{{/phone}}
    {{#website}}<div class="wp-detail"><a href="{{website}}" target="_blank" rel="noopener" class="wp-link">🌐 Website</a></div>{{/website}}
    {{#lat}}<div class="wp-detail"><a href="https://www.openstreetmap.org/?mlat={{lat}}&mlon={{lon}}#map=16/{{lat}}/{{lon}}" target="_blank" rel="noopener" class="wp-link">🗺 Open map</a></div>{{/lat}}
  </div>
</div>""",
    'template_css': """.widget-card .widget-places { font-family: system-ui, sans-serif; }
.widget-card .wp-main { padding: 1rem; }
.widget-card .wp-name { font-size: 1.15rem; font-weight: 700; color: var(--quip-text, #e2e8f0); margin-bottom: 0.25rem; }
.widget-card .wp-category { font-size: 0.75rem; color: var(--quip-link, #60a5fa); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
.widget-card .wp-rating { font-size: 0.85rem; color: #fbbf24; margin-bottom: 0.5rem; }
.widget-card .wp-description { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.5rem; }
.widget-card .wp-address { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.25rem; }
.widget-card .wp-detail { font-size: 0.8rem; color: var(--quip-text-muted, #64748b); margin-bottom: 0.15rem; }
.widget-card .wp-link { color: var(--quip-link, #60a5fa); text-decoration: none; }
.widget-card .wp-link:hover { text-decoration: underline; }""",
}
