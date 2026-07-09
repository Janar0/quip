<script lang="ts">
  import { onDestroy } from 'svelte';
  import { widgetTemplates, widgetTemplatesLoaded } from '$lib/stores/widgets';
  import Mustache from 'mustache';

  let { templateName, data }: { templateName: string; data: Record<string, unknown> } = $props();

  let templates = $state<Record<string, { template_html: string; template_css: string }>>({});
  let loaded = $state(false);
  const unsub1 = widgetTemplates.subscribe(v => { templates = v; });
  const unsub2 = widgetTemplatesLoaded.subscribe(v => { loaded = v; });
  onDestroy(() => { unsub1(); unsub2(); });

  let renderedHtml = $derived.by(() => {
    const tpl = templates[templateName];
    if (!tpl) {
      if (!loaded) return `<div style="padding:0.75rem;font-family:system-ui;opacity:0.4;font-size:0.8rem">Loading widget…</div>`;
      return `<div style="padding:0.75rem;font-family:system-ui;opacity:0.4;font-size:0.8rem">Widget "${templateName}" not found</div>`;
    }
    try {
      const body = Mustache.render(tpl.template_html, data);
      const css = tpl.template_css ?? '';
      return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src * data: blob:; media-src * data: blob:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'"><style>html,body{margin:0;background:transparent;color:#e5e7eb}.widget-card{overflow:hidden}${css}</style></head><body><div class="widget-card"><script>const root=document.querySelector('.widget-card');<\/script>${body}</div></body></html>`;
    } catch {
      return '<div style="padding:0.75rem;color:#f87171;font-size:0.8rem">Template render error</div>';
    }
  });

</script>

<iframe
  srcdoc={renderedHtml}
  sandbox="allow-scripts allow-downloads"
  title={templateName}
  class="widget-card block w-full min-h-72 overflow-hidden border-0 my-1"
></iframe>
