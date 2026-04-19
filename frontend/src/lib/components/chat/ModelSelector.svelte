<script lang="ts">
  import { t } from 'svelte-i18n';
  import { SvelteSet } from 'svelte/reactivity';
  import { selectedModel, setDefaultModel } from '$lib/stores/chat';
  import { modelList, modelsLoaded, adminDefaultModel, type ModelItem } from '$lib/stores/models';

  let { variant = 'pill' }: { variant?: 'pill' | 'picker' } = $props();

  let open = $state(false);
  let rootEl: HTMLDivElement;
  let triggerEl = $state<HTMLButtonElement | undefined>();
  let menuStyle = $state('');

  function portal(node: HTMLElement) {
    document.body.appendChild(node);
    return { destroy: () => { if (node.parentNode) node.parentNode.removeChild(node); } };
  }

  function placeMenu() {
    if (!triggerEl) return;
    const r = triggerEl.getBoundingClientRect();
    const menuW = 320;
    const vw = window.innerWidth;
    // Always center the menu under the trigger — both pill and picker variants.
    let left = r.left + r.width / 2 - menuW / 2;
    left = Math.max(8, Math.min(vw - menuW - 8, left));
    const top = r.bottom + 10;
    menuStyle = `top: ${top}px; left: ${left}px; width: ${menuW}px;`;
  }

  let models = $derived($modelList);
  let loaded = $derived($modelsLoaded);
  let isDefault = $derived(localStorage.getItem('default_model') === $selectedModel);

  let grouped = $derived.by(() => {
    const groups: Record<string, ModelItem[]> = {};
    for (const m of models) {
      const provider = m.id.split('/')[0] ?? 'other';
      (groups[provider] ??= []).push(m);
    }
    return Object.entries(groups).sort(([a], [b]) => a.localeCompare(b));
  });

  let selectedInfo = $derived(models.find((m) => m.id === $selectedModel));
  let provider = $derived(selectedInfo ? (selectedInfo.id.split('/')[0] ?? 'other') : '');
  let providerLabel = $derived(provider.charAt(0).toUpperCase() + provider.slice(1));

  // Keyword → lobe-icons slug. First regex that matches the combined text of
  // id/name/display_name/provider wins. Backend no longer gates by whitelist —
  // any unknown slug just renders as no-icon via <img onerror>, so adding a
  // new provider is a one-line table entry and nothing breaks if it's wrong.
  const ICON_PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
    [/claude|anthropic/, 'claude'],
    [/gemini/, 'gemini'],
    [/\bgpt\b|\bo[134]\b|openai/, 'openai'],
    [/llama|\bmeta\b/, 'meta'],
    [/mi[xs]tral/, 'mistral'],
    [/deepseek/, 'deepseek'],
    [/grok|\bxai\b|x-ai/, 'grok'],
    [/qwen|alibaba/, 'qwen'],
    [/glm|chatglm|zhipu|z-ai|z\.ai/, 'zhipu'],
    [/perplexity|sonar/, 'perplexity'],
    [/command|cohere/, 'cohere'],
    [/moonshot|kimi/, 'moonshot'],
    [/\byi[-\s]/, 'yi'],
    [/minimax/, 'minimax'],
    [/doubao/, 'doubao'],
    [/stepfun|step-/, 'stepfun'],
    [/mimo|xiaomi/, 'xiaomimimo'],
    [/ernie|wenxin|baidu/, 'wenxin'],
    [/hunyuan|tencent/, 'hunyuan'],
    [/internlm/, 'internlm'],
    [/gemma/, 'gemma'],
    [/\bphi-?\d/, 'phi'],
    [/jamba|ai21/, 'ai21'],
    [/nemotron|nvidia/, 'nvidia'],
    [/reka/, 'reka'],
    [/liquid/, 'liquid'],
  ];

  // Display name without the "Provider: " prefix — the provider is already
  // communicated by the brand icon, so stripping it keeps the pill compact.
  function shortName(m: ModelItem | undefined): string {
    const raw = m?.display_name || m?.name || 'Model';
    return raw.replace(/^[^:]{1,32}:\s*/, '');
  }

  function iconSlug(m: ModelItem | undefined): string {
    if (!m) return 'openai';
    const hay = `${m.id} ${m.name} ${m.display_name ?? ''} ${m.provider ?? ''}`.toLowerCase();
    for (const [re, slug] of ICON_PATTERNS) {
      if (re.test(hay)) return slug;
    }
    return (m.id.split('/')[0] ?? m.provider ?? '').toLowerCase() || 'openai';
  }

  // Persistent negative cache — slugs that returned 404 at least once. Avoids
  // re-requesting them on every reload (browser 404 caching is unreliable).
  // Uses SvelteSet so .add/.has participate in fine-grained reactivity —
  // a plain Set wrapped in $state doesn't trigger derived re-evaluation.
  const MISS_KEY = 'provider_icon_miss';
  function loadMissed(): string[] {
    try { return JSON.parse(localStorage.getItem(MISS_KEY) ?? '[]'); }
    catch { return []; }
  }
  const missedSlugs = new SvelteSet<string>(loadMissed());
  function markMissed(slug: string) {
    if (missedSlugs.has(slug)) return;
    missedSlugs.add(slug);
    try { localStorage.setItem(MISS_KEY, JSON.stringify([...missedSlugs])); }
    catch { /* quota */ }
  }

  let currentSlug = $derived(iconSlug(selectedInfo));
  let iconUrl = $derived(
    selectedInfo && !missedSlugs.has(currentSlug)
      ? `/api/provider-icon/${currentSlug}`
      : ''
  );

  function fmtCtx(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(0) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K';
    return String(n);
  }

  function pick(id: string) {
    $selectedModel = id;
    open = false;
  }

  $effect(() => {
    if (!loaded || models.length === 0) return;
    if (models.find((m) => m.id === $selectedModel)) return;

    const fallback = ($adminDefaultModel && models.find((m) => m.id === $adminDefaultModel))
      ? $adminDefaultModel
      : models[0].id;

    $selectedModel = fallback;
    localStorage.setItem('default_model', fallback);
  });

  $effect(() => {
    if (!open) return;
    placeMenu();
    function onDocClick(e: MouseEvent) {
      const t = e.target as Node;
      if (rootEl && !rootEl.contains(t)) {
        // menu is a portal-ish fixed element outside rootEl — check too
        const menu = document.querySelector('.quip-model-menu');
        if (menu && menu.contains(t)) return;
        open = false;
      }
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') open = false;
    }
    function onResize() { placeMenu(); }
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onKey);
    window.addEventListener('resize', onResize);
    window.addEventListener('scroll', onResize, true);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onKey);
      window.removeEventListener('resize', onResize);
      window.removeEventListener('scroll', onResize, true);
    };
  });
</script>

<div class="flex items-center gap-2" bind:this={rootEl}>
  {#if !loaded && models.length === 0}
    <span class="text-xs opacity-50">{$t('models.loading')}</span>
  {:else if models.length === 0}
    <span class="text-xs opacity-50">{$t('models.noModels')}</span>
  {:else if variant === 'picker'}
    <!-- Big model picker (start screen) -->
    <div class="relative">
      <button
        type="button"
        class="quip-model-picker"
        bind:this={triggerEl}
        onclick={() => (open = !open)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {#if iconUrl}
          <img src={iconUrl} alt={providerLabel} class="quip-provider-icon" onerror={() => markMissed(currentSlug)} />
        {/if}
        <span class="name">{shortName(selectedInfo)}</span>
        {#if selectedInfo}
          <span class="sep">·</span>
          <span class="sub">{fmtCtx(selectedInfo.context_length)} ctx</span>
        {/if}
        <svg class="w-3.5 h-3.5 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--quip-text-muted); transform: {open ? 'rotate(180deg)' : ''};">
          <path d="M6 9l6 6 6-6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      {#if open}
        <div class="quip-model-menu" style={menuStyle} role="listbox" use:portal>
          {#each grouped as [p, items]}
            <div class="group-lbl">{p.charAt(0).toUpperCase() + p.slice(1)}</div>
            {#each items as m (m.id)}
              <button
                type="button"
                class="opt {m.id === $selectedModel ? 'sel' : ''}"
                role="option"
                aria-selected={m.id === $selectedModel}
                onclick={() => pick(m.id)}
              >
                <span class="l">
                  <span class="name">{shortName(m)}</span>
                  <span class="meta">{fmtCtx(m.context_length)}</span>
                </span>
                <svg class="check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
            {/each}
          {/each}
        </div>
      {/if}
    </div>
  {:else}
    <!-- Compact pill (chat header) -->
    <div class="relative">
      <button
        type="button"
        class="quip-model-pill"
        bind:this={triggerEl}
        onclick={() => (open = !open)}
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        {#if iconUrl}
          <img src={iconUrl} alt={providerLabel} class="quip-provider-icon" onerror={() => markMissed(currentSlug)} />
        {/if}
        <span>{shortName(selectedInfo)}</span>
        {#if selectedInfo}
          <span class="sep">·</span>
          <span class="sub">{fmtCtx(selectedInfo.context_length)}</span>
        {/if}
        <svg class="w-3 h-3 transition-transform" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--quip-text-muted); transform: {open ? 'rotate(180deg)' : ''};">
          <path d="M6 9l6 6 6-6" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
      </button>
      {#if open}
        <div class="quip-model-menu" style={menuStyle} role="listbox" use:portal>
          {#each grouped as [p, items]}
            <div class="group-lbl">{p.charAt(0).toUpperCase() + p.slice(1)}</div>
            {#each items as m (m.id)}
              <button
                type="button"
                class="opt {m.id === $selectedModel ? 'sel' : ''}"
                role="option"
                aria-selected={m.id === $selectedModel}
                onclick={() => pick(m.id)}
              >
                <span class="l">
                  <span class="name">{shortName(m)}</span>
                  <span class="meta">{fmtCtx(m.context_length)}</span>
                </span>
                <svg class="check" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
              </button>
            {/each}
          {/each}
        </div>
      {/if}
    </div>
    {#if !isDefault}
      <button
        class="hidden sm:flex p-1.5 rounded-lg quip-icon-btn active:scale-[0.92] text-xs"
        onclick={() => setDefaultModel($selectedModel)}
        title={$t('models.saveDefault')}
        aria-label={$t('models.saveDefault')}
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
      </button>
    {/if}
  {/if}
</div>
