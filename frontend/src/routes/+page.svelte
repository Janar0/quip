<script lang="ts">
  import { t, locale } from 'svelte-i18n';
  import { getRandomBackronym, getAppName } from '$lib/quip/backronyms';

  let backronym = $state('');
  let appName = $state('Q.U.I.P.');

  function refresh() {
    const lang = $locale ?? 'en';
    backronym = getRandomBackronym(lang);
    appName = getAppName(lang);
  }

  $effect(() => {
    if ($locale) refresh();
  });
</script>

<div class="flex flex-col items-center justify-center min-h-screen gap-6 p-8 ambient-glow">
  <div class="text-center">
    <h1 class="text-6xl font-black tracking-widest">{appName}</h1>
    <p class="mt-3 text-xl opacity-60 italic">{backronym}</p>
  </div>

  <p class="text-lg opacity-70">{$t('home.subtitle')}</p>

  <div class="flex gap-3 mt-4">
    <a href="/auth/login" class="btn preset-filled-primary-500 px-8">{$t('auth.login')}</a>
    <a href="/auth/register" class="btn preset-filled px-8">{$t('auth.register')}</a>
  </div>

  <div class="flex gap-2 mt-8 opacity-50">
    <button class="btn btn-sm preset-outlined" onclick={() => { $locale = 'en'; localStorage.setItem('locale', 'en'); }}>EN</button>
    <button class="btn btn-sm preset-outlined" onclick={() => { $locale = 'ru'; localStorage.setItem('locale', 'ru'); }}>RU</button>
  </div>

  <button class="text-xs opacity-30 hover:opacity-60 transition-opacity" onclick={refresh}>
    ↻
  </button>
</div>
