<script lang="ts">
  import { t } from 'svelte-i18n';
  import { goto } from '$app/navigation';
  import { register } from '$lib/api/auth';
  import { getSetupStatus } from '$lib/api/auth';
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { D3, easeOut } from '$lib/motion';

  let email = $state('');
  let username = $state('');
  let name = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);
  let setupRequired = $state(false);
  let adminEmailConfigured = $state(false);
  let bootstrapToken = $state('');
  const telegramLink = typeof window !== 'undefined'
    ? new URLSearchParams(window.location.search).get('telegram_link')
    : null;

  onMount(() => {
    getSetupStatus().then((setup) => {
      setupRequired = setup.required;
      adminEmailConfigured = setup.admin_email_configured;
    });
  });

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;
    const result = await register({
      email,
      username,
      name,
      password,
      ...(setupRequired && bootstrapToken ? { bootstrap_token: bootstrapToken } : {}),
    });
    loading = false;

    if (result.ok) {
      if (telegramLink) {
        window.location.assign(`/api/auth/telegram/claim?token=${encodeURIComponent(telegramLink)}`);
      } else {
        goto('/chat');
      }
    } else {
      error = result.error ?? 'Registration failed';
    }
  }
</script>

<div class="flex items-center justify-center min-h-screen p-4">
  <div class="card p-8 w-full max-w-md space-y-6" in:fly={{ y: 20, duration: D3, easing: easeOut }}>
    <h1 class="text-2xl font-bold text-center">{$t('auth.register')}</h1>

    {#if error}
      <aside class="alert preset-filled-error-500">
        <p>{error}</p>
      </aside>
    {/if}

    <form onsubmit={handleSubmit} class="space-y-4">
      <label class="label">
        <span>{$t('auth.name')}</span>
        <input type="text" class="input" bind:value={name} required />
      </label>

      {#if setupRequired}
        <label class="label">
          <span>{$t('auth.bootstrapToken')}</span>
          <input
            type="password"
            class="input font-mono"
            bind:value={bootstrapToken}
            required={!adminEmailConfigured}
            autocomplete="one-time-code"
          />
          <span class="text-xs opacity-50">{adminEmailConfigured ? $t('auth.bootstrapTokenOptional') : $t('auth.bootstrapTokenHint')}</span>
        </label>
      {/if}

      <label class="label">
        <span>{$t('auth.username')}</span>
        <input type="text" class="input" bind:value={username} required />
      </label>

      <label class="label">
        <span>{$t('auth.email')}</span>
        <input type="email" class="input" bind:value={email} required />
      </label>

      <label class="label">
        <span>{$t('auth.password')}</span>
        <input type="password" class="input" bind:value={password} required minlength="8" />
      </label>

      <button type="submit" class="btn preset-filled-primary-500 w-full" disabled={loading}>
        {loading ? $t('common.loading') : $t('auth.register')}
      </button>
    </form>

    <p class="text-center text-sm opacity-70">
      {$t('auth.hasAccount')}
      <a href={telegramLink ? `/auth/login?telegram_link=${encodeURIComponent(telegramLink)}` : '/auth/login'} class="anchor">{$t('auth.login')}</a>
    </p>
  </div>
</div>
