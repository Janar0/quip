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
      return Mustache.render(tpl.template_html, data);
    } catch {
      return '<div style="padding:0.75rem;color:#f87171;font-size:0.8rem">Template render error</div>';
    }
  });

  let css = $derived(templates[templateName]?.template_css ?? '');
</script>

<div class="widget-card rounded-xl overflow-hidden my-1" style="border: 1px solid var(--quip-border)">
  {#if css}
    <!-- svelte-ignore css_unused_selector -->
    <style>{css}</style>
  {/if}
  {@html renderedHtml}
</div>
