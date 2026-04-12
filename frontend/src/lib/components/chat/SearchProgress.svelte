<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fly, fade } from 'svelte/transition';
  import { D2, easeOut } from '$lib/motion';
  import type { ToolExecution } from '$lib/stores/sandbox';

  let { executions }: { executions: ToolExecution[] } = $props();

  let expanded = $state(false);
  let allDone = $derived(executions.every((e) => e.status !== 'running'));
  let hasError = $derived(executions.some((e) => e.status === 'error'));

  interface SearchResultItem {
    title: string;
    url: string;
    snippet?: string;
  }

  function parseArgs(exec: ToolExecution): Record<string, string> {
    try {
      return JSON.parse(exec.arguments ?? '{}');
    } catch {
      return {};
    }
  }

  function getResults(exec: ToolExecution): SearchResultItem[] {
    if (exec.name === 'web_search' && exec.result?.results) {
      return exec.result.results as SearchResultItem[];
    }
    return [];
  }

  function stepLabel(exec: ToolExecution): string {
    const args = parseArgs(exec);
    if (exec.name === 'web_search') return args.query ?? 'Searching...';
    if (exec.name === 'read_url') {
      try {
        const url = new URL(args.url ?? '');
        return url.hostname + url.pathname.slice(0, 40);
      } catch {
        return args.url?.slice(0, 50) ?? 'Reading page...';
      }
    }
    return exec.name;
  }

  let totalResults = $derived(
    executions.reduce((sum, e) => sum + getResults(e).length, 0),
  );
</script>

<!-- Search progress — left-border accent style -->
<div class="border-l-2 pl-3 mb-3 space-y-1" style="border-color: var(--quip-border-strong)">
  <!-- Summary line -->
  <button
    class="flex items-center gap-2 text-xs w-full text-left"
    onclick={() => (expanded = !expanded)}
  >
    {#if !allDone}
      <span class="flex-shrink-0 w-3 h-3 flex items-center justify-center">
        <span class="block w-2.5 h-2.5 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
      </span>
    {:else if hasError}
      <svg class="w-3 h-3 text-error-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M18 6L6 18M6 6l12 12" stroke-linecap="round"/></svg>
    {:else}
      <svg class="w-3 h-3 text-success-400/60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
    {/if}

    <span style="color: var(--quip-text-muted)">
      {#if !allDone}
        {$t('search.searching')}
      {:else}
        {$t('search.searched')}{totalResults ? ` — ${totalResults} ${$t('search.results')}` : ''}
      {/if}
    </span>

    {#if allDone}
      <svg
        class="w-3 h-3 ml-1 transition-transform {expanded ? 'rotate-180' : ''}"
        style="color: var(--quip-text-muted)"
        fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"
      >
        <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    {/if}
  </button>

  <!-- Step lines (shown while running, hidden when done+collapsed) -->
  {#if !allDone || expanded}
    <div class="space-y-0.5">
      {#each executions as exec (exec.id)}
        <div
          class="flex items-center gap-1.5 text-[11px]"
          style="color: var(--quip-text-muted)"
          in:fly={{ y: 6, duration: D2, easing: easeOut }}
        >
          {#if exec.status === 'running'}
            <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
              <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
            </span>
          {:else if exec.status === 'error'}
            <svg class="w-2.5 h-2.5 text-error-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M18 6L6 18M6 6l12 12" stroke-linecap="round"/></svg>
          {:else}
            <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
          {/if}

          <span class="opacity-50 truncate">{stepLabel(exec)}</span>

          {#if exec.status !== 'running' && getResults(exec).length > 0}
            <span class="opacity-30 flex-shrink-0 ml-1">{getResults(exec).length}</span>
          {/if}
        </div>
      {/each}
    </div>
  {/if}

  <!-- Expanded: search result links -->
  {#if expanded && allDone}
    <div class="space-y-2 pt-1" transition:fade={{ duration: D2 }}>
      {#each executions as exec (exec.id)}
        {#if getResults(exec).length > 0}
          <div class="space-y-1">
            {#each getResults(exec) as r}
              <div class="text-[11px]">
                <a href={r.url} target="_blank" rel="noopener" class="hover:underline font-medium" style="color: var(--quip-link)">{r.title}</a>
                {#if r.snippet}
                  <p class="opacity-40 mt-0.5 line-clamp-1">{r.snippet}</p>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>
