<script lang="ts">
  import { t } from 'svelte-i18n';
  import { selectedModel, setDefaultModel } from '$lib/stores/chat';
  import { modelList, modelsLoaded, adminDefaultModel, type ModelItem } from '$lib/stores/models';

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

  function fmtCtx(n: number): string {
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(0) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(0) + 'K';
    return String(n);
  }

  // Auto-select when current model is empty or not in the model list.
  // Priority: admin default → first available.
  $effect(() => {
    if (!loaded || models.length === 0) return;
    if (models.find((m) => m.id === $selectedModel)) return;

    const fallback = ($adminDefaultModel && models.find((m) => m.id === $adminDefaultModel))
      ? $adminDefaultModel
      : models[0].id;

    $selectedModel = fallback;
    localStorage.setItem('default_model', fallback);
  });
</script>

<div class="flex items-center gap-2">
  {#if !loaded && models.length === 0}
    <span class="text-xs opacity-50">{$t('models.loading')}</span>
  {:else if models.length === 0}
    <span class="text-xs opacity-50">{$t('models.noModels')}</span>
  {:else}
    <select class="text-sm rounded-lg px-3 py-1.5 w-40 sm:w-56 focus:outline-none" style="background: var(--quip-bg-raised); border: 1px solid var(--quip-border-strong); color: var(--quip-text)" bind:value={$selectedModel}>
      {#each grouped as [provider, items]}
        <optgroup label={provider.charAt(0).toUpperCase() + provider.slice(1)}>
          {#each items as m}
            <option value={m.id} title="{fmtCtx(m.context_length)} ctx | ${m.pricing.prompt}/tok">{m.display_name || m.name}</option>
          {/each}
        </optgroup>
      {/each}
    </select>
    {#if selectedInfo}
      <span class="hidden sm:inline text-xs text-slate-600">{fmtCtx(selectedInfo.context_length)} ctx</span>
    {/if}
    {#if !isDefault}
      <button
        class="hidden sm:flex p-1.5 rounded-lg border border-slate-800 text-slate-500 hover:text-slate-300 hover:border-slate-700 transition-colors text-xs"
        onclick={() => setDefaultModel($selectedModel)}
        title={$t('models.saveDefault')}
      >
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>
      </button>
    {/if}
  {/if}
</div>
