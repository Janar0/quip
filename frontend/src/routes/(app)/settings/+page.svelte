<script lang="ts">
  import { onMount } from 'svelte';
  import { t, locale } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { getUserSettings, updateUserSettings, fetchMe } from '$lib/api/auth';
  import { currentUser } from '$lib/stores/auth';
  import { selectedModel, setDefaultModel } from '$lib/stores/chat';
  import { getModels } from '$lib/api/admin';
  import { theme, setTheme, type ThemeName } from '$lib/stores/theme';

  let name = $state('');
  let defaultModel = $state('');
  let selectedLocale = $state('en');
  let models = $state<{ id: string; name: string }[]>([]);
  let loading = $state(true);
  let saving = $state(false);

  onMount(async () => {
    const [settings, modelList] = await Promise.all([getUserSettings(), getModels()]);
    name = $currentUser?.name ?? settings.name ?? '';
    defaultModel = settings.default_model || localStorage.getItem('default_model') || '';
    selectedLocale = settings.locale || $locale || 'en';
    models = modelList.map((m) => ({ id: m.id, name: m.name || m.id }));
    loading = false;
  });

  async function handleSave() {
    saving = true;
    const ok = await updateUserSettings({
      name: name.trim(),
      default_model: defaultModel,
      locale: selectedLocale,
    });
    if (ok) {
      // Update local state
      if (defaultModel) {
        setDefaultModel(defaultModel);
      }
      if (selectedLocale) {
        $locale = selectedLocale;
        localStorage.setItem('locale', selectedLocale);
      }
      await fetchMe();
      toast.success($t('toast.settingsSaved'));
    } else {
      toast.error($t('common.error'));
    }
    saving = false;
  }
</script>

<div class="p-8 max-w-lg mx-auto space-y-6">
  <h1 class="text-2xl font-bold">{$t('settings.title')}</h1>

  {#if loading}
    <p class="opacity-50">{$t('common.loading')}</p>
  {:else}
    <div class="space-y-5">
      <!-- Display Name -->
      <label class="label">
        <span class="text-sm font-medium">{$t('settings.displayName')}</span>
        <input type="text" class="input mt-1" bind:value={name} />
      </label>

      <!-- Default Model -->
      <label class="label">
        <span class="text-sm font-medium">{$t('settings.defaultModel')}</span>
        <select class="select mt-1" bind:value={defaultModel}>
          <option value="">—</option>
          {#each models as model (model.id)}
            <option value={model.id}>{model.name}</option>
          {/each}
        </select>
      </label>

      <!-- Theme -->
      <div>
        <span class="text-sm font-medium">{$t('settings.theme') ?? 'Theme'}</span>
        <div class="flex gap-2 mt-2">
          {#each ['dark', 'light', 'gray'] as t}
            <button
              class="btn btn-sm {$theme === t ? 'preset-filled' : 'preset-outlined'}"
              onclick={() => setTheme(t as ThemeName)}
            >{t === 'dark' ? 'Dark' : t === 'light' ? 'Light' : 'Gray'}</button>
          {/each}
        </div>
      </div>

      <!-- Language -->
      <div>
        <span class="text-sm font-medium">{$t('settings.language')}</span>
        <div class="flex gap-2 mt-2">
          <button
            class="btn btn-sm {selectedLocale === 'en' ? 'preset-filled' : 'preset-outlined'}"
            onclick={() => (selectedLocale = 'en')}
          >English</button>
          <button
            class="btn btn-sm {selectedLocale === 'ru' ? 'preset-filled' : 'preset-outlined'}"
            onclick={() => (selectedLocale = 'ru')}
          >Русский</button>
        </div>
      </div>

      <button
        class="btn preset-filled-primary-500 w-full"
        onclick={handleSave}
        disabled={saving}
      >
        {saving ? $t('common.loading') : $t('common.save')}
      </button>
    </div>
  {/if}
</div>
