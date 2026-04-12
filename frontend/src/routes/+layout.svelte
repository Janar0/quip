<script lang="ts">
  import '../app.css';
  import '$lib/i18n';
  import { isLoading } from 'svelte-i18n';
  import { onMount } from 'svelte';
  import { authToken } from '$lib/stores/auth';
  import { fetchMe } from '$lib/api/auth';
  import { Toaster } from 'svelte-sonner';
  import { loadWidgetTemplates } from '$lib/stores/widgets';
  import { theme, setTheme } from '$lib/stores/theme';

  let { children } = $props();

  let toasterTheme = $derived($theme === 'light' ? 'light' as const : 'dark' as const);

  onMount(async () => {
    document.getElementById('splash')?.remove();
    // Sync theme store with DOM on mount
    setTheme($theme);
    if ($authToken) {
      await fetchMe();
    }
    await loadWidgetTemplates();
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
