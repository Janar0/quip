"""Skill: image_generation — Generate or edit images using AI image models"""

SKILL = {
    'id': 'image_generation',
    'name': 'Image Generation',
    'description': 'Generate or edit images using AI image models',
    'category': 'tool',
    'type': 'content',
    'enabled': True,
    'prompt_instructions': """## Image Generation

Use the `generate_image` tool to create or edit images.

### Parameters
- **prompt** (required): Describe what to generate in detail. Mention style, mood, lighting, composition.
- **image_urls** (optional): Pass existing image URLs to edit or remix them. Supports `/api/files/...` (uploaded files) and `/api/images/...` (previously generated images).
- **aspect_ratio**: "1:1" (default), "16:9", "9:16", "4:3", "3:4"
- **image_size**: "1K" (default), "0.5K", "2K", "4K"
- **hidden** (optional, boolean): set to `true` when you are going to re-use the image elsewhere (recipe widget hero, inline markdown) and do NOT want a duplicate standalone preview rendered. Default `false` (image is shown inline).

### When to use
- User asks to generate, create, draw, paint, or visualize something
- User asks to edit, modify, or transform an existing image
- User shares image(s) and wants a variation, style transfer, or remix
- Creative or artistic requests of any kind

### Finding uploaded image URLs
When the user attaches images, their URLs are appended to the message text as:
`[Uploaded image URLs: /api/files/uuid1, /api/files/uuid2]`
Use these exact URLs in `image_urls` when editing the user's uploaded images.

### Multi-image (fusion / style transfer)
Pass multiple URLs in `image_urls` — the model blends them according to the prompt.

### Multi-turn editing
Your previous generate_image results are annotated in your own earlier messages as:
`[Generated image URLs: /api/images/abc.png, ...]`
Read your prior message to find the URL, then pass it in `image_urls` to edit that image.

### After generation
The tool returns `url` (first image) and `urls` (all images). By default they are displayed inline in the chat automatically — you don't need to embed them in Markdown. Just write a short description of what you generated.

If you pass `hidden: true`, NOTHING is rendered by the tool — you are responsible for inserting the URL yourself (as a widget image, or inline with `![alt](/api/images/...)`). Use this only when showing the image twice would be redundant.

### Examples
```json
{"prompt": "A sunset over misty mountains, cinematic lighting, ultra-detailed"}
{"prompt": "16:9 product photo of wireless headphones, white background, studio lighting", "aspect_ratio": "16:9"}
{"prompt": "Transform this photo into a watercolor painting", "image_urls": ["/api/files/uuid-here"]}
{"prompt": "Merge the style of the first image with the subject of the second", "image_urls": ["/api/files/id1", "/api/files/id2"]}
{"prompt": "Add dramatic storm clouds to the sky", "image_urls": ["/api/images/prev.png"]}
```""",
    'settings_schema': [
        {
            'key': 'model',
            'label': 'Model',
            'type': 'text',
            'default': 'google/gemini-2.0-flash-exp:free',
            'help': 'OpenRouter image model id.',
        },
    ],
    'default_settings': {'model': 'google/gemini-2.0-flash-exp:free'},
}
