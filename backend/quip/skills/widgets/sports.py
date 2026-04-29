"""Skill: sports — Display sports match scores or standings. Use when user asks about sports scores"""

SKILL = {
    'id': 'sports',
    'name': 'Sports',
    'description': 'Display sports match scores or standings. Use when user asks about sports scores, match results, or team standings.',
    'category': 'widget',
    'icon': 'M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z',
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """Widget: sports — display a match score or standings card.

Call: use_widget(name="sports", data={...})

For a single match:
{
  "type": "match",
  "league": "Premier League",
  "date": "2026-04-12",
  "status": "FT",
  "home": {"name": "Arsenal", "score": 2, "logo_letter": "A"},
  "away": {"name": "Chelsea", "score": 1, "logo_letter": "C"},
  "events": ["⚽ 23' Saka", "⚽ 67' Havertz", "⚽ 81' Palmer"]
}

For standings:
{
  "type": "standings",
  "league": "Premier League",
  "season": "2025/26",
  "teams": [
    {"pos": 1, "name": "Arsenal", "played": 30, "won": 22, "drawn": 5, "lost": 3, "gd": "+42", "points": 71}
  ]
}

Use web_search to get accurate current data before calling this widget.""",
    'data_schema': {'type': 'string — match or standings', 'league': 'string', 'home': {'name': 'string', 'score': 'number', 'logo_letter': 'string'}, 'away': {'name': 'string', 'score': 'number', 'logo_letter': 'string'}, 'status': 'string', 'events': ['string'], 'teams': [{'pos': 'number', 'name': 'string', 'played': 'number', 'won': 'number', 'drawn': 'number', 'lost': 'number', 'gd': 'string', 'points': 'number'}]},
    'api_config': None,
    'template_html': """<div class="widget-sports">
  {{#league}}<div class="ws-badge">{{league}}</div>{{/league}}
  {{#home}}
  <div class="ws-match">
    <div class="ws-team ws-team-left">
      <div class="ws-logo">{{home.logo_letter}}</div>
      <div class="ws-team-name">{{home.name}}</div>
    </div>
    <div class="ws-score-box">
      <div class="ws-score">{{home.score}}<span class="ws-dash">—</span>{{away.score}}</div>
      {{#status}}<div class="ws-status">{{status}}</div>{{/status}}
    </div>
    <div class="ws-team ws-team-right">
      <div class="ws-logo">{{away.logo_letter}}</div>
      <div class="ws-team-name">{{away.name}}</div>
    </div>
  </div>
  {{#events}}
  <div class="ws-events">
    {{#events}}<div class="ws-event">{{.}}</div>{{/events}}
  </div>
  {{/events}}
  {{/home}}
  {{#teams}}
  <table class="ws-table">
    <thead><tr><th>#</th><th>Team</th><th>P</th><th>W</th><th>D</th><th>L</th><th>GD</th><th>Pts</th></tr></thead>
    <tbody>
      {{#teams}}<tr><td>{{pos}}</td><td class="ws-t-name">{{name}}</td><td>{{played}}</td><td>{{won}}</td><td>{{drawn}}</td><td>{{lost}}</td><td>{{gd}}</td><td class="ws-t-pts">{{points}}</td></tr>{{/teams}}
    </tbody>
  </table>
  {{/teams}}
</div>""",
    'template_css': """.widget-card .widget-sports {
  padding: 1.25rem;
  font-family: system-ui, -apple-system, sans-serif;
  background: var(--quip-glass-bg, rgba(22,22,26,0.42));
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
  border-radius: var(--quip-radius, 12px);
}
.widget-card .ws-badge {
  display: inline-block;
  font-size: 0.65rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--quip-link, #c4c8d2);
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  padding: 0.2rem 0.55rem;
  border-radius: 4px;
  margin-bottom: 0.75rem;
}
.widget-card .ws-match {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 1.5rem;
  padding: 1rem 0;
}
.widget-card .ws-team { display: flex; flex-direction: column; align-items: center; gap: 0.4rem; flex: 1; }
.widget-card .ws-logo {
  width: 42px; height: 42px;
  border-radius: 50%;
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  display: flex; align-items: center; justify-content: center;
  font-size: 1.15rem; font-weight: 800;
  color: var(--quip-text, #f5f5f5);
}
.widget-card .ws-team-name { font-size: 0.85rem; font-weight: 600; color: var(--quip-text, #f5f5f5); text-align: center; }
.widget-card .ws-score-box { text-align: center; }
.widget-card .ws-score { font-size: 2rem; font-weight: 800; color: var(--quip-text, #f5f5f5); letter-spacing: -0.02em; }
.widget-card .ws-dash { color: var(--quip-text-muted, #6b6b74); margin: 0 0.3rem; }
.widget-card .ws-status {
  font-size: 0.7rem; font-weight: 600; color: var(--quip-link, #c4c8d2);
  background: var(--quip-glass-highlight, rgba(255,255,255,0.08));
  padding: 0.1rem 0.5rem; border-radius: 3px;
  display: inline-block; margin-top: 0.25rem;
}
.widget-card .ws-events {
  margin-top: 0.75rem; padding-top: 0.5rem;
  border-top: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
}
.widget-card .ws-event { font-size: 0.8rem; color: var(--quip-text-dim, #a3a3a3); padding: 0.15rem 0; }
.widget-card .ws-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin-top: 0.5rem; }
.widget-card .ws-table th {
  color: var(--quip-text-muted, #6b6b74); font-weight: 500;
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--quip-glass-border-strong, rgba(255,255,255,0.12));
  text-align: left;
}
.widget-card .ws-table td {
  color: var(--quip-text, #f5f5f5);
  padding: 0.45rem 0.5rem;
  border-bottom: 1px solid var(--quip-glass-border, rgba(255,255,255,0.07));
}
.widget-card .ws-table tbody tr:hover { background: var(--quip-glass-highlight, rgba(255,255,255,0.03)); }
.widget-card .ws-t-name { font-weight: 600; }
.widget-card .ws-t-pts { font-weight: 700; color: var(--quip-link, #c4c8d2); }""",
}
