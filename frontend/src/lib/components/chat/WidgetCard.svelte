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

  let rootEl: HTMLDivElement | undefined = $state();

  function appendAuthTokenToMedia(html: string): string {
    if (typeof localStorage === 'undefined') return html;
    const token = localStorage.getItem('access_token') || '';
    if (!token) return html;
    const enc = encodeURIComponent(token);
    return html.replace(
      /((?:https?:\/\/[^\s"'()]+)?\/api\/(?:images|audio|files)\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*)/g,
      (url) => {
        if (/[?&]token=/.test(url)) return url;
        const sep = url.includes('?') ? '&' : '?';
        return `${url}${sep}token=${enc}`;
      },
    );
  }

  function extractAndRunScripts(element: HTMLElement) {
    const scripts = element.querySelectorAll('script');
    scripts.forEach(s => {
      const code = s.textContent || '';
      s.remove();
      if (!code.trim()) return;
      try {
        const fn = new Function('root', code);
        fn(element);
      } catch (e) {
        console.warn('Widget script error:', e);
      }
    });
  }

  let renderedHtml = $derived.by(() => {
    const tpl = templates[templateName];
    if (!tpl) {
      if (!loaded) return `<div style="padding:0.75rem;font-family:system-ui;opacity:0.4;font-size:0.8rem">Loading widget…</div>`;
      return `<div style="padding:0.75rem;font-family:system-ui;opacity:0.4;font-size:0.8rem">Widget "${templateName}" not found</div>`;
    }
    try {
      const body = Mustache.render(tpl.template_html, data);
      const css = tpl.template_css ?? '';
      const merged = css ? `<style>${css}</style>${body}` : body;
      return appendAuthTokenToMedia(merged);
    } catch {
      return '<div style="padding:0.75rem;color:#f87171;font-size:0.8rem">Template render error</div>';
    }
  });

  $effect(() => {
    renderedHtml;
    if (!rootEl) return;
    extractAndRunScripts(rootEl);
  });
</script>

<div bind:this={rootEl} class="widget-card overflow-hidden my-1">
  {@html renderedHtml}
</div>
