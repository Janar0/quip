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
  <div class="wp-card">
    <div class="wp-header">
      <div class="wp-name">{{name}}</div>
      {{#category}}<span class="wp-badge">{{category}}</span>{{/category}}
    </div>
    {{#rating}}<div class="wp-rating"><span class="wp-stars">★</span> {{rating}}</div>{{/rating}}
    {{#description}}<p class="wp-desc">{{description}}</p>{{/description}}
    <div class="wp-details">
      <div class="wp-row">📍 {{address}}</div>
      {{#hours}}<div class="wp-row">🕐 {{hours}}</div>{{/hours}}
      {{#phone}}<div class="wp-row">📞 {{phone}}</div>{{/phone}}
    </div>
    <div class="wp-links">
      {{#website}}<a href="{{website}}" target="_blank" rel="noopener" class="wp-link">Website →</a>{{/website}}
      {{#lat}}<a href="https://www.openstreetmap.org/?mlat={{lat}}&mlon={{lon}}#map=16/{{lat}}/{{lon}}" target="_blank" rel="noopener" class="wp-link">Open map →</a>{{/lat}}
    </div>
  </div>
</div>""",
    'template_css': """.widget-card .widget-places {
  font-family: system-ui, -apple-system, sans-serif;
}
.widget-card .wp-card {
  padding: 1.25rem;
  background: var(--quip-glass-bg, rgba(22,22,26,0.42));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  border-radius: var(--quip-radius, 12px);
}
.widget-card .wp-header {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  flex-wrap: wrap;
  margin-bottom: 0.4rem;
}
.widget-card .wp-name {
  font-size: 1.15rem;
  font-weight: 700;
  color: var(--quip-text, #f5f5f5);
}
.widget-card .wp-badge {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--quip-link, #c4c8d2);
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  padding: 0.15rem 0.5rem;
  border-radius: 4px;
}
.widget-card .wp-rating {
  font-size: 0.9rem;
  margin-bottom: 0.5rem;
}
.widget-card .wp-stars { color: #f59e0b; }
.widget-card .wp-desc {
  font-size: 0.85rem;
  color: var(--quip-text-dim, #a3a3a3);
  margin: 0 0 0.75rem;
  line-height: 1.5;
}
.widget-card .wp-details {
  margin-bottom: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}
.widget-card .wp-row {
  font-size: 0.8rem;
  color: var(--quip-text-muted, #6b6b74);
}
.widget-card .wp-links {
  display: flex;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-top: 0.75rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
}
.widget-card .wp-link {
  font-size: 0.8rem;
  color: var(--quip-link, #c4c8d2);
  text-decoration: none;
  transition: opacity 0.12s;
}
.widget-card .wp-link:hover { opacity: 0.75; }""",
}
