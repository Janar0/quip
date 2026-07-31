<script lang="ts">
  import { t } from 'svelte-i18n';
  import { goto } from '$app/navigation';
  import { login } from '$lib/api/auth';
  import { fly } from 'svelte/transition';
  import { D3, easeOut } from '$lib/motion';

  let email = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);

  const authQuery = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : null;
  const telegramError = authQuery?.get('telegram_error');
  const telegramLink = authQuery?.get('telegram_link');

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;
    const result = await login({ email, password });
    loading = false;

    if (result.ok) {
      if (telegramLink) {
        window.location.assign(`/api/auth/telegram/claim?token=${encodeURIComponent(telegramLink)}`);
      } else {
        goto('/chat');
      }
    } else {
      error = result.error ?? 'Login failed';
    }
  }
</script>

<div class="flex items-center justify-center min-h-screen p-4">
  <div class="card p-8 w-full max-w-md space-y-6" in:fly={{ y: 20, duration: D3, easing: easeOut }}>
    <h1 class="text-2xl font-bold text-center">{$t('auth.login')}</h1>

    {#if error}
      <aside class="alert preset-filled-error-500">
        <p>{error}</p>
      </aside>
    {/if}

    <form onsubmit={handleSubmit} class="space-y-4">
      <label class="label">
        <span>{$t('auth.email')}</span>
        <input type="email" class="input" bind:value={email} required />
      </label>

      <label class="label">
        <span>{$t('auth.password')}</span>
        <input type="password" class="input" bind:value={password} required />
      </label>

      <button type="submit" class="btn preset-filled-primary-500 w-full" disabled={loading}>
        {loading ? $t('common.loading') : $t('auth.login')}
      </button>
    </form>

    <div class="relative flex items-center gap-3 text-xs opacity-50">
      <span class="h-px flex-1 bg-current"></span>
      <span>{$t('auth.telegram')}</span>
      <span class="h-px flex-1 bg-current"></span>
    </div>

    {#if telegramError === 'not_linked'}
      <p class="text-xs opacity-70">{$t('auth.telegramNotLinked')}</p>
    {:else if telegramError}
      <p class="text-xs opacity-70">{$t('auth.telegramFailed')}</p>
    {/if}

    <a href="/api/auth/telegram/login" class="btn preset-outlined w-full text-center">{$t('auth.telegramLogin')}</a>

    <p class="text-center text-sm opacity-70">
      {$t('auth.noAccount')}
      <a href={telegramLink ? `/auth/register?telegram_link=${encodeURIComponent(telegramLink)}` : '/auth/register'} class="anchor">{$t('auth.register')}</a>
    </p>
  </div>
</div>
