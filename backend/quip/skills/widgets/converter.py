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
  <div class="wc-row">
    <div class="wc-side">
      <div class="wc-value">{{from_value}}</div>
      <div class="wc-unit">{{from_unit}}</div>
      <div class="wc-label">{{from_label}}</div>
    </div>
    <div class="wc-arrow">
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M5 12h14m-4-4l4 4-4 4"/></svg>
    </div>
    <div class="wc-side">
      <div class="wc-value wc-result">{{to_value}}</div>
      <div class="wc-unit">{{to_unit}}</div>
      <div class="wc-label">{{to_label}}</div>
    </div>
  </div>
  <div class="wc-formula">{{formula}}</div>
</div>""",
    'template_css': """.widget-card .widget-converter { padding: 1.25rem; font-family: system-ui, sans-serif; text-align: center; }
.widget-card .wc-row { display: flex; align-items: center; justify-content: center; gap: 1.5rem; }
.widget-card .wc-side { flex: 1; max-width: 200px; }
.widget-card .wc-value { font-size: 2rem; font-weight: 700; color: var(--quip-text, #e2e8f0); }
.widget-card .wc-result { color: var(--quip-link, #60a5fa); }
.widget-card .wc-unit { font-size: 1rem; font-weight: 600; color: var(--quip-text-dim, #94a3b8); }
.widget-card .wc-label { font-size: 0.75rem; color: var(--quip-text-muted, #64748b); margin-top: 0.15rem; }
.widget-card .wc-arrow { color: var(--quip-text-muted, #64748b); flex-shrink: 0; }
.widget-card .wc-formula { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--quip-border, #1e293b); font-size: 0.8rem; color: var(--quip-text-muted, #64748b); }""",
}
