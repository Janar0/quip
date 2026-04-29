"""Skill: artifact_table — Sortable data table"""

SKILL = {
    'id': 'artifact_table',
    'name': 'artifact_table',
    'description': 'Sortable data table',
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

table — Sortable data table.

Format:
<artifact identifier="id" type="table" title="Title">
{"columns": [{"key": "name", "label": "Name"}, {"key": "age", "label": "Age"}], "rows": [{"name": "Alice", "age": 30}]}
</artifact>

Rules:
- columns is an array of {key, label}.
- rows is an array of objects whose keys match column keys.

USE WHEN:
- Displaying structured data with columns and rows
- User needs to sort or scan specific values
- Comparing items across multiple attributes

DO NOT USE WHEN:
- Data fits better as a chart (use chart)
- Only 1-2 rows of data (inline markdown table suffices)
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
