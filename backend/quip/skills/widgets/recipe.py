"""Skill: recipe — Display a recipe with ingredients, steps as a beautiful card. Use when user asks"""

SKILL = {
    'id': 'recipe',
    'name': 'Recipe',
    'description': 'Display a recipe with ingredients, steps as a beautiful card. Use when user asks for recipes or cooking instructions.',
    'category': 'widget',
    'icon': 'M15 11h.01M11 15h.01M16 16a4 4 0 11-8 0c0-1.6.8-3 2-4l2-2 2 2c1.2 1 2 2.4 2 4z',
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """Widget: recipe — display a recipe as a rich card with hero images, ingredients, numbered steps, and notes.

Call: use_widget(name="recipe", data={...})

Data schema:
{
  "title": "Recipe title",
  "description": "Short 1-line description",
  "servings": 4,
  "prep_time": "15 min",
  "cook_time": "30 min",
  "images": ["/api/images/abc.png", "https://..."],
  "ingredients": [
    {"amount": "400", "unit": "g", "name": "chicken breast"}
  ],
  "steps": ["Step 1...", "Step 2..."],
  "notes": "Optional tips, substitutions, serving suggestions — multiline ok",
  "tags": ["dinner", "healthy"]
}

Rules:
- Use the user's language for ALL text (title, description, ingredients, steps, notes).
- `images`: optional; if you called generate_image earlier, pass those `/api/images/...` URLs here so they render as the recipe hero. 1-4 images recommended.
- `notes`: optional block for tips, substitutions, or "bon appétit!" closing line. Multi-line with \n supported.
- `amount`/`unit` in ingredients may be strings (e.g. "400" + "g", "1" + "pinch", "2" + "cloves").
- Steps should be concrete instructions, one per array item — they will be auto-numbered.
- After the widget, keep follow-up text very short (or omit entirely). The widget is the main content.""",
    'data_schema': {'title': 'string', 'description': 'string', 'servings': 'number', 'prep_time': 'string', 'cook_time': 'string', 'images': ['string'], 'ingredients': [{'amount': 'string', 'unit': 'string', 'name': 'string'}], 'steps': ['string'], 'notes': 'string', 'tags': ['string']},
    'api_config': None,
    'template_html': """<div class="widget-recipe">
  {{#images.length}}
  <div class="wr-hero wr-hero-{{images.length}}">
    {{#images}}<div class="wr-hero-img" style="background-image: url('{{.}}')"></div>{{/images}}
  </div>
  {{/images.length}}

  <div class="wr-body">
    <h2 class="wr-title">{{title}}</h2>
    {{#description}}<p class="wr-desc">{{description}}</p>{{/description}}

    <div class="wr-controls">
      <div class="wr-servings">
        <span class="wr-servings-label">Servings</span>
        <div class="wr-serv-group">
          <button type="button" class="wr-serv-btn" data-wr-serv="-" aria-label="decrease">−</button>
          <span class="wr-serv-val" data-wr-serv-val data-wr-serv-base="{{servings}}">{{servings}}</span>
          <button type="button" class="wr-serv-btn" data-wr-serv="+" aria-label="increase">+</button>
        </div>
      </div>
      {{#cook_time}}<div class="wr-meta-pill"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>{{cook_time}}</div>{{/cook_time}}
      {{#prep_time}}<div class="wr-meta-pill"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11H7a2 2 0 00-2 2v7h14v-7a2 2 0 00-2-2h-2M9 11V7a3 3 0 116 0v4M9 11h6"/></svg>prep {{prep_time}}</div>{{/prep_time}}
    </div>

    <div class="wr-section">
      <div class="wr-section-title">Ingredients</div>
      <ul class="wr-ingredients">
        {{#ingredients}}
        <li class="wr-ing">
          <span class="wr-ing-dot"></span>
          <span class="wr-ing-amount" data-wr-base-amount="{{amount}}" data-wr-unit="{{unit}}">{{amount}}{{#unit}} {{unit}}{{/unit}}</span>
          <span class="wr-ing-name">{{name}}</span>
        </li>
        {{/ingredients}}
      </ul>
    </div>

    <div class="wr-section">
      <div class="wr-section-title">Steps</div>
      <ol class="wr-steps">
        {{#steps}}
        <li class="wr-step" data-wr-step role="button" tabindex="0">
          <div class="wr-step-badge">
            <svg class="wr-step-hex" viewBox="0 0 24 24" fill="currentColor"><polygon points="12,2 21.5,7 21.5,17 12,22 2.5,17 2.5,7"/></svg>
            <svg class="wr-step-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="5 13 10 18 19 7"/></svg>
          </div>
          <div class="wr-step-text">{{.}}</div>
        </li>
        {{/steps}}
      </ol>
    </div>

    {{#notes}}
    <div class="wr-notes">
      <div class="wr-section-title">Notes</div>
      <p class="wr-notes-text">{{notes}}</p>
    </div>
    {{/notes}}

    {{#tags.length}}
    <div class="wr-tags">
      {{#tags}}<span class="wr-tag">{{.}}</span>{{/tags}}
    </div>
    {{/tags.length}}
  </div>
</div>""",
    'template_css': """.widget-card .widget-recipe { font-family: system-ui, -apple-system, sans-serif; overflow: hidden; }

/* Hero images */
.widget-card .wr-hero { display: grid; gap: 4px; background: var(--quip-border, #1e293b); }
.widget-card .wr-hero-1 { grid-template-columns: 1fr; }
.widget-card .wr-hero-2 { grid-template-columns: 1fr 1fr; }
.widget-card .wr-hero-3 { grid-template-columns: 2fr 1fr 1fr; grid-template-rows: 1fr; }
.widget-card .wr-hero-4 { grid-template-columns: 1fr 1fr; grid-template-rows: 1fr 1fr; }
.widget-card .wr-hero-img {
  background-size: cover;
  background-position: center;
  aspect-ratio: 16 / 10;
  min-height: 140px;
}
.widget-card .wr-hero-1 .wr-hero-img { aspect-ratio: 21 / 9; }
.widget-card .wr-hero-3 .wr-hero-img:first-child { grid-row: span 2; aspect-ratio: auto; }

.widget-card .wr-body { padding: 1.25rem 1.25rem 1.25rem; }

/* Header */
.widget-card .wr-title {
  font-size: 1.4rem;
  font-weight: 700;
  color: var(--quip-text, #e2e8f0);
  margin: 0 0 0.35rem;
  line-height: 1.25;
}
.widget-card .wr-desc {
  font-size: 0.85rem;
  color: var(--quip-text-dim, #94a3b8);
  margin: 0 0 1rem;
  line-height: 1.5;
}

/* Controls row */
.widget-card .wr-controls {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
  margin-bottom: 1.5rem;
  padding-bottom: 1rem;
  border-bottom: 1px solid var(--quip-border, #1e293b);
}
.widget-card .wr-servings {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  font-size: 0.8rem;
  color: var(--quip-text-dim, #94a3b8);
}
.widget-card .wr-servings-label { text-transform: none; }
.widget-card .wr-serv-group {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.15rem 0.5rem;
  border: 1px solid var(--quip-border-strong, #334155);
  border-radius: 999px;
}
.widget-card .wr-serv-btn {
  font-size: 0.9rem;
  color: var(--quip-text-muted, #64748b);
  user-select: none;
  line-height: 1;
  padding: 0 0.35rem;
  background: none;
  border: none;
  cursor: pointer;
  font-family: inherit;
  transition: color 120ms;
}
.widget-card .wr-serv-btn:hover { color: var(--quip-text, #e2e8f0); }
.widget-card .wr-serv-btn:disabled { opacity: 0.35; cursor: default; }
.widget-card .wr-serv-val {
  font-weight: 600;
  color: var(--quip-text, #e2e8f0);
  min-width: 1.2em;
  text-align: center;
}
.widget-card .wr-meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.75rem;
  color: var(--quip-text-dim, #94a3b8);
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  background: var(--quip-hover, rgba(148,163,184,0.08));
}

/* Section header */
.widget-card .wr-section { margin-bottom: 1.5rem; }
.widget-card .wr-section-title {
  font-size: 0.7rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: var(--quip-text-muted, #64748b);
  margin-bottom: 0.75rem;
}

/* Ingredients */
.widget-card .wr-ingredients { list-style: none; padding: 0; margin: 0; }
.widget-card .wr-ing {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  padding: 0.4rem 0;
  font-size: 0.88rem;
  color: var(--quip-text, #e2e8f0);
  border-bottom: 1px solid color-mix(in srgb, var(--quip-border, #1e293b) 50%, transparent);
}
.widget-card .wr-ing:last-child { border-bottom: none; }
.widget-card .wr-ing-dot {
  width: 4px; height: 4px;
  border-radius: 50%;
  background: var(--quip-text-muted, #64748b);
  flex-shrink: 0;
  transform: translateY(-2px);
}
.widget-card .wr-ing-amount {
  font-weight: 600;
  color: var(--quip-link, #60a5fa);
  min-width: 4em;
  flex-shrink: 0;
}
.widget-card .wr-ing-name { color: var(--quip-text, #e2e8f0); }

/* Steps — hexagon badges with counter */
.widget-card .wr-steps {
  list-style: none;
  padding: 0;
  margin: 0;
  counter-reset: wr-step;
}
.widget-card .wr-step {
  counter-increment: wr-step;
  display: flex;
  align-items: flex-start;
  gap: 0.85rem;
  padding: 0.5rem 0;
  cursor: pointer;
  border-radius: 6px;
  transition: background 120ms;
}
.widget-card .wr-step:hover { background: color-mix(in srgb, var(--quip-hover, rgba(148,163,184,0.08)) 70%, transparent); }
.widget-card .wr-step:focus-visible { outline: 2px solid var(--quip-link, #60a5fa); outline-offset: 2px; }
.widget-card .wr-step-badge {
  position: relative;
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  margin-left: 0.35rem;
  color: color-mix(in srgb, var(--quip-link, #60a5fa) 18%, transparent);
  transition: color 160ms;
}
.widget-card .wr-step-hex { width: 100%; height: 100%; display: block; }
.widget-card .wr-step-check {
  position: absolute;
  inset: 6px;
  width: calc(100% - 12px);
  height: calc(100% - 12px);
  color: var(--quip-bg, #0f172a);
  opacity: 0;
  transform: scale(0.6);
  transition: opacity 160ms, transform 160ms;
}
.widget-card .wr-step-badge::after {
  content: counter(wr-step);
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 0.75rem;
  font-weight: 700;
  color: var(--quip-link, #60a5fa);
  transition: opacity 160ms;
}
.widget-card .wr-step-text {
  font-size: 0.88rem;
  line-height: 1.6;
  color: var(--quip-text, #e2e8f0);
  padding-top: 0.3rem;
  padding-right: 0.5rem;
  transition: color 160ms, text-decoration-color 160ms;
}

/* Done state */
.widget-card .wr-step.wr-step-done .wr-step-badge { color: var(--quip-link, #60a5fa); }
.widget-card .wr-step.wr-step-done .wr-step-badge::after { opacity: 0; }
.widget-card .wr-step.wr-step-done .wr-step-check { opacity: 1; transform: scale(1); }
.widget-card .wr-step.wr-step-done .wr-step-text {
  color: var(--quip-text-muted, #64748b);
  text-decoration: line-through;
  text-decoration-color: color-mix(in srgb, var(--quip-text-muted, #64748b) 60%, transparent);
  text-decoration-thickness: 1.5px;
}

/* Notes */
.widget-card .wr-notes {
  margin-top: 0.5rem;
  padding: 0.9rem 1rem;
  border-radius: 8px;
  background: color-mix(in srgb, var(--quip-hover, rgba(148,163,184,0.08)) 60%, transparent);
  border-left: 2px solid var(--quip-link, #60a5fa);
}
.widget-card .wr-notes .wr-section-title { margin-bottom: 0.4rem; }
.widget-card .wr-notes-text {
  font-size: 0.83rem;
  color: var(--quip-text-dim, #94a3b8);
  line-height: 1.55;
  margin: 0;
  white-space: pre-wrap;
}

/* Tags */
.widget-card .wr-tags {
  display: flex;
  gap: 0.375rem;
  flex-wrap: wrap;
  margin-top: 1rem;
  padding-top: 0.75rem;
  border-top: 1px solid var(--quip-border, #1e293b);
}
.widget-card .wr-tag {
  font-size: 0.7rem;
  padding: 0.2rem 0.55rem;
  border-radius: 4px;
  background: var(--quip-hover, rgba(148,163,184,0.08));
  color: var(--quip-text-muted, #64748b);
}""",
}
