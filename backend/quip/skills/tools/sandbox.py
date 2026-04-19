"""Skill: sandbox — Python 3.12 / Node / bash execution environment with file persistence"""

SKILL = {
    'id': 'sandbox',
    'name': 'sandbox',
    'description': 'Python 3.12 / Node / bash execution environment with file persistence',
    'category': 'tool',
    'icon': None,
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """You have a sandboxed execution environment with Python 3.12, Node.js, and bash.

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
""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'api_config': None,
    'settings_schema': [
        {'key': 'memory_limit', 'label': 'Memory limit', 'type': 'text', 'default': '512m'},
        {'key': 'cpu_limit', 'label': 'CPU limit', 'type': 'text', 'default': '1.0'},
        {'key': 'idle_timeout', 'label': 'Idle timeout (sec)', 'type': 'number', 'default': 600},
        {'key': 'exec_timeout', 'label': 'Exec timeout (sec)', 'type': 'number', 'default': 30},
    ],
    'default_settings': {
        'memory_limit': '512m', 'cpu_limit': '1.0',
        'idle_timeout': 600, 'exec_timeout': 30,
    },
}
