<script lang="ts">
  import { t } from 'svelte-i18n';
  import { goto } from '$app/navigation';
  import { login } from '$lib/api/auth';

  let email = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;
    const result = await login({ email, password });
    loading = false;

    if (result.ok) {
      goto('/chat');
    } else {
      error = result.error ?? 'Login failed';
    }
  }
</script>

<div class="flex items-center justify-center min-h-screen p-4">
  <div class="card p-8 w-full max-w-md space-y-6">
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

    <p class="text-center text-sm opacity-70">
      {$t('auth.noAccount')}
      <a href="/auth/register" class="anchor">{$t('auth.register')}</a>
    </p>
  </div>
</div>
