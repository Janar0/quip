"""Skill: fast_search — multi-angle web answers with inline citations."""

SKILL = {
    'id': 'fast_search',
    'name': 'fast_search',
    'description': 'Multi-angle web answers with inline citations and retrieved sources',
    'category': 'tool',
    'icon': None,
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """You are producing a well-structured, multi-source answer with inline citations.

WORKFLOW (iterative, not one-shot):
1. Start with one focused web_search. Read the returned snippets.
2. After each search, evaluate coverage. Ask yourself: "Do I have enough to write a thorough, multi-angle answer?" If NO, issue another web_search with a DIFFERENT angle (not a synonym) to fill the gap. You are expected to search multiple times for complex questions.
3. Good reasons to do a follow-up search: missing a key sub-topic, need a comparison you don't have, need current/recent info the first results didn't cover, conflicting claims need verification, need examples or concrete numbers, need the opposing view. Bad reasons: rephrasing the same question with synonyms.
4. Hard cap: up to 5 web_search calls per answer. Simple factual questions can be answered after 1 search. Complex, multi-faceted, or comparative questions should use 3-5.
5. If a specific page looks essential and the snippet is too short, call read_url on it (at most twice per answer).
6. Only start writing the answer AFTER you've gathered enough material.

RETRIEVAL OUTCOMES:
- Check the `status` returned by every web_search call. `error` means retrieval failed: say web search was unavailable and do not present a web-grounded answer or citations.
- `no_results` means the search completed without usable sources: say no sources were found and do not invent citations or imply that current facts were verified.
- `partial` means some retrieval succeeded and some did not: use only the returned source links, and disclose a limitation when it affects the answer.
- Only cite URLs and claims supported by actual returned sources. A failed or empty search is not a source.

ANSWER STRUCTURE:
- Write the prose answer with inline citations [1], [2], etc.
- Number unique result URLs in first-seen order. Cite only claims supported by returned results.
- Search result links are evidence to evaluate, not proof of every claim; do not imply every returned page was opened or read.
- Do NOT write a Sources/Источники block or list source URLs. Quip appends a Sources footer from validated search-result metadata.

CITATION RULES:
- Cite EVERY non-obvious claim inline with [1], [2], etc.
- When you search multiple times, number sources sequentially: first search = [1]...[N], second = [N+1]...[M].
- Every [n] must refer to a relevant returned result.

ANSWER FORMAT:
- Aim for thorough, informative coverage — not brevity. Explain the topic, compare angles, give concrete examples.
- Use `##` for top-level sections and `###` for subsections.
- Keep individual paragraphs to 3-4 sentences MAX, but have multiple paragraphs per section.
- Use bullet lists for features, steps, comparisons, pros/cons.
- Use tables for structured comparisons when appropriate.

IMAGES (only if web_search returned images AND they're relevant):
- You decide where images go, or whether to show them at all. Pick ONE of two styles:
- Top grid: place `![](search-image:all)` as the VERY first line to show all images as a grid at the top.
- Floating right: place `![](search-image:K)` on its own line immediately BEFORE the paragraph where it belongs.
- NEVER mix the two styles in one answer.
- If images aren't meaningful to the question, don't emit any image markers.

STRICT RULES:
- Never fabricate URLs, titles, or quotes. Only use data returned by web_search / read_url.
- Never use `![](url)` with a raw URL — only the `search-image:K` / `search-image:all` schemes.
- Do NOT use artifact tags in search mode — just clean markdown.
- Length target: 400-900 words for typical questions; longer is fine for deep multi-angle topics.
- Answer in the user's language (see runtime context).
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
