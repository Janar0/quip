<script lang="ts">
import { onDestroy, onMount } from 'svelte';
  import { t, locale } from 'svelte-i18n';
  import { toast } from 'svelte-sonner';
  import { fade } from 'svelte/transition';
  import { D2 } from '$lib/motion';
import { createTelegramLink, getTelegramStatus, getUserSettings, unlinkTelegram, updateUserSettings, fetchMe } from '$lib/api/auth';
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
  let telegramLinked = $state(false);
  let telegramUserId = $state<string | null>(null);
  let telegramLinkUrl = $state('');
  let telegramLinkLoading = $state(false);
  let telegramPoll: ReturnType<typeof setInterval> | undefined;

  onMount(async () => {
    const [settings, modelList] = await Promise.all([getUserSettings(), getModels()]);
    name = $currentUser?.name ?? settings.name ?? '';
    defaultModel = settings.default_model || localStorage.getItem('default_model') || '';
    selectedLocale = settings.locale || $locale || 'en';
    models = modelList.map((m) => ({ id: m.id, name: m.name || m.id }));
    const telegram = await getTelegramStatus();
    telegramLinked = telegram.linked;
    telegramUserId = telegram.telegram_user_id;
    loading = false;
  });

  onDestroy(() => {
    if (telegramPoll) clearInterval(telegramPoll);
  });

  async function refreshTelegramStatus() {
    const wasLinked = telegramLinked;
    const telegram = await getTelegramStatus();
    telegramLinked = telegram.linked;
    telegramUserId = telegram.telegram_user_id;
    if (!wasLinked && telegram.linked) {
      toast.success($t('settings.telegramConnected'));
    }
    if (telegram.linked && telegramPoll) {
      clearInterval(telegramPoll);
      telegramPoll = undefined;
    }
  }

  async function connectTelegram() {
    telegramLinkLoading = true;
    const link = await createTelegramLink();
    telegramLinkLoading = false;
    if (!link) {
      toast.error($t('settings.telegramLinkFailed'));
      return;
    }
    telegramLinkUrl = link.url;
    window.open(link.url, '_blank', 'noopener,noreferrer');
    if (telegramPoll) clearInterval(telegramPoll);
    telegramPoll = setInterval(refreshTelegramStatus, 2500);
  }

  async function disconnectTelegram() {
    if (await unlinkTelegram()) {
      telegramLinked = false;
      telegramUserId = null;
      telegramLinkUrl = '';
      toast.success($t('settings.telegramUnlinked'));
    } else {
      toast.error($t('common.error'));
    }
  }

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

<div class="p-8 max-w-lg mx-auto space-y-6" in:fade={{ duration: D2 }}>
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
          {#each ['dark', 'light'] as t}
            <button
              class="btn btn-sm {$theme === t ? 'preset-filled' : 'preset-outlined'}"
              onclick={() => setTheme(t as ThemeName)}
            >{t === 'dark' ? 'Dark' : 'Light'}</button>
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

      <!-- Telegram account link -->
      <section class="card p-4 space-y-3">
        <div>
          <h2 class="font-semibold">{$t('settings.telegram')}</h2>
          <p class="text-sm opacity-60 mt-1">{$t('settings.telegramDesc')}</p>
        </div>
        {#if telegramLinked}
          <div class="flex items-center justify-between gap-3">
            <span class="text-sm">{$t('settings.telegramConnected')} {telegramUserId ? `(${telegramUserId})` : ''}</span>
            <button class="btn btn-sm preset-outlined" onclick={disconnectTelegram}>{$t('settings.telegramUnlink')}</button>
          </div>
        {:else}
          <button class="btn preset-outlined w-full" onclick={connectTelegram} disabled={telegramLinkLoading}>
            {telegramLinkLoading ? $t('common.loading') : $t('settings.telegramConnect')}
          </button>
          {#if telegramLinkUrl}
            <a class="text-xs break-all underline opacity-70" href={telegramLinkUrl} target="_blank" rel="noreferrer">{telegramLinkUrl}</a>
          {/if}
        {/if}
      </section>

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
