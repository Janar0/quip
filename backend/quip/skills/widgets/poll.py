"""Skill: poll — Display a poll or comparison card with options. Use when user wants to create a """


async def _handler(params: dict) -> dict:
    data = params.get("data", {})
    options = data.get("options", [])
    total = sum(o.get("votes", 0) for o in options)
    for o in options:
        o["percent"] = round(o.get("votes", 0) / total * 100) if total else 0
    data["total_votes"] = total
    return data


SKILL = {
    'id': 'poll',
    'name': 'Poll',
    'description': 'Display a poll or comparison card with options. Use when user wants to create a poll or compare options visually.',
    'category': 'widget',
    'handler': _handler,
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
        <span class="wpl-percent">{{percent}}%</span>
      </div>
      {{#description}}<div class="wpl-desc">{{description}}</div>{{/description}}
      <div class="wpl-bar-track">
        <div class="wpl-bar" style="width:{{percent}}%"></div>
      </div>
      {{#votes}}<div class="wpl-votes">{{votes}} votes</div>{{/votes}}
    </div>
    {{/options}}
  </div>
  {{#total_votes}}<div class="wpl-total">{{total_votes}} total votes</div>{{/total_votes}}
</div>""",
    'template_css': """.widget-card .widget-poll {
  padding: 1.35rem;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--quip-glass-bg, rgba(22,22,26,0.42));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  border-radius: var(--quip-radius, 12px);
}
.widget-card .wpl-question {
  font-size: 1.1rem;
  font-weight: 700;
  color: var(--quip-text, #f5f5f5);
  margin-bottom: 1rem;
}
.widget-card .wpl-option {
  padding: 0.85rem;
  border-radius: 8px;
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  margin-bottom: 0.5rem;
  transition: border-color 0.15s;
  background: var(--quip-glass-highlight, rgba(255,255,255,0.02));
}
.widget-card .wpl-option:hover { border-color: var(--quip-glass-border-strong, rgba(255,255,255,0.12)); }
.widget-card .wpl-option-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.35rem;
}
.widget-card .wpl-label { font-size: 0.9rem; font-weight: 600; color: var(--quip-text, #f5f5f5); }
.widget-card .wpl-percent { font-size: 0.85rem; font-weight: 700; color: var(--quip-link, #c4c8d2); }
.widget-card .wpl-desc {
  font-size: 0.8rem;
  color: var(--quip-text-dim, #a3a3a3);
  margin-bottom: 0.5rem;
  line-height: 1.4;
}
.widget-card .wpl-bar-track {
  height: 6px;
  border-radius: 3px;
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  overflow: hidden;
  margin-bottom: 0.35rem;
}
.widget-card .wpl-bar {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--quip-link, #c4c8d2), rgba(196,200,210,0.5));
  transition: width 0.6s ease;
  min-width: 0;
}
.widget-card .wpl-votes {
  font-size: 0.7rem;
  color: var(--quip-text-muted, #6b6b74);
}
.widget-card .wpl-total {
  margin-top: 0.75rem;
  padding-top: 0.6rem;
  border-top: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  font-size: 0.75rem;
  color: var(--quip-text-muted, #6b6b74);
  text-align: right;
}""",
}
