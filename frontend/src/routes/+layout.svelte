<script lang="ts">
  import '../app.css';
  import '$lib/i18n';
  import { isLoading } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { authToken } from '$lib/stores/auth';
  import { fetchMe } from '$lib/api/auth';
  import { tryRefresh } from '$lib/api/client';
  import { Toaster } from 'svelte-sonner';
  import { loadWidgetTemplates } from '$lib/stores/widgets';
  import { theme, setTheme } from '$lib/stores/theme';

  let { children } = $props();

  let toasterTheme = $derived($theme === 'light' ? 'light' as const : 'dark' as const);

  const REFRESH_INTERVAL_MS = 50 * 60 * 1000; // 50 min — before 60 min access token expires

  async function silentRefresh() {
    const hasRefreshToken = typeof localStorage !== 'undefined' && !!localStorage.getItem('refresh_token');
    if (hasRefreshToken) await tryRefresh();
  }

  onMount(async () => {
    document.getElementById('splash')?.remove();
    setTheme($theme);
    if ($authToken) {
      await fetchMe();
      await loadWidgetTemplates();
    }

    // Refresh token on tab focus (user returns to tab after being away)
    const onVisibility = () => {
      if (document.visibilityState === 'visible') silentRefresh();
    };
    document.addEventListener('visibilitychange', onVisibility);

    // Periodic refresh while tab is open
    const interval = setInterval(silentRefresh, REFRESH_INTERVAL_MS);

    return () => {
      document.removeEventListener('visibilitychange', onVisibility);
      clearInterval(interval);
    };
  });
</script>

<Toaster richColors position="bottom-right" theme={toasterTheme} />

{#if $isLoading}
  <div class="flex items-center justify-center min-h-screen">
    <p class="opacity-50">Loading...</p>
  </div>
{:else}
  {@render children()}
{/if}
