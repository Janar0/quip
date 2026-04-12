<script lang="ts">
  import type { ResearchStatusInfo } from '$lib/stores/chat';
  import { isStreaming } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';

  let {
    history,
    current,
  }: {
    history: ResearchStatusInfo[];
    current: ResearchStatusInfo;
  } = $props();

  let manualToggle = $state<boolean | null>(null);
  let isDone = $derived(current.phase === 'synthesizing' || !$isStreaming);
  let isSynthesizing = $derived(current.phase === 'synthesizing');
  let expanded = $derived(manualToggle !== null ? manualToggle : $isStreaming);
  let showTimeline = $derived(expanded || $isStreaming);

  function domainFromUrl(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url.slice(0, 40);
    }
  }
</script>

<!-- Deep research progress — left-border accent style -->
<div class="border-l-2 pl-3 mb-3 space-y-1" style="border-color: var(--quip-border-strong)">
  <!-- Summary line -->
  <button
    class="flex items-center gap-2 text-xs w-full text-left"
    onclick={() => (manualToggle = manualToggle === null ? !$isStreaming : !manualToggle)}
  >
    {#if !isDone}
      <span class="flex-shrink-0 w-3 h-3 flex items-center justify-center">
        <span class="block w-2.5 h-2.5 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
      </span>
    {:else}
      <svg class="w-3 h-3 text-success-400/60 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
    {/if}

    <span style="color: var(--quip-text-muted)">
      {#if isSynthesizing || isDone}
        {$t('chat.deepResearch')}
      {:else}
        {$t('chat.deepResearch')} — {current.detail || current.phase}
      {/if}
    </span>

    <svg
      class="w-3 h-3 ml-1 transition-transform {expanded ? 'rotate-180' : ''}"
      style="color: var(--quip-text-muted)"
      fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"
    >
      <path d="M19 9l-7 7-7-7" stroke-linecap="round" stroke-linejoin="round"/>
    </svg>
  </button>

  <!-- Steps timeline -->
  {#if showTimeline}
    <div class="space-y-0.5">
      {#each history as step, i}
        {@const isActive = i === history.length - 1 && $isStreaming && step.phase !== 'synthesizing'}

        {#if step.phase === 'decomposing'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if isActive}
              <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
                <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
              </span>
            {:else}
              <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {/if}
            <span class="opacity-50">{$t('research.decomposing')}</span>
          </div>

        {:else if step.phase === 'searching'}
          {#if step.sub_queries?.length}
            {#each step.sub_queries as query}
              <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
                {#if isActive}
                  <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
                    <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
                  </span>
                {:else}
                  <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
                {/if}
                <span class="opacity-50 truncate">{query}</span>
              </div>
            {/each}
          {:else}
            <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
              <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
                <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
              </span>
              <span class="opacity-50">{$t('research.searching')}...</span>
            </div>
          {/if}

        {:else if step.phase === 'search_complete'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span class="opacity-40">{$t('research.sourcesFound', { values: { count: step.sources_found ?? 0 } })}</span>
          </div>

        {:else if step.phase === 'reading'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if isActive}
              <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
                <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
              </span>
            {:else}
              <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {/if}
            <span class="opacity-50">
              {$t('research.reading')}{step.urls_reading?.length ? ` (${step.urls_reading.length})` : ''}
            </span>
          </div>
          {#if step.urls_reading?.length}
            <div class="ml-4 space-y-0.5">
              {#each step.urls_reading as url}
                <div class="text-[10px] opacity-30 truncate">{domainFromUrl(url)}</div>
              {/each}
            </div>
          {/if}

        {:else if step.phase === 'read_complete'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span class="opacity-40">{$t('research.pagesRead', { values: { count: step.urls_read ?? 0 } })}</span>
          </div>

        {:else if step.phase === 'synthesizing'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if $isStreaming}
              <span class="flex-shrink-0 w-2.5 h-2.5 flex items-center justify-center">
                <span class="block w-2 h-2 rounded-full border border-slate-500 border-t-transparent animate-spin"></span>
              </span>
            {:else}
              <svg class="w-2.5 h-2.5 text-success-400/50 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" stroke-width="2"><path d="M5 13l4 4L19 7" stroke-linecap="round" stroke-linejoin="round"/></svg>
            {/if}
            <span class="opacity-50">{$t('research.synthesizing')}</span>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>
