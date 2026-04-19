"""Skill: music_generation — Generate AI music using the generate_music tool"""

SKILL = {
    'id': 'music_generation',
    'name': 'Music Generation',
    'description': 'Generate AI music using the generate_music tool',
    'category': 'tool',
    'icon': None,
    'type': 'content',
    'enabled': True,
    'is_builtin': True,
    'is_internal': False,
    'prompt_instructions': """## Music Generation

Use the `generate_music` tool to create AI-generated music.

### Inline positioning
The audio player renders **inline at the exact position where you call the tool** — like a photo embedded in an article. Text before the tool call appears above the player; text after appears below. Place the tool call wherever it reads most naturally in your response.

### How to write a prompt
Pack as much detail as possible:
- **Genre / style** — lo-fi hip hop, orchestral, jazz, electronic, ambient, etc.
- **Instruments** — soft piano, acoustic guitar, strings, vinyl crackle, 808 bass, etc.
- **Tempo / BPM** — "90 BPM", "slow", "uptempo"
- **Mood / atmosphere** — relaxing, energetic, melancholic, cinematic, nostalgic
- **Structure hints** — "with a melodic drop at the end", "looping background track"

### After generation
The tool returns `url` pointing to the WAV file. The frontend renders it as an audio player automatically.

**Do NOT write any of these in your response** — they are NOT needed, the player is already rendered:
- The URL itself (`/api/audio/...`)
- JSON objects like `{"music": "..."}` or `{"url": "..."}`
- Placeholder tags like `{music_widget}`, `{music_preview}`, `{audio}`, `[music player]`, etc.

Just write a short description of what was generated in plain prose.

### Examples
```json
{"prompt": "Chill lo-fi hip hop beat with soft piano, vinyl crackle and gentle rain, 85 BPM, relaxing study music"}
{"prompt": "Epic orchestral film score, full strings and brass, building tension, cinematic, 120 BPM"}
{"prompt": "Upbeat jazz cafe background, acoustic bass, brushed snare, muted trumpet, 140 BPM"}
{"prompt": "Ambient electronic soundscape, soft pads, distant synth arpeggios, meditative, 60 BPM"}
```""",
    'data_schema': None,
    'template_html': None,
    'template_css': None,
    'settings_schema': [
        {
            'key': 'model',
            'label': 'Model',
            'type': 'text',
            'default': 'google/lyria-3-clip-preview',
            'help': 'OpenRouter audio model id.',
        },
    ],
    'default_settings': {'model': 'google/lyria-3-clip-preview'},
}
