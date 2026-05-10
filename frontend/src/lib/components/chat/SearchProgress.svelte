<script lang="ts">
  import { t } from 'svelte-i18n';
  import { fly, fade } from 'svelte/transition';
  import { D2, easeOut } from '$lib/motion';
  import type { ToolExecution } from '$lib/stores/sandbox';

  let { executions }: { executions: ToolExecution[] } = $props();

  let expanded = $state(true);
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

<div class="border-l-2 pl-3 mb-3 space-y-1" style="border-color: var(--quip-border-strong)">
  <button
    class="flex items-center gap-2 text-xs w-full text-left cursor-pointer"
    style="color: var(--quip-text-muted)"
    onclick={() => (expanded = !expanded)}
    onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-dim)' }}
    onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-muted)' }}
  >
    {#if !allDone}
      <span class="spinner-ring flex-shrink-0" style="width: 12px; height: 12px; border-width: 1.5px"></span>
    {:else if hasError}
      <svg class="w-3 h-3 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
    {:else}
      <svg class="w-3 h-3 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
    {/if}

    <span>
      {#if !allDone}
        {$t('search.searching')}
      {:else}
        {$t('search.searched')}{totalResults ? ` — ${totalResults} ${$t('search.results')}` : ''}
      {/if}
    </span>

    {#if allDone}
      <svg
        class="w-3 h-3 ml-1 flex-shrink-0 opacity-40"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
        style="transition: transform var(--quip-d-2) var(--quip-ease-out); transform: rotate({expanded ? 180 : 0}deg)"
      >
        <path d="M19 9l-7 7-7-7" />
      </svg>
    {/if}
  </button>

  <!-- Step lines -->
  {#if !allDone || expanded}
    <div class="space-y-0.5">
      {#each executions as exec (exec.id)}
        <div
          class="flex items-center gap-1.5 text-[11px]"
          in:fly={{ y: 6, duration: D2, easing: easeOut }}
          style="color: var(--quip-text-muted)"
        >
          {#if exec.status === 'running'}
            <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
          {:else if exec.status === 'error'}
            <svg class="w-2.5 h-2.5 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6L6 18M6 6l12 12"/></svg>
          {:else}
            <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
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
          <div class="space-y-1.5">
            {#each getResults(exec) as r}
              <div class="text-[11px] flex items-start gap-1.5">
                {#if r.url}
                  <img
                    src={`https://www.google.com/s2/favicons?domain=${new URL(r.url).hostname}&sz=16`}
                    alt=""
                    class="w-3.5 h-3.5 mt-0.5 rounded-sm flex-shrink-0 opacity-60"
                    loading="lazy"
                    onerror={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none'; }}
                  />
                {/if}
                <div class="min-w-0 flex-1">
                  <a href={r.url} target="_blank" rel="noopener" class="hover:underline font-medium block truncate" style="color: var(--quip-link)">{r.title}</a>
                  {#if r.snippet}
                    <p class="opacity-40 mt-0.5 line-clamp-2">{r.snippet}</p>
                  {/if}
                </div>
              </div>
            {/each}
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>
