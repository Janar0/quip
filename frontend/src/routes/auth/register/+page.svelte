<script lang="ts">
  import { t } from 'svelte-i18n';
  import { goto } from '$app/navigation';
  import { register } from '$lib/api/auth';

  let email = $state('');
  let username = $state('');
  let name = $state('');
  let password = $state('');
  let error = $state('');
  let loading = $state(false);

  async function handleSubmit(e: Event) {
    e.preventDefault();
    error = '';
    loading = true;
    const result = await register({ email, username, name, password });
    loading = false;

    if (result.ok) {
      goto('/chat');
    } else {
      error = result.error ?? 'Registration failed';
    }
  }
</script>

<div class="flex items-center justify-center min-h-screen p-4">
  <div class="card p-8 w-full max-w-md space-y-6">
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
      <a href="/auth/login" class="anchor">{$t('auth.login')}</a>
    </p>
  </div>
</div>
