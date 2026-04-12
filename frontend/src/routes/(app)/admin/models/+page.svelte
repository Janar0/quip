<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { getSettings, updateSettings, getAdminModels } from '$lib/api/admin';

  let whitelist = $state<string[]>([]);
  let modelAliases = $state<Record<string, string>>({});
  let allModels = $state<{ id: string; name: string }[]>([]);
  let saving = $state(false);
  let loading = $state(true);
  let search = $state('');

  // System models
  let searchModel = $state('');
  let researchModel = $state('');
  let titleModel = $state('');
  let defaultModel = $state('');
  let savingSystemModels = $state(false);

  let filtered = $derived(
    search.trim()
      ? allModels.filter(
          (m) =>
            m.name.toLowerCase().includes(search.toLowerCase()) ||
            m.id.toLowerCase().includes(search.toLowerCase()),
        )
      : allModels,
  );

  onMount(async () => {
    const [settings, models] = await Promise.all([getSettings(), getAdminModels()]);
    whitelist = settings.model_whitelist ?? [];
    modelAliases = settings.model_aliases ?? {};
    searchModel = settings.search_model ?? '';
    researchModel = settings.research_model ?? '';
    titleModel = settings.title_model ?? '';
    defaultModel = settings.default_model ?? '';
    allModels = models;
    loading = false;
  });

  async function saveSystemModels() {
    savingSystemModels = true;
    const ok = await updateSettings({ search_model: searchModel, research_model: researchModel, title_model: titleModel, default_model: defaultModel });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.settingsSaved') : $t('admin.failedToSave'));
    savingSystemModels = false;
  }

  function toggleWhitelist(modelId: string) {
    if (whitelist.includes(modelId)) {
      whitelist = whitelist.filter((id) => id !== modelId);
    } else {
      whitelist = [...whitelist, modelId];
    }
  }

  function selectAll() {
    whitelist = allModels.map((m) => m.id);
  }

  function selectNone() {
    whitelist = [];
  }

  async function saveWhitelist() {
    saving = true;
    const ok = await updateSettings({ model_whitelist: whitelist });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.settingsSaved') : $t('admin.failedToSave'));
    saving = false;
  }

  async function saveAliases() {
    saving = true;
    const ok = await updateSettings({ model_aliases: modelAliases });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.settingsSaved') : $t('admin.failedToSave'));
    saving = false;
  }
</script>

<div class="p-8 max-w-2xl space-y-5">
  <h1 class="text-2xl font-bold">{$t('admin.tabs.models')}</h1>

  {#if loading}
    <div class="space-y-4">
      {#each [1, 2, 3] as _}
        <div class="card p-6 space-y-3 animate-pulse">
          <div class="h-5 w-40 bg-slate-800/50 rounded"></div>
          <div class="h-32 bg-slate-800/30 rounded"></div>
        </div>
      {/each}
    </div>
  {:else if allModels.length === 0}
    <div class="card p-8 text-center space-y-2">
      <p class="opacity-40">{$t('admin.noModelsAvailable')}</p>
    </div>
  {:else}
    <!-- Model Whitelist -->
    <section class="card p-6 space-y-4">
      <div class="flex items-center justify-between">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.modelWhitelist')}</h2>
        </div>
        <div class="flex items-center gap-2 text-xs">
          <span class="opacity-40">{whitelist.length === 0 ? $t('admin.modelWhitelistHint') : `${whitelist.length} / ${allModels.length}`}</span>
          <button class="opacity-50 hover:opacity-100 transition-colors" onclick={selectAll}>All</button>
          <span class="opacity-30">·</span>
          <button class="opacity-50 hover:opacity-100 transition-colors" onclick={selectNone}>None</button>
        </div>
      </div>
      <p class="text-sm opacity-40">{$t('admin.modelWhitelistDesc')}</p>

      <input
        type="text"
        class="input w-full text-sm"
        placeholder={$t('nav.search') + '...'}
        bind:value={search}
      />

      <div class="max-h-72 overflow-y-auto space-y-0.5">
        {#each filtered as model (model.id)}
          <label class="flex items-center gap-2 text-sm py-1.5 px-2 rounded hover:bg-slate-800/50 cursor-pointer">
            <input
              type="checkbox"
              checked={whitelist.includes(model.id)}
              onchange={() => toggleWhitelist(model.id)}
              class="checkbox"
            />
            <span class="flex-1">{model.name}</span>
            <span class="opacity-30 text-xs shrink-0">{model.id}</span>
          </label>
        {/each}
      </div>

      <button class="btn preset-filled-primary-500" onclick={saveWhitelist} disabled={saving}>
        {saving ? '...' : $t('common.save')}
      </button>
    </section>

    <!-- Model Aliases -->
    <section class="card p-6 space-y-4">
      <div class="flex items-center gap-2">
        <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>
        <h2 class="text-lg font-semibold">{$t('admin.modelAliases')}</h2>
      </div>
      <p class="text-sm opacity-40">{$t('admin.modelAliasesDesc')}</p>

      <div class="space-y-2 max-h-72 overflow-y-auto">
        {#each allModels as model (model.id)}
          <div class="flex items-center gap-2 text-sm">
            <span class="opacity-40 text-xs w-48 shrink-0 truncate">{model.id}</span>
            <input
              type="text"
              class="input flex-1 py-1 text-sm"
              placeholder={model.name}
              value={modelAliases[model.id] ?? ''}
              oninput={(e) => {
                const val = e.currentTarget.value.trim();
                if (val) modelAliases = { ...modelAliases, [model.id]: val };
                else {
                  const { [model.id]: _, ...rest } = modelAliases;
                  modelAliases = rest;
                }
              }}
            />
          </div>
        {/each}
      </div>

      <button class="btn preset-filled-primary-500" onclick={saveAliases} disabled={saving}>
        {saving ? '...' : $t('common.save')}
      </button>
    </section>

    <!-- System Models -->
    <section class="card p-6 space-y-4">
      <div class="flex items-center gap-2">
        <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M12 1v4M12 19v4M4.22 4.22l2.83 2.83M16.95 16.95l2.83 2.83M1 12h4M19 12h4M4.22 19.78l2.83-2.83M16.95 7.05l2.83-2.83"/></svg>
        <h2 class="text-lg font-semibold">{$t('admin.systemModels')}</h2>
      </div>

      <div class="space-y-4">
        <!-- Default model -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium">{$t('admin.defaultModel')}</label>
          <p class="text-xs opacity-40">{$t('admin.defaultModelDesc')}</p>
          <select class="select w-full text-sm" bind:value={defaultModel}>
            <option value="">{$t('admin.defaultModelNone')}</option>
            {#each allModels as m (m.id)}
              <option value={m.id}>{m.name}</option>
            {/each}
          </select>
        </div>

        <!-- Search model -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium">{$t('admin.searchModel')}</label>
          <p class="text-xs opacity-40">{$t('admin.searchModelDesc')}</p>
          <select class="select w-full text-sm" bind:value={searchModel}>
            <option value="">{$t('admin.searchModelNone')}</option>
            {#each allModels as m (m.id)}
              <option value={m.id}>{m.name}</option>
            {/each}
          </select>
        </div>

        <!-- Research model -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium">{$t('admin.researchModel')}</label>
          <p class="text-xs opacity-40">{$t('admin.researchModelDesc')}</p>
          <select class="select w-full text-sm" bind:value={researchModel}>
            <option value="">{$t('admin.researchModelNone')}</option>
            {#each allModels as m (m.id)}
              <option value={m.id}>{m.name}</option>
            {/each}
          </select>
        </div>

        <!-- Title model -->
        <div class="space-y-1.5">
          <label class="text-sm font-medium">{$t('admin.titleModel')}</label>
          <p class="text-xs opacity-40">{$t('admin.titleModelDesc')}</p>
          <select class="select w-full text-sm" bind:value={titleModel}>
            <option value="">{$t('admin.titleModelNone')}</option>
            {#each allModels as m (m.id)}
              <option value={m.id}>{m.name}</option>
            {/each}
          </select>
        </div>
      </div>

      <button class="btn preset-filled-primary-500" onclick={saveSystemModels} disabled={savingSystemModels}>
        {savingSystemModels ? '...' : $t('common.save')}
      </button>
    </section>
  {/if}
</div>
