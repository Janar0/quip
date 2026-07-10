"""Skill: web_search — Call web_search / read_url to get up-to-date facts from the internet"""

SKILL = {
    'id': 'web_search',
    'name': 'web_search',
    'description': 'Call web_search / read_url to get up-to-date facts from the internet',
    'category': 'tool',
    'icon': None,
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """You have web_search and read_url tools.

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
- At the end, append a Sources block — strict format, one source per line:
  ---
  **Sources:**
  [1] Exact page title - https://full-url.com/page
  [2] Exact page title - https://another-url.org/doc
- Translate "Sources:" label into the user's language.
- When you search multiple times, number sources sequentially: first search = [1]...[N], second = [N+1]...[M].
- CRITICAL: every line must start with [N]. Use " - " between title and full URL. Never split across lines. Never use domain names or site descriptions (like "Facebook Group", "Reddit") as URLs — always use the full real URL.
- Only present what the search actually returned.
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
    'settings_schema': [
        {'key': 'provider', 'label': 'Provider', 'type': 'select',
         'options': ['searxng', 'tavily'], 'default': 'searxng'},
        {'key': 'tavily_api_key', 'label': 'Tavily API key', 'type': 'password', 'default': ''},
        {'key': 'searxng_url', 'label': 'SearXNG URL', 'type': 'text', 'default': '',
         'help': 'Only used when provider = searxng.'},
    ],
    'default_settings': {'provider': 'searxng', 'tavily_api_key': '', 'searxng_url': ''},
}
