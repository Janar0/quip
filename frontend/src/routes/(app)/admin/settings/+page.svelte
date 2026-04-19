<script lang="ts">
  import { t } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { toast } from 'svelte-sonner';
  import { goto } from '$app/navigation';
  import { getSettings, updateSettings } from '$lib/api/admin';

  let apiKey = $state('');
  let keyIsSet = $state(false);
  let keyInfo = $state<Record<string, unknown> | null>(null);
  let ollamaUrl = $state('http://localhost:11434');
  let systemPrompt = $state('');
  let searchEnabled = $state(false);
  let researchEnabled = $state(true);
  let ragEnabled = $state(true);
  let embeddingProvider = $state('openrouter');
  let embeddingModel = $state('openai/text-embedding-3-small');
  let ragChunkSize = $state(512);
  let ragChunkOverlap = $state(64);
  let ragTopK = $state(5);
  let saving = $state(false);
  let loading = $state(true);
  let activeTab = $state<'api' | 'system' | 'tools'>('api');

  onMount(async () => {
    const settings = await getSettings();
    keyIsSet = settings.openrouter_api_key_set;
    keyInfo = settings.openrouter_key_info;
    ollamaUrl = settings.ollama_url ?? 'http://localhost:11434';
    systemPrompt = settings.system_prompt ?? '';
    searchEnabled = settings.search_enabled ?? false;
    researchEnabled = settings.research_enabled ?? true;
    ragEnabled = settings.rag_enabled ?? true;
    embeddingProvider = settings.embedding_provider ?? 'openrouter';
    embeddingModel = settings.embedding_model ?? 'openai/text-embedding-3-small';
    ragChunkSize = settings.rag_chunk_size ?? 512;
    ragChunkOverlap = settings.rag_chunk_overlap ?? 64;
    ragTopK = settings.rag_top_k ?? 5;
    loading = false;
  });

  async function saveKey() {
    saving = true;
    const ok = await updateSettings({ openrouter_api_key: apiKey });
    if (ok) {
      toast.success($t('toast.apiKeySaved'));
      keyIsSet = true;
      apiKey = '';
      const settings = await getSettings();
      keyInfo = settings.openrouter_key_info;
    } else {
      toast.error($t('toast.apiKeyFailed'));
    }
    saving = false;
  }

  async function saveOllama() {
    saving = true;
    const ok = await updateSettings({ ollama_url: ollamaUrl });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.ollamaSaved') : $t('admin.failedToSave'));
    saving = false;
  }

  async function savePrompt() {
    saving = true;
    const ok = await updateSettings({ system_prompt: systemPrompt });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.systemPromptSaved') : $t('admin.failedToSave'));
    saving = false;
  }

  async function toggleSearch() {
    searchEnabled = !searchEnabled;
    const ok = await updateSettings({ search_enabled: searchEnabled });
    if (!ok) {
      searchEnabled = !searchEnabled;
      toast.error($t('admin.failedToSave'));
    }
  }

  async function toggleResearch() {
    researchEnabled = !researchEnabled;
    const ok = await updateSettings({ research_enabled: researchEnabled });
    if (!ok) {
      researchEnabled = !researchEnabled;
      toast.error($t('admin.failedToSave'));
    }
  }

  async function toggleRag() {
    ragEnabled = !ragEnabled;
    const ok = await updateSettings({ rag_enabled: ragEnabled });
    if (!ok) {
      ragEnabled = !ragEnabled;
      toast.error($t('admin.failedToSave'));
    }
  }

  async function saveRagSettings() {
    saving = true;
    const ok = await updateSettings({
      embedding_provider: embeddingProvider,
      embedding_model: embeddingModel,
      rag_chunk_size: ragChunkSize,
      rag_chunk_overlap: ragChunkOverlap,
      rag_top_k: ragTopK,
    });
    toast[ok ? 'success' : 'error'](ok ? $t('toast.settingsSaved') : $t('admin.failedToSave'));
    saving = false;
  }
</script>

<div class="p-8 max-w-2xl space-y-5">
  <h1 class="text-2xl font-bold">{$t('admin.tabs.settings')}</h1>

  <!-- Tab bar -->
  <div class="flex gap-1 border-b" style="border-color: var(--quip-border)">
    {#each [
      { id: 'api', label: $t('admin.tabApi') },
      { id: 'system', label: $t('admin.tabSystem') },
      { id: 'tools', label: $t('admin.tabTools') },
    ] as tab}
      <button
        class="px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors {activeTab === tab.id
          ? 'border-slate-400 text-slate-200'
          : 'border-transparent text-slate-500 hover:text-slate-300'}"
        onclick={() => (activeTab = tab.id as typeof activeTab)}
      >{tab.label}</button>
    {/each}
  </div>

  {#if loading}
    <div class="space-y-4">
      {#each [1,2,3] as _}
        <div class="card p-6 space-y-3 animate-pulse">
          <div class="h-5 w-40 bg-slate-800/50 rounded"></div>
          <div class="h-3 w-64 bg-slate-800/30 rounded"></div>
          <div class="h-10 bg-slate-800/30 rounded"></div>
        </div>
      {/each}
    </div>

  {:else if activeTab === 'api'}
    <!-- ══ TAB: API & Models ══ -->
    <div class="space-y-5">
      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.openrouterKey')}</h2>
        </div>

        {#if keyIsSet}
          <div class="flex items-center gap-3">
            <span class="inline-flex items-center gap-1.5 text-xs font-medium px-2.5 py-1 rounded-full bg-success-500/15 text-success-400">
              <span class="relative flex size-1.5"><span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-success-400 opacity-75"></span><span class="relative inline-flex size-1.5 rounded-full bg-success-500"></span></span>
              {$t('admin.connected')}
            </span>
            {#if keyInfo}
              <span class="text-sm opacity-50">${keyInfo.limit_remaining ?? '?'} remaining</span>
            {/if}
          </div>
        {:else}
          <p class="text-sm opacity-50">{$t('admin.noApiKey')} <a href="https://openrouter.ai/keys" target="_blank" class="text-slate-400 underline">openrouter.ai/keys</a></p>
        {/if}

        <div class="flex gap-2">
          <input type="password" class="input flex-1" placeholder={keyIsSet ? $t('admin.enterNewKey') : 'sk-or-...'} bind:value={apiKey} />
          <button class="btn preset-filled-primary-500" onclick={saveKey} disabled={saving || !apiKey.trim()}>
            {saving ? '...' : $t('common.save')}
          </button>
        </div>
      </section>

      {#if keyInfo}
        <section class="card p-6 space-y-3">
          <h2 class="text-sm font-semibold opacity-60 uppercase tracking-wide">{$t('admin.keyDetails')}</h2>
          <div class="grid grid-cols-2 gap-x-4 gap-y-2 text-sm">
            <span class="opacity-40">{$t('admin.keyLabel')}</span><span>{keyInfo.label ?? 'N/A'}</span>
            <span class="opacity-40">{$t('admin.keyLimit')}</span><span>${keyInfo.limit ?? 'Unlimited'}</span>
            <span class="opacity-40">{$t('admin.keyUsage')}</span><span>${keyInfo.usage ?? 0}</span>
            <span class="opacity-40">{$t('admin.freeTier')}</span>
            <span class="inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full {keyInfo.is_free_tier ? 'bg-warning-500/15 text-warning-400' : 'bg-slate-800/40 text-surface-300'}">
              {keyInfo.is_free_tier ? $t('common.yes') : $t('common.no')}
            </span>
          </div>
        </section>
      {/if}

      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><circle cx="6" cy="6" r="1"/><circle cx="6" cy="18" r="1"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.ollama')}</h2>
        </div>
        <p class="text-sm opacity-40">{$t('admin.ollamaDesc')}</p>
        <div class="flex gap-2">
          <input type="text" class="input flex-1" placeholder="http://localhost:11434" bind:value={ollamaUrl} />
          <button class="btn preset-filled-primary-500" onclick={saveOllama} disabled={saving}>{$t('common.save')}</button>
        </div>
      </section>
    </div>

  {:else if activeTab === 'system'}
    <!-- ══ TAB: System ══ -->
    <div class="space-y-5">
      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.systemPrompt')}</h2>
        </div>
        <p class="text-sm opacity-40">{$t('admin.systemPromptDesc')}</p>
        <textarea class="textarea w-full" rows="8" placeholder={$t('admin.systemPromptPlaceholder')} bind:value={systemPrompt}></textarea>
        <button class="btn preset-filled-primary-500" onclick={savePrompt} disabled={saving}>
          {saving ? '...' : $t('common.save')}
        </button>
      </section>
    </div>

  {:else}
    <!-- ══ TAB: Tools — only high-level toggles; per-skill config lives in /admin/skills ══ -->
    <div class="space-y-5">
      <section class="card p-6 space-y-3">
        <h2 class="text-lg font-semibold">{$t('admin.tabs.skills')}</h2>
        <p class="text-sm opacity-60">
          Каждый инструмент / виджет / артефакт теперь настраивается на своей карточке в разделе
          <button class="underline text-slate-300" onclick={() => goto('/admin/skills')}>Skills</button>:
          API-ключи, модели, лимиты, шаблоны. Включение/выключение — тумблером на карточке.
        </p>
      </section>

      <!-- Web Search master toggle -->
      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.searchEnabled')}</h2>
        </div>
        <p class="text-sm opacity-40">{$t('admin.searchEnabledDesc')}</p>
        <label class="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" class="checkbox" checked={searchEnabled} onchange={toggleSearch} />
          <span class="text-sm">{searchEnabled ? $t('common.enabled') : $t('common.disabled')}</span>
        </label>
      </section>

      <!-- Deep Research -->
      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 3H5a2 2 0 00-2 2v4m6-6h10a2 2 0 012 2v4M9 3v18m0 0h10a2 2 0 002-2v-4M9 21H5a2 2 0 01-2-2v-4m0 0h18"/></svg>
          <h2 class="text-lg font-semibold">Deep Research</h2>
        </div>
        <p class="text-sm opacity-40">Multi-agent deep research mode. Requires Web Search to be enabled.</p>
        <label class="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" class="checkbox" checked={researchEnabled} onchange={toggleResearch} />
          <span class="text-sm">{researchEnabled ? $t('common.enabled') : $t('common.disabled')}</span>
        </label>
      </section>

      <!-- RAG & Documents -->
      <section class="card p-6 space-y-4">
        <div class="flex items-center gap-2">
          <svg class="w-5 h-5 opacity-50" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
          <h2 class="text-lg font-semibold">{$t('admin.ragEnabled')}</h2>
        </div>
        <p class="text-sm opacity-40">{$t('admin.ragEnabledDesc')}</p>
        <label class="flex items-center gap-3 cursor-pointer">
          <input type="checkbox" class="checkbox" checked={ragEnabled} onchange={toggleRag} />
          <span class="text-sm">{ragEnabled ? $t('common.enabled') : $t('common.disabled')}</span>
        </label>

        {#if ragEnabled}
          <div class="grid grid-cols-2 gap-4 pt-2">
            <label class="space-y-1">
              <span class="text-xs opacity-50">{$t('admin.embeddingProvider')}</span>
              <select class="select w-full" bind:value={embeddingProvider}>
                <option value="openrouter">OpenRouter</option>
                <option value="ollama">Ollama</option>
              </select>
            </label>
            <label class="space-y-1">
              <span class="text-xs opacity-50">{$t('admin.embeddingModel')}</span>
              <input type="text" class="input w-full" bind:value={embeddingModel} placeholder="openai/text-embedding-3-small" />
            </label>
            <label class="space-y-1">
              <span class="text-xs opacity-50">{$t('admin.ragChunkSize')}</span>
              <input type="number" class="input w-full" min="64" max="4096" bind:value={ragChunkSize} />
            </label>
            <label class="space-y-1">
              <span class="text-xs opacity-50">{$t('admin.ragChunkOverlap')}</span>
              <input type="number" class="input w-full" min="0" max="512" bind:value={ragChunkOverlap} />
            </label>
            <label class="space-y-1 col-span-2">
              <span class="text-xs opacity-50">{$t('admin.ragTopK')}</span>
              <input type="number" class="input w-full" min="1" max="20" bind:value={ragTopK} />
            </label>
          </div>
          <button class="btn preset-filled-primary-500" onclick={saveRagSettings} disabled={saving}>
            {saving ? '...' : $t('common.save')}
          </button>
        {/if}
      </section>
    </div>
  {/if}
</div>
