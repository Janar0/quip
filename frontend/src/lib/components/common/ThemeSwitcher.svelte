<script lang="ts">
  import { theme, setTheme, type ThemeName } from '$lib/stores/theme';

  const themes: { name: ThemeName; icon: string; label: string }[] = [
    { name: 'dark', icon: 'moon', label: 'Dark' },
    { name: 'light', icon: 'sun', label: 'Light' },
    { name: 'gray', icon: 'circle', label: 'Gray' },
  ];
</script>

<div class="flex items-center gap-0.5 p-0.5 rounded-lg" style="background: var(--quip-hover)">
  {#each themes as t}
    <button
      class="p-1.5 rounded-md transition-all {$theme === t.name ? 'shadow-sm' : 'opacity-50 hover:opacity-80'}"
      style={$theme === t.name ? 'background: var(--quip-bg-elevated); color: var(--quip-text)' : 'color: var(--quip-text-dim)'}
      onclick={() => setTheme(t.name)}
      title={t.label}
      aria-label="{t.label} theme"
    >
      {#if t.icon === 'moon'}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>
      {:else if t.icon === 'sun'}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
      {:else}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>
      {/if}
    </button>
  {/each}
</div>
