"""Skill: artifact_chart — Data chart: line, bar, pie, doughnut"""

SKILL = {
    'id': 'artifact_chart',
    'name': 'artifact_chart',
    'description': 'Data chart: line, bar, pie, doughnut',
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

chart — Data chart (line, bar, pie, doughnut).

Format:
<artifact identifier="id" type="chart" title="Title">
{"chartType": "bar", "labels": ["A", "B"], "datasets": [{"label": "Series", "data": [10, 20]}]}
</artifact>

Rules:
- chartType is one of: line, bar, pie, doughnut.
- labels is an array of category names.
- datasets is an array; each entry has a label and a data array parallel to labels.
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
