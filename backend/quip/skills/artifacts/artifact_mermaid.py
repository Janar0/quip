"""Skill: artifact_mermaid — Mermaid diagram (flowchart, sequence, state, class, gantt)"""

SKILL = {
    'id': 'artifact_mermaid',
    'name': 'artifact_mermaid',
    'description': 'Mermaid diagram (flowchart, sequence, state, class, gantt)',
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

mermaid — Diagram using Mermaid syntax.

Format:
<artifact identifier="id" type="mermaid" title="Title">
graph TD;
  A-->B;
  A-->C;
  B-->D;
</artifact>

Good for flowcharts, sequence diagrams, state diagrams, class diagrams, gantt charts.
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
}
