"""Skill: artifact_code — Source code block with syntax highlighting"""

SKILL = {
    'id': 'artifact_code',
    'name': 'artifact_code',
    'description': 'Source code block with syntax highlighting',
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

code — Source code block.

Format:
<artifact identifier="id" type="code" title="Title" language="python">
def hello():
    print("hi")
</artifact>

Rules:
- The `language` attribute drives syntax highlighting.
- Use this when the user asks for runnable code, scripts, or snippets they'll copy.
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
