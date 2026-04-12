<script lang="ts">
  import { onDestroy } from 'svelte';
  import { widgetTemplates } from '$lib/stores/widgets';
  import Mustache from 'mustache';

  let { templateName, data }: { templateName: string; data: Record<string, unknown> } = $props();

  let templates = $state<Record<string, { template_html: string; template_css: string }>>({});
  const unsub = widgetTemplates.subscribe(v => { templates = v; });
  onDestroy(unsub);

  let renderedHtml = $derived.by(() => {
    const tpl = templates[templateName];
    if (!tpl) return `<div style="padding:1rem;font-family:system-ui;opacity:0.5;font-size:0.85rem">Widget "${templateName}" not loaded</div>`;
    try {
      return Mustache.render(tpl.template_html, data);
    } catch {
      return '<div style="padding:1rem;color:#f87171;font-size:0.85rem">Template render error</div>';
    }
  });

  let css = $derived(templates[templateName]?.template_css ?? '');
</script>

<div class="widget-card rounded-xl border border-slate-800 overflow-hidden my-1">
  {#if css}
    <!-- svelte-ignore css_unused_selector -->
    <style>{css}</style>
  {/if}
  {@html renderedHtml}
</div>
