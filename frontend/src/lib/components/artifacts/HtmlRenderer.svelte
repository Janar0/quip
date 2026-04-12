<script lang="ts">
  let { content, title = '' }: { content: string; title?: string } = $props();

  // Inject dark theme base styles
  let themedContent = $derived.by(() => {
    const darkCSS = `<style>
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
  sandbox="allow-scripts allow-downloads"
  class="w-full border-0"
  style="min-height: 300px; height: 500px; background: #111;"
  {title}
></iframe>
