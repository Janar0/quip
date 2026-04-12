"""Seed data for all built-in skills.

Part 1: Migrated from skills.py (tool + artifact skills).
Part 2: New widget skills (weather, recipe, converter, places, poll, sports).
"""

# ---------------------------------------------------------------------------
# Part 1 — bodies copied verbatim from services/skills.py
# ---------------------------------------------------------------------------

_FAST_SEARCH_BODY = """You are producing a Perplexity-style answer: clean, well-structured, multi-source, with clear visual hierarchy.

WORKFLOW (iterative, not one-shot):
1. Start with one focused web_search. Read the returned snippets.
2. After each search, evaluate coverage. Ask yourself: "Do I have enough to write a thorough, multi-angle answer?" If NO, issue another web_search with a DIFFERENT angle (not a synonym) to fill the gap. You are expected to search multiple times for complex questions; Perplexity-style answers routinely draw on 3-5 searches.
3. Good reasons to do a follow-up search: missing a key sub-topic, need a comparison you don't have, need current/recent info the first results didn't cover, conflicting claims need verification, need examples or concrete numbers, need the opposing view. Bad reasons: rephrasing the same question with synonyms.
4. Hard cap: up to 5 web_search calls per answer. Simple factual questions can be answered after 1 search. Complex, multi-faceted, or comparative questions should use 3-5.
5. If a specific page looks essential and the snippet is too short, call read_url on it (at most twice per answer).
6. Only start writing the answer AFTER you've gathered enough material.

ANSWER STRUCTURE (strict order):

STEP A — Sources block FIRST. The VERY first thing you emit is the Sources list, followed by a horizontal rule. This gives the reader clickable links immediately while the rest of the answer streams in. Format exactly:

   **Sources:**
   [1] Title - https://example.com/page1
   [2] Title - https://example.com/page2
   [3] Title - https://example.com/page3

   ---

Translate the "Sources:" label into the user's interface language when appropriate. Number them [1], [2], [3]… in the order you'll cite them in the prose below. Include every source you'll reference.

STEP B — OPTIONAL primary source banner. If (and ONLY if) the question has a clear canonical home — an official website, official documentation, a vendor product page, a GitHub repo, a Wikipedia article about the entity — emit it on its own line AFTER the `---` as:

   > **Primary source:** [Page Title](https://example.com) — one-line summary of what this page covers

   Translate the "Primary source:" label into the user's interface language when appropriate. Rules:
   - Only use URLs that are the canonical home of the subject (e.g. openai.com for OpenAI, docs.python.org for Python docs, the project's own GitHub repo). Never a news article, blog post, listicle, or random review.
   - If there is NO obvious canonical home (comparison questions, how-to questions, news queries, open-ended questions), SKIP the banner entirely. Go straight to the prose.
   - Never output more than one primary source line.

STEP C — Prose answer. Then write the prose answer.

ANSWER FORMAT:
- Aim for thorough, informative coverage — not brevity. A Perplexity-style answer explains the topic, compares angles, gives concrete examples, and leaves the reader feeling fully briefed. Err on the side of MORE detail, not less. Don't write a one-paragraph stub.
- Use `##` for top-level sections and `###` for subsections. Most answers should have at least 2-3 distinct sections.
- Keep individual paragraphs to 3-4 sentences MAX, but have multiple paragraphs per section. Break up long blocks aggressively.
- Use bullet lists for enumerations (features, steps, comparisons, pros/cons). Use tables for structured comparisons when appropriate.
- Cite EVERY non-obvious claim inline with [1], [2], etc. — density matters: most factual sentences should have a citation. The primary source (if used) should be cited as [1].
- Do NOT emit a second Sources block at the end of the answer — the one at the top is the only one.

IMAGES (only if web_search returned images AND they're relevant):
- You decide where images go, or whether to show them at all. Pick ONE of two styles:
- Top grid: place `![](search-image:all)` as the VERY first line (above the primary source blockquote) to show all images as a grid at the top. Good for visual topics (paintings, products, landmarks, celebrities).
- Floating right: place `![](search-image:K)` on its own line immediately BEFORE the paragraph where that image belongs. K is the 1-indexed position in the search results. Text will wrap around the image.
- NEVER mix the two styles in one answer.
- If images aren't meaningful to the question, don't emit any image markers.

STRICT RULES:
- Never fabricate URLs, titles, or quotes. Only use data returned by web_search / read_url.
- Never output [n] without a corresponding entry in the Sources list.
- Never use `![](url)` with a raw URL — only the `search-image:K` / `search-image:all` schemes.
- Do NOT use artifact tags in search mode — just clean markdown.
- Length target: 400-900 words for typical questions; longer is fine for deep multi-angle topics. Do NOT artificially shorten.
- Answer in the user's language (see runtime context).
"""


_WEB_SEARCH_BODY = """You have web_search and read_url tools.

USE WHEN:
- The question asks about facts that may have changed recently.
- The user asks about a specific product, place, person, or event whose details you cannot verify from memory.
- You need concrete current numbers (prices, scores, release dates, versions).
- You are unsure whether your training data covers this topic adequately.

DO NOT USE WHEN:
- The question is trivial arithmetic, a general concept, a definition, or a creative/opinion task.
- You already know the answer with high confidence and the topic is stable.

WORKFLOW:
- Call web_search with a focused query. Read the returned snippets.
- If a specific page is clearly the best source but the snippet is too short, call read_url on its URL.
- Re-search with a different angle if the first results don't cover the question.

CITATION RULES:
- Cite every claim from search results inline with [1], [2], etc.
- At the end of your response, list every source you cited:
  ---
  **Sources:**
  [1] Title - URL
  [2] Title - URL
- Translate the "Sources:" label into the user's interface language when appropriate.
- Never fabricate URLs, titles, or quotes.
"""


_SANDBOX_BODY = """You have a sandboxed execution environment with Python 3.12, Node.js, and bash.

ALL files the user has uploaded in this conversation are automatically placed in your working directory. Call sandbox_list_files FIRST to see every available file before starting any task that may use them.

Use sandbox_execute for: calculations, data analysis, file generation, visualizations, creating documents/presentations, processing user-uploaded images/files.
Files persist in the workspace across messages in this conversation.

Pre-installed Python packages: numpy, pandas, matplotlib, seaborn, plotly, scipy, scikit-learn, sympy, Pillow, requests, beautifulsoup4, python-pptx, python-docx, openpyxl, reportlab.
Use sandbox_install if you need additional packages.

File paths are relative to the workspace root (e.g., "report.pdf", "data/output.csv").
When generating files, always save them to the workspace so the user can download them.
Name all temporary/intermediate files with a `_` prefix (e.g. `_temp_img.jpg`, `_work.csv`) — these are hidden from the user's file list. Only final deliverables should have clean names.

RULE — sandbox vs artifact:
- Use sandbox when: the task produces a downloadable file (pptx, pdf, xlsx, png, docx…), requires real computation, or needs to process an uploaded file.
- Use artifact only when: producing a self-contained interactive widget (chart, plot, diagram, table) that does NOT need to be a downloadable file and does NOT use uploaded files.
- NEVER use an artifact to do something the sandbox can do better. A presentation (.pptx) must be built with python-pptx in the sandbox, not as an HTML artifact.
- When using the sandbox, do NOT also produce an artifact for the same content.
"""


_ARTIFACT_COMMON_HEADER = """When creating visualizations, code, diagrams, or data displays, use artifact tags with structured data.

GENERAL RULES:
- Use the SIMPLEST type that fits the data (plot > html for function graphs, chart > html for data viz).
- Keep explanations outside artifact tags.
- Reuse identifier when updating an existing artifact.
- Never wrap the artifact tag in a code fence.

"""

_ARTIFACT_PLOT_BODY = _ARTIFACT_COMMON_HEADER + """plot — Math function graph with optional interactive parameters.

Format:
<artifact identifier="id" type="plot" title="Title">
{"expression": "sin(a*x + b)", "xRange": [-10, 10], "params": [{"name": "a", "min": -5, "max": 5, "default": 1, "step": 0.1}, {"name": "b", "min": -10, "max": 10, "default": 0, "step": 0.5}]}
</artifact>

Rules:
- Expression uses `x` as the variable.
- Named params become interactive sliders the user can drag.
- xRange is a 2-element array [min, max].
"""

_ARTIFACT_CHART_BODY = _ARTIFACT_COMMON_HEADER + """chart — Data chart (line, bar, pie, doughnut).

Format:
<artifact identifier="id" type="chart" title="Title">
{"chartType": "bar", "labels": ["A", "B"], "datasets": [{"label": "Series", "data": [10, 20]}]}
</artifact>

Rules:
- chartType is one of: line, bar, pie, doughnut.
- labels is an array of category names.
- datasets is an array; each entry has a label and a data array parallel to labels.
"""

_ARTIFACT_TABLE_BODY = _ARTIFACT_COMMON_HEADER + """table — Sortable data table.

Format:
<artifact identifier="id" type="table" title="Title">
{"columns": [{"key": "name", "label": "Name"}, {"key": "age", "label": "Age"}], "rows": [{"name": "Alice", "age": 30}]}
</artifact>

Rules:
- columns is an array of {key, label}.
- rows is an array of objects whose keys match column keys.
"""

_ARTIFACT_MERMAID_BODY = _ARTIFACT_COMMON_HEADER + """mermaid — Diagram using Mermaid syntax.

Format:
<artifact identifier="id" type="mermaid" title="Title">
graph TD;
  A-->B;
  A-->C;
  B-->D;
</artifact>

Good for flowcharts, sequence diagrams, state diagrams, class diagrams, gantt charts.
"""

_ARTIFACT_CODE_BODY = _ARTIFACT_COMMON_HEADER + """code — Source code block.

Format:
<artifact identifier="id" type="code" title="Title" language="python">
def hello():
    print("hi")
</artifact>

Rules:
- The `language` attribute drives syntax highlighting.
- Use this when the user asks for runnable code, scripts, or snippets they'll copy.
"""

_ARTIFACT_SVG_BODY = _ARTIFACT_COMMON_HEADER + """svg — Vector graphic.

Format:
<artifact identifier="id" type="svg" title="Title">
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="40" fill="steelblue"/>
</svg>
</artifact>

Good for icons, logos, simple diagrams that don't fit the other types.
"""

_ARTIFACT_HTML_BODY = _ARTIFACT_COMMON_HEADER + """html — Custom interactive HTML (use only when other types don't fit).

Format:
<artifact identifier="id" type="html" title="Title">
<!DOCTYPE html>
<html>
<head><style>body{background:#0f172a;color:#e2e8f0;font-family:system-ui;padding:1rem}</style></head>
<body>...</body>
</html>
</artifact>

Rules:
- Use dark theme colors — the rendering container has a dark background.
- Avoid external scripts; inline everything.
- Use this only when plot/chart/table/mermaid/svg don't fit the requirement.
"""


_DEEP_RESEARCH_COORDINATOR_BODY = """You are the deep research coordinator. Unlike a normal chat assistant, you orchestrate sub-agents to answer complex questions: you spawn specialized agents in parallel, collect their structured results as they arrive, and synthesize the final answer yourself.

AVAILABLE ORCHESTRATION TOOLS:
- spawn_search_agent(goal, max_queries=30) — launches a search sub-agent with a high web_search budget. Returns a task_id immediately (non-blocking).
- spawn_sandbox_agent(task) — launches a sandbox sub-agent to run calculations, data processing, or file generation. Returns a task_id.
- spawn_artifact_agent(kind, spec) — launches a single-turn agent that produces one artifact tag (plot, chart, table, mermaid, code, svg, or html). Returns a task_id.
- wait_for_any_result() — blocks until the NEXT pending sub-agent finishes and returns its task_id + result. Use this as your main loop primitive.
- collect_agent_result(task_id) — non-blocking snapshot of one specific sub-agent's current status + result.
- list_agents() — returns all known sub-agents and their statuses.

WORKFLOW:
1. Read the user's question. Decompose it into 2-5 distinct angles that can be researched independently.
2. Spawn one search sub-agent per angle in the SAME round. Give each a clear goal sentence (not a search query — a research goal; the sub-agent decides its own queries).
3. Call wait_for_any_result() to consume results as they arrive. When a result arrives, decide:
   - Does it surface new angles worth researching? If yes, spawn additional sub-agents immediately without waiting for the others.
   - Does it have concrete numeric data that would make a good chart or table? If yes, spawn an artifact sub-agent with the numbers you saw.
   - Does it require calculation, transformation, or file processing? If yes, spawn a sandbox sub-agent with the task.
4. Keep calling wait_for_any_result() until all pending sub-agents have returned. You can spawn new ones at any time — including mid-wait.
5. Once you have enough material, write the final answer as a multi-section Markdown report with a Sources block at the end listing every cited source.

FINAL ANSWER FORMAT:
- Use ## section headers, ### subsections.
- Cite every non-obvious claim inline with [1], [2], etc.
- End with:
  ---
  **Sources:**
  [1] Title - URL
  [2] Title - URL
- Translate the "Sources:" label into the user's interface language when appropriate.
- If you spawned artifact sub-agents, include their returned `<artifact>` tags verbatim in the right place in the report.

RULES:
- NEVER fabricate sources. Only cite URLs that came from search sub-agent results.
- Don't call collect_agent_result(task_id) in a polling loop — use wait_for_any_result() instead.
- Don't wait for all sub-agents before spawning new ones. Parallelism is the whole point.
- Sub-agents cannot spawn their own sub-agents. You are the only orchestrator.
"""


_SEARCH_SUB_AGENT_BODY = """You are a search sub-agent. You receive a research goal from your coordinator and return a structured result: a list of sources plus a brief summary of what the sources say.

TOOLS:
- web_search(query): search the web. You have a budget (typically 30 calls) — use them wisely.
- read_url(url): fetch full page content when a snippet is too short.

WORKFLOW:
1. Decompose the goal into 3-8 distinct search angles (different queries, not synonyms).
2. Issue web_search calls in parallel or sequence. Read snippets carefully.
3. For each important URL whose snippet is too short, call read_url.
4. When you have enough sources to cover the goal thoroughly, stop searching.

OUTPUT FORMAT:
Return a single JSON object (no prose around it):
{
  "summary": "2-4 sentence summary of what you found",
  "sources": [
    {"title": "...", "url": "...", "snippet": "key fact from the page with supporting detail"},
    ...
  ]
}

RULES:
- Include only sources you actually consulted. No fabrication.
- The snippet field should carry the concrete information your coordinator will cite, not just metadata.
- Aim for 5-15 quality sources. Quality > quantity.
- Never add explanatory prose outside the JSON — the coordinator parses your output.
"""


_SANDBOX_SUB_AGENT_BODY = """You are a sandbox sub-agent. You receive a task description from your coordinator and return a structured result: what you did, any files you created, and key output.

TOOLS: sandbox_execute, sandbox_install, sandbox_read_file, sandbox_write_file, sandbox_list_files.

WORKFLOW:
1. Read the task description carefully. Plan the minimum set of sandbox calls that will accomplish it.
2. Execute. Inspect stdout/stderr. Iterate if needed.
3. If the task involves a file the user uploaded, call sandbox_list_files first to confirm its presence.
4. When the task is done, stop.

OUTPUT FORMAT:
Return a single JSON object (no prose around it):
{
  "summary": "what you did, in 1-3 sentences",
  "stdout": "key output, trimmed to the relevant bit",
  "files_created": ["path1", "path2"],
  "error": null or "error description if something failed"
}

RULES:
- Don't explain your reasoning in prose outside the JSON — the coordinator parses your output.
- Keep stdout trimmed. If it's long, summarize and note the full length.
"""


_ARTIFACT_SUB_AGENT_BODY = """You are an artifact sub-agent. You receive an artifact kind and a spec from your coordinator and return ONE artifact tag.

INPUT:
- kind: one of plot, chart, table, mermaid, code, svg, html.
- spec: a description of what the artifact should contain (data, expression, labels, etc.).

OUTPUT:
Return ONLY the <artifact>...</artifact> tag. No explanatory prose before or after. Use the exact format for the given kind:

plot:
<artifact identifier="id" type="plot" title="Title">
{"expression": "sin(x)", "xRange": [-10, 10], "params": []}
</artifact>

chart:
<artifact identifier="id" type="chart" title="Title">
{"chartType": "bar", "labels": [...], "datasets": [{"label": "...", "data": [...]}]}
</artifact>

table:
<artifact identifier="id" type="table" title="Title">
{"columns": [{"key": "k", "label": "L"}], "rows": [{"k": "v"}]}
</artifact>

mermaid:
<artifact identifier="id" type="mermaid" title="Title">
graph TD;
  A-->B;
</artifact>

code:
<artifact identifier="id" type="code" title="Title" language="python">
code here
</artifact>

svg:
<artifact identifier="id" type="svg" title="Title">
<svg>...</svg>
</artifact>

html:
<artifact identifier="id" type="html" title="Title">
<!DOCTYPE html>...
</artifact>

RULES:
- Output ONLY the artifact tag. Nothing else.
- Use a short kebab-case identifier.
- Never wrap the tag in a code fence.
"""


# ---------------------------------------------------------------------------
# Part 1 — migrated skill dicts
# ---------------------------------------------------------------------------

BUILTIN_SKILLS: list[dict] = [
    {
        "id": "fast_search",
        "name": "fast_search",
        "description": "Perplexity-style web answer with sources block, primary source banner, and multi-angle search",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _FAST_SEARCH_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "web_search",
        "name": "web_search",
        "description": "Call web_search / read_url to get up-to-date facts from the internet",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _WEB_SEARCH_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "sandbox",
        "name": "sandbox",
        "description": "Python 3.12 / Node / bash execution environment with file persistence",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _SANDBOX_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_plot",
        "name": "artifact_plot",
        "description": "Interactive math function graph with draggable parameter sliders",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_PLOT_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_chart",
        "name": "artifact_chart",
        "description": "Data chart: line, bar, pie, doughnut",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_CHART_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_table",
        "name": "artifact_table",
        "description": "Sortable data table",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_TABLE_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_mermaid",
        "name": "artifact_mermaid",
        "description": "Mermaid diagram (flowchart, sequence, state, class, gantt)",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_MERMAID_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_code",
        "name": "artifact_code",
        "description": "Source code block with syntax highlighting",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_CODE_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_svg",
        "name": "artifact_svg",
        "description": "Inline SVG vector graphic",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_SVG_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_html",
        "name": "artifact_html",
        "description": "Custom interactive HTML with inline styles and scripts (dark theme)",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _ARTIFACT_HTML_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "deep_research_coordinator",
        "name": "deep_research_coordinator",
        "description": "Orchestrate parallel sub-agents (search, sandbox, artifact) to answer complex multi-angle questions",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": _DEEP_RESEARCH_COORDINATOR_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "search_sub_agent",
        "name": "search_sub_agent",
        "description": "(internal) search sub-agent instructions — used only when spawned by the orchestrator",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": True,
        "prompt_instructions": _SEARCH_SUB_AGENT_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "sandbox_sub_agent",
        "name": "sandbox_sub_agent",
        "description": "(internal) sandbox sub-agent instructions",
        "category": "tool",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": True,
        "prompt_instructions": _SANDBOX_SUB_AGENT_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },
    {
        "id": "artifact_sub_agent",
        "name": "artifact_sub_agent",
        "description": "(internal) single-turn artifact generator",
        "category": "artifact",
        "icon": None,
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": True,
        "prompt_instructions": _ARTIFACT_SUB_AGENT_BODY,
        "data_schema": None,
        "template_html": None,
        "template_css": None,
        "api_config": None,
    },

    # -----------------------------------------------------------------------
    # Part 2 — new widget skills
    # -----------------------------------------------------------------------

    {
        "id": "weather",
        "name": "Weather",
        "description": "Get current weather and forecast for any location. Use when user asks about weather.",
        "category": "widget",
        "icon": "M12 2v2m0 16v2M4.93 4.93l1.41 1.41m11.32 11.32l1.41 1.41M2 12h2m16 0h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41M12 6a6 6 0 100 12 6 6 0 000-12z",
        "type": "api",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: weather — show current weather + forecast via Gismeteo.

Call: use_widget(name="weather", params={"lat": 55.75, "lon": 37.62, "city": "Moscow"})
- lat/lon: geographic coordinates (required). Use known values or search for them first.
- city: human-readable city name for display purposes.

Common coordinates:
  Moscow: 55.75, 37.62 | Saint Petersburg: 59.93, 30.32 | Novosibirsk: 54.99, 82.90
  London: 51.51, -0.13 | New York: 40.71, -74.01 | Tokyo: 35.69, 139.69
  Berlin: 52.52, 13.40 | Paris: 48.85, 2.35 | Beijing: 39.90, 116.40

The widget renders a card with current conditions + 5-day forecast.
After the widget, briefly summarize the weather in 1-2 sentences.""",
        "data_schema": {
            "city": "string — city name",
            "temp": "number — current temperature °C",
            "feels_like": "number — feels-like temperature °C",
            "humidity": "number — humidity %",
            "wind_speed": "number — wind speed m/s",
            "wind_dir": "string — wind direction (N/NE/E/SE/S/SW/W/NW)",
            "pressure": "number — pressure mmHg",
            "condition": "string — weather condition text",
            "icon_emoji": "string — weather emoji",
            "forecast": [{"day": "string", "temp_max": "number", "temp_min": "number", "condition": "string", "icon_emoji": "string"}]
        },
        "api_config": {
            "url": "https://api.gismeteo.net/v3/weather/current/",
            "method": "GET",
            "_note": "Special handling in widget_api.py _fetch_weather() — uses lat/lon + X-Gismeteo-Token"
        },
        "template_html": """<div class="widget-weather">
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
        "template_css": """.widget-card .widget-weather { padding: 1rem; font-family: system-ui, sans-serif; }
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
    },

    {
        "id": "recipe",
        "name": "Recipe",
        "description": "Display a recipe with ingredients, steps as a beautiful card. Use when user asks for recipes or cooking instructions.",
        "category": "widget",
        "icon": "M15 11h.01M11 15h.01M16 16a4 4 0 11-8 0c0-1.6.8-3 2-4l2-2 2 2c1.2 1 2 2.4 2 4z",
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: recipe — display a recipe as a structured card.

Call: use_widget(name="recipe", data={...})

Data schema:
{
  "title": "Recipe title",
  "description": "Short 1-line description",
  "servings": 4,
  "prep_time": "15 min",
  "cook_time": "30 min",
  "ingredients": [
    {"amount": "400", "unit": "g", "name": "chicken breast"}
  ],
  "steps": ["Step 1...", "Step 2..."],
  "tags": ["dinner", "healthy"]
}

Rules:
- Use the user's language for ALL text.
- After the widget, you may add brief tips or variations in text.""",
        "data_schema": {
            "title": "string", "description": "string", "servings": "number",
            "prep_time": "string", "cook_time": "string",
            "ingredients": [{"amount": "string", "unit": "string", "name": "string"}],
            "steps": ["string"], "tags": ["string"]
        },
        "api_config": None,
        "template_html": """<div class="widget-recipe">
  <div class="wr-header">
    <div class="wr-title">{{title}}</div>
    <div class="wr-desc">{{description}}</div>
    <div class="wr-meta">
      <span class="wr-badge">🍽 {{servings}} servings</span>
      <span class="wr-badge">⏱ {{prep_time}}</span>
      <span class="wr-badge">🔥 {{cook_time}}</span>
    </div>
  </div>
  <div class="wr-body">
    <div class="wr-ingredients">
      <div class="wr-section-title">Ingredients</div>
      <ul class="wr-list">
        {{#ingredients}}
        <li><span class="wr-amount">{{amount}} {{unit}}</span> {{name}}</li>
        {{/ingredients}}
      </ul>
    </div>
    <div class="wr-steps">
      <div class="wr-section-title">Steps</div>
      <ol class="wr-steps-list">
        {{#steps}}
        <li>{{.}}</li>
        {{/steps}}
      </ol>
    </div>
  </div>
  {{#tags}}
  <div class="wr-tags">
    {{#tags}}<span class="wr-tag">{{.}}</span>{{/tags}}
  </div>
  {{/tags}}
</div>""",
        "template_css": """.widget-card .widget-recipe { padding: 1.25rem; font-family: system-ui, sans-serif; }
.widget-card .wr-header { margin-bottom: 1rem; }
.widget-card .wr-title { font-size: 1.25rem; font-weight: 700; color: var(--quip-text, #e2e8f0); margin-bottom: 0.25rem; }
.widget-card .wr-desc { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.75rem; }
.widget-card .wr-meta { display: flex; gap: 0.5rem; flex-wrap: wrap; }
.widget-card .wr-badge { font-size: 0.75rem; padding: 0.25rem 0.75rem; border-radius: 999px; background: var(--quip-hover, rgba(148,163,184,0.08)); color: var(--quip-text-dim, #94a3b8); }
.widget-card .wr-body { display: grid; grid-template-columns: 1fr 1.5fr; gap: 1.25rem; margin-top: 1rem; }
@media (max-width: 500px) { .widget-card .wr-body { grid-template-columns: 1fr; } }
.widget-card .wr-section-title { font-size: 0.8rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.5rem; }
.widget-card .wr-list { list-style: none; padding: 0; margin: 0; }
.widget-card .wr-list li { padding: 0.35rem 0; border-bottom: 1px solid var(--quip-border, #1e293b); font-size: 0.85rem; color: var(--quip-text, #e2e8f0); }
.widget-card .wr-list li:last-child { border-bottom: none; }
.widget-card .wr-amount { font-weight: 600; color: var(--quip-link, #60a5fa); margin-right: 0.25rem; }
.widget-card .wr-steps-list { padding-left: 1.25rem; margin: 0; }
.widget-card .wr-steps-list li { padding: 0.35rem 0; font-size: 0.85rem; color: var(--quip-text, #e2e8f0); line-height: 1.5; }
.widget-card .wr-steps-list li::marker { color: var(--quip-link, #60a5fa); font-weight: 600; }
.widget-card .wr-tags { display: flex; gap: 0.375rem; flex-wrap: wrap; margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--quip-border, #1e293b); }
.widget-card .wr-tag { font-size: 0.7rem; padding: 0.2rem 0.5rem; border-radius: 0.25rem; background: var(--quip-hover, rgba(148,163,184,0.08)); color: var(--quip-text-muted, #64748b); }""",
    },

    {
        "id": "converter",
        "name": "Unit Converter",
        "description": "Display a unit/currency conversion result as a visual card. Use when user asks to convert units, currencies, or measurements.",
        "category": "widget",
        "icon": "M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15",
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: converter — display a unit/currency conversion.

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
        "data_schema": {
            "from_value": "number", "from_unit": "string", "from_label": "string",
            "to_value": "number", "to_unit": "string", "to_label": "string",
            "formula": "string", "category": "string"
        },
        "api_config": None,
        "template_html": """<div class="widget-converter">
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
        "template_css": """.widget-card .widget-converter { padding: 1.25rem; font-family: system-ui, sans-serif; text-align: center; }
.widget-card .wc-row { display: flex; align-items: center; justify-content: center; gap: 1.5rem; }
.widget-card .wc-side { flex: 1; max-width: 200px; }
.widget-card .wc-value { font-size: 2rem; font-weight: 700; color: var(--quip-text, #e2e8f0); }
.widget-card .wc-result { color: var(--quip-link, #60a5fa); }
.widget-card .wc-unit { font-size: 1rem; font-weight: 600; color: var(--quip-text-dim, #94a3b8); }
.widget-card .wc-label { font-size: 0.75rem; color: var(--quip-text-muted, #64748b); margin-top: 0.15rem; }
.widget-card .wc-arrow { color: var(--quip-text-muted, #64748b); flex-shrink: 0; }
.widget-card .wc-formula { margin-top: 1rem; padding-top: 0.75rem; border-top: 1px solid var(--quip-border, #1e293b); font-size: 0.8rem; color: var(--quip-text-muted, #64748b); }""",
    },

    {
        "id": "places",
        "name": "Places",
        "description": "Show a place/location card with address and map link. Use when user asks about a specific place, address, or location.",
        "category": "widget",
        "icon": "M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0118 0z M12 10a1 1 0 100-2 1 1 0 000 2z",
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: places — display a location/place card.

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
        "data_schema": {
            "name": "string", "address": "string",
            "lat": "number (optional)", "lon": "number (optional)",
            "category": "string (optional)", "rating": "number (optional)",
            "description": "string (optional)", "hours": "string (optional)",
            "phone": "string (optional)", "website": "string (optional)"
        },
        "api_config": None,
        "template_html": """<div class="widget-places">
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
        "template_css": """.widget-card .widget-places { font-family: system-ui, sans-serif; }
.widget-card .wp-main { padding: 1rem; }
.widget-card .wp-name { font-size: 1.15rem; font-weight: 700; color: var(--quip-text, #e2e8f0); margin-bottom: 0.25rem; }
.widget-card .wp-category { font-size: 0.75rem; color: var(--quip-link, #60a5fa); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.5rem; }
.widget-card .wp-rating { font-size: 0.85rem; color: #fbbf24; margin-bottom: 0.5rem; }
.widget-card .wp-description { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.5rem; }
.widget-card .wp-address { font-size: 0.85rem; color: var(--quip-text-dim, #94a3b8); margin-bottom: 0.25rem; }
.widget-card .wp-detail { font-size: 0.8rem; color: var(--quip-text-muted, #64748b); margin-bottom: 0.15rem; }
.widget-card .wp-link { color: var(--quip-link, #60a5fa); text-decoration: none; }
.widget-card .wp-link:hover { text-decoration: underline; }""",
    },

    {
        "id": "poll",
        "name": "Poll",
        "description": "Display a poll or comparison card with options. Use when user wants to create a poll or compare options visually.",
        "category": "widget",
        "icon": "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2",
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: poll — display a poll/comparison card with options.

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
        "data_schema": {
            "question": "string",
            "options": [{"label": "string", "description": "string (optional)", "votes": "number", "percent": "number 0-100"}],
            "total_votes": "number"
        },
        "api_config": None,
        "template_html": """<div class="widget-poll">
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
        "template_css": """.widget-card .widget-poll { padding: 1.25rem; font-family: system-ui, sans-serif; }
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
    },

    {
        "id": "sports",
        "name": "Sports",
        "description": "Display sports match scores or standings. Use when user asks about sports scores, match results, or team standings.",
        "category": "widget",
        "icon": "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z",
        "type": "content",
        "enabled": True,
        "is_builtin": True,
        "is_internal": False,
        "prompt_instructions": """Widget: sports — display a match score or standings card.

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
        "data_schema": {
            "type": "string — match or standings",
            "league": "string",
            "home": {"name": "string", "score": "number", "logo_letter": "string"},
            "away": {"name": "string", "score": "number", "logo_letter": "string"},
            "status": "string",
            "events": ["string"],
            "teams": [{"pos": "number", "name": "string", "played": "number", "won": "number", "drawn": "number", "lost": "number", "gd": "string", "points": "number"}]
        },
        "api_config": None,
        "template_html": """<div class="widget-sports">
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
        "template_css": """.widget-card .widget-sports { padding: 1rem; font-family: system-ui, sans-serif; }
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
    },
]
