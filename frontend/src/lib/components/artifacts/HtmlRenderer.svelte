<script lang="ts">
  let { content, title = '', allowScripts = true }: { content: string; title?: string; allowScripts?: boolean } = $props();

  // Inject dark theme base styles
  let themedContent = $derived.by(() => {
    const darkCSS = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src * data: blob:; media-src * data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><style>
      :root { color-scheme: dark; }
      body { background: #111; color: #e0e0e0; font-family: system-ui, sans-serif; margin: 0; padding: 16px; }
      input, select, button, textarea { color-scheme: dark; background: #222; color: #e0e0e0; border: 1px solid #444; border-radius: 4px; padding: 4px 8px; }
      button { cursor: pointer; }
      button:hover { background: #333; }
    </style>`;
    if (content.includes('</head>')) {
      return content.replace('</head>', darkCSS + '</head>');
    }
    return darkCSS + content;
  });
</script>

<iframe
  srcdoc={themedContent}
  sandbox={allowScripts ? 'allow-scripts allow-downloads' : 'allow-downloads'}
  class="w-full border-0"
  style="min-height: 300px; height: 500px; background: #111;"
  {title}
></iframe>
