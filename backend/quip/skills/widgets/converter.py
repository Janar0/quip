"""Skill: converter — Display a unit/currency conversion result as a visual card. Use when user asks t"""

SKILL = {
    'id': 'converter',
    'name': 'Unit Converter',
    'description': 'Display a unit/currency conversion result as a visual card. Use when user asks to convert units, currencies, or measurements.',
    'category': 'widget',
    'icon': 'M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15',
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """Widget: converter — display a unit/currency conversion.

Call: use_widget(name="converter", data={...})

Data schema:
{
  "from_value": 100,
  "from_unit": "km",
  "from_label": "Kilometers",
  "to_value": 62.14,
  "to_unit": "mi",
  "to_label": "Miles",
  "formula": "1 km = 0.6214 mi",
  "category": "distance"
}

category: one of "distance", "weight", "temperature", "volume", "currency", "area", "speed", "time", "data".""",
    'data_schema': {'from_value': 'number', 'from_unit': 'string', 'from_label': 'string', 'to_value': 'number', 'to_unit': 'string', 'to_label': 'string', 'formula': 'string', 'category': 'string'},
    'api_config': None,
    'template_html': """<div class="widget-converter">
  {{#category}}<div class="wc-cat">{{category}}</div>{{/category}}
  <div class="wc-row">
    <div class="wc-side">
      <div class="wc-value">{{from_value}}</div>
      <div class="wc-unit">{{from_unit}}</div>
      <div class="wc-label">{{from_label}}</div>
    </div>
    <div class="wc-arrow">
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M5 12h14M13 5l7 7-7 7"/></svg>
    </div>
    <div class="wc-side">
      <div class="wc-value wc-result">{{to_value}}</div>
      <div class="wc-unit">{{to_unit}}</div>
      <div class="wc-label">{{to_label}}</div>
    </div>
  </div>
  {{#formula}}<div class="wc-formula">{{formula}}</div>{{/formula}}
</div>""",
    'template_css': """.widget-card .widget-converter {
  padding: 1.5rem;
  font-family: system-ui, -apple-system, sans-serif;
  text-align: center;
  background: var(--quip-glass-bg, rgba(22,22,26,0.42));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  border-radius: var(--quip-radius, 12px);
}
.widget-card .wc-cat {
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--quip-text-muted, #6b6b74);
  margin-bottom: 0.75rem;
}
.widget-card .wc-row {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.25rem;
}
.widget-card .wc-side { flex: 1; max-width: 180px; }
.widget-card .wc-value {
  font-size: 2.2rem;
  font-weight: 800;
  color: var(--quip-text, #f5f5f5);
  line-height: 1.15;
  letter-spacing: -0.02em;
}
.widget-card .wc-result {
  color: var(--quip-link, #c4c8d2);
}
.widget-card .wc-unit {
  font-size: 1rem;
  font-weight: 600;
  color: var(--quip-text-dim, #a3a3a3);
  margin-top: 0.15rem;
}
.widget-card .wc-label {
  font-size: 0.75rem;
  color: var(--quip-text-muted, #6b6b74);
  margin-top: 0.2rem;
}
.widget-card .wc-arrow {
  color: var(--quip-text-muted, #6b6b74);
  flex-shrink: 0;
}
.widget-card .wc-formula {
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  font-size: 0.8rem;
  color: var(--quip-text-muted, #6b6b74);
}""",
}
