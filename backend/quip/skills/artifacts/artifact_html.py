"""Skill: artifact_html — Custom interactive HTML with inline styles and scripts (dark theme)"""

SKILL = {
    'id': 'artifact_html',
    'name': 'artifact_html',
    'description': 'Custom interactive HTML with inline styles and scripts (dark theme)',
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

html — Custom interactive HTML (use only when other types don't fit).

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
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
