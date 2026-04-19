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
  {{#league}}<div class="ws-league">{{league}}</div>{{/league}}
  {{#home}}
  <div class="ws-match">
    <div class="ws-team">
      <div class="ws-logo">{{home.logo_letter}}</div>
      <div class="ws-team-name">{{home.name}}</div>
    </div>
    <div class="ws-score-box">
      <div class="ws-score">{{home.score}} — {{away.score}}</div>
      <div class="ws-status">{{status}}</div>
    </div>
    <div class="ws-team">
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
    'template_css': """.widget-card .widget-sports { padding: 1rem; font-family: system-ui, sans-serif; }
.widget-card .ws-league { font-size: 0.75rem; color: var(--quip-text-muted, #64748b); text-transform: uppercase; letter-spacing: 0.05em; text-align: center; margin-bottom: 0.75rem; }
.widget-card .ws-match { display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0; }
.widget-card .ws-team { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 0.375rem; }
.widget-card .ws-logo { width: 40px; height: 40px; border-radius: 50%; background: var(--quip-hover, rgba(148,163,184,0.08)); display: flex; align-items: center; justify-content: center; font-size: 1.1rem; font-weight: 700; color: var(--quip-text, #e2e8f0); }
.widget-card .ws-team-name { font-size: 0.85rem; font-weight: 500; color: var(--quip-text, #e2e8f0); text-align: center; }
.widget-card .ws-score-box { text-align: center; padding: 0 1rem; }
.widget-card .ws-score { font-size: 1.75rem; font-weight: 800; color: var(--quip-text, #e2e8f0); }
.widget-card .ws-status { font-size: 0.7rem; color: var(--quip-link, #60a5fa); font-weight: 600; }
.widget-card .ws-events { margin-top: 0.75rem; padding-top: 0.5rem; border-top: 1px solid var(--quip-border, #1e293b); }
.widget-card .ws-event { font-size: 0.8rem; color: var(--quip-text-dim, #94a3b8); padding: 0.15rem 0; }
.widget-card .ws-table { width: 100%; border-collapse: collapse; font-size: 0.8rem; }
.widget-card .ws-table th { color: var(--quip-text-muted, #64748b); font-weight: 500; padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--quip-border, #1e293b); text-align: left; }
.widget-card .ws-table td { color: var(--quip-text, #e2e8f0); padding: 0.4rem 0.5rem; border-bottom: 1px solid var(--quip-border, #1e293b); }
.widget-card .ws-t-name { font-weight: 500; }
.widget-card .ws-t-pts { font-weight: 700; color: var(--quip-link, #60a5fa); }""",
}
