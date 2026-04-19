"""Skill: artifact_svg — Inline SVG vector graphic"""

SKILL = {
    'id': 'artifact_svg',
    'name': 'artifact_svg',
    'description': 'Inline SVG vector graphic',
    'category': 'artifact',
    'icon': None,
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """When creating visualizations, code, diagrams, or data displays, use artifact tags with structured data.

GENERAL RULES:
- Use the SIMPLEST type that fits the data (plot > html for function graphs, chart > html for data viz).
- Keep explanations outside artifact tags.
- Reuse identifier when updating an existing artifact.
- Never wrap the artifact tag in a code fence.

svg — Vector graphic.

Format:
<artifact identifier="id" type="svg" title="Title">
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
  <circle cx="50" cy="50" r="40" fill="steelblue"/>
</svg>
</artifact>

Good for icons, logos, simple diagrams that don't fit the other types.
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
