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
    // Matches /api/images/... /api/audio/... /api/files/... ending at a quote, whitespace, or closing paren
    return html.replace(
      /((?:https?:\/\/[^\s"'()]+)?\/api\/(?:images|audio|files)\/[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*)/g,
      (url) => {
        if (/[?&]token=/.test(url)) return url;
        const sep = url.includes('?') ? '&' : '?';
        return `${url}${sep}token=${enc}`;
      },
    );
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
    // re-run when HTML changes
    renderedHtml;
    if (!rootEl) return;
    if (templateName === 'recipe') {
      initRecipe(rootEl);
    }
  });

  function formatAmount(n: number): string {
    if (!isFinite(n)) return '';
    if (Number.isInteger(n)) return String(n);
    const r = Math.round(n * 100) / 100;
    return String(r).replace(/\.?0+$/, '');
  }

  function initRecipe(root: HTMLElement) {
    const val = root.querySelector<HTMLElement>('[data-wr-serv-val]');
    const dec = root.querySelector<HTMLButtonElement>('[data-wr-serv="-"]');
    const inc = root.querySelector<HTMLButtonElement>('[data-wr-serv="+"]');
    if (val && dec && inc) {
      const base = parseFloat(val.dataset.wrServBase || val.textContent || '1') || 1;
      let current = base;
      const amounts = Array.from(root.querySelectorAll<HTMLElement>('[data-wr-base-amount]'));
      const update = () => {
        val.textContent = String(Math.round(current));
        dec.disabled = current <= 1;
        amounts.forEach(el => {
          const raw = (el.dataset.wrBaseAmount || '').trim();
          const unit = el.dataset.wrUnit || '';
          const suffix = unit ? ` ${unit}` : '';
          // Scale only if the amount is a pure number (optional decimal/comma)
          if (/^-?\d+([.,]\d+)?$/.test(raw)) {
            const baseAmt = parseFloat(raw.replace(',', '.'));
            const scaled = baseAmt * current / base;
            el.textContent = formatAmount(scaled) + suffix;
          } else {
            el.textContent = raw + suffix;
          }
        });
      };
      dec.onclick = () => { if (current > 1) { current -= 1; update(); } };
      inc.onclick = () => { current += 1; update(); };
      update();
    }

    root.querySelectorAll<HTMLElement>('[data-wr-step]').forEach(step => {
      const toggle = () => step.classList.toggle('wr-step-done');
      step.onclick = toggle;
      step.onkeydown = (e: KeyboardEvent) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle(); }
      };
    });
  }
</script>

<div bind:this={rootEl} class="widget-card overflow-hidden my-1">
  {@html renderedHtml}
</div>
