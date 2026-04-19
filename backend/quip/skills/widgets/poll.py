"""Skill: poll — Display a poll or comparison card with options. Use when user wants to create a """

SKILL = {
    'id': 'poll',
    'name': 'Poll',
    'description': 'Display a poll or comparison card with options. Use when user wants to create a poll or compare options visually.',
    'category': 'widget',
    'icon': 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2',
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """Widget: poll — display a poll/comparison card with options.

Call: use_widget(name="poll", data={...})

Data schema:
{
  "question": "Which framework do you prefer?",
  "options": [
    {"label": "React", "description": "Meta's UI library", "votes": 0, "percent": 0},
    {"label": "Vue", "description": "Progressive framework", "votes": 0, "percent": 0}
  ],
  "total_votes": 0
}

This is display-only — the card shows options but doesn't collect votes.
Set votes/percent to 0 for new polls. Pre-calculate percent if you have data: percent = round(votes/total*100).""",
    'data_schema': {'question': 'string', 'options': [{'label': 'string', 'description': 'string (optional)', 'votes': 'number', 'percent': 'number 0-100'}], 'total_votes': 'number'},
    'api_config': None,
    'template_html': """<div class="widget-poll">
  <div class="wpl-question">{{question}}</div>
  <div class="wpl-options">
    {{#options}}
    <div class="wpl-option">
      <div class="wpl-option-header">
        <span class="wpl-label">{{label}}</span>
        {{#votes}}<span class="wpl-votes">{{votes}} votes</span>{{/votes}}
      </div>
      {{#description}}<div class="wpl-desc">{{description}}</div>{{/description}}
      <div class="wpl-bar-bg">
        <div class="wpl-bar" style="width: {{percent}}%"></div>
      </div>
    </div>
    {{/options}}
  </div>
  {{#total_votes}}<div class="wpl-total">Total: {{total_votes}} votes</div>{{/total_votes}}
</div>""",
    'template_css': """.widget-card .widget-poll { padding: 1.25rem; font-family: system-ui, sans-serif; }
.widget-card .wpl-question { font-size: 1.1rem; font-weight: 600; color: var(--quip-text, #e2e8f0); margin-bottom: 1rem; }
.widget-card .wpl-option { padding: 0.75rem; border-radius: 0.5rem; border: 1px solid var(--quip-border, #1e293b); margin-bottom: 0.5rem; transition: border-color 0.15s; }
.widget-card .wpl-option:hover { border-color: var(--quip-link, #60a5fa); }
.widget-card .wpl-option-header { display: flex; justify-content: space-between; align-items: center; }
.widget-card .wpl-label { font-size: 0.9rem; font-weight: 500; color: var(--quip-text, #e2e8f0); }
.widget-card .wpl-votes { font-size: 0.75rem; color: var(--quip-text-muted, #64748b); }
.widget-card .wpl-desc { font-size: 0.8rem; color: var(--quip-text-dim, #94a3b8); margin-top: 0.25rem; }
.widget-card .wpl-bar-bg { height: 4px; border-radius: 2px; background: var(--quip-hover, rgba(148,163,184,0.08)); margin-top: 0.5rem; overflow: hidden; }
.widget-card .wpl-bar { height: 100%; border-radius: 2px; background: var(--quip-link, #60a5fa); transition: width 0.3s; }
.widget-card .wpl-total { margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--quip-border, #1e293b); font-size: 0.75rem; color: var(--quip-text-muted, #64748b); text-align: right; }""",
}
