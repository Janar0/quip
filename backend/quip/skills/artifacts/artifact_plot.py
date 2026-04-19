"""Skill: artifact_plot — Interactive math function graph with draggable parameter sliders"""

SKILL = {
    'id': 'artifact_plot',
    'name': 'artifact_plot',
    'description': 'Interactive math function graph with draggable parameter sliders',
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

plot — Math function graph with optional interactive parameters.

Format:
<artifact identifier="id" type="plot" title="Title">
{"expression": "sin(a*x + b)", "xRange": [-10, 10], "params": [{"name": "a", "min": -5, "max": 5, "default": 1, "step": 0.1}, {"name": "b", "min": -10, "max": 10, "default": 0, "step": 0.5}]}
</artifact>

Rules:
- Expression uses `x` as the variable.
- Named params become interactive sliders the user can drag.
- xRange is a 2-element array [min, max].
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
