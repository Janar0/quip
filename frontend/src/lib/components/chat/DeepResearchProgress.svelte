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

<div class="border-l-2 pl-3 mb-3 space-y-1" style="border-color: var(--quip-border-strong)">
  <button
    class="flex items-center gap-2 text-xs w-full text-left cursor-pointer"
    style="color: var(--quip-text-muted)"
    onclick={() => (manualToggle = manualToggle === null ? !$isStreaming : !manualToggle)}
    onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-dim)' }}
    onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-muted)' }}
  >
    {#if !isDone}
      <span class="spinner-ring flex-shrink-0" style="width: 12px; height: 12px; border-width: 1.5px"></span>
    {:else}
      <svg class="w-3 h-3 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
    {/if}

    <span>
      {#if isSynthesizing || isDone}
        {$t('chat.deepResearch')}
      {:else}
        {$t('chat.deepResearch')} — {current.detail || current.phase}
      {/if}
    </span>

    <svg
      class="w-3 h-3 ml-1 flex-shrink-0 opacity-40"
      viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"
      style="transition: transform var(--quip-d-2) var(--quip-ease-out); transform: rotate({expanded ? 180 : 0}deg)"
    >
      <path d="M19 9l-7 7-7-7" />
    </svg>
  </button>

  {#if showTimeline}
    <div class="space-y-0.5">
      {#each history as step, i}
        {@const isActive = i === history.length - 1 && $isStreaming && step.phase !== 'synthesizing'}

        {#if step.phase === 'decomposing'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if isActive}
              <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
            {:else}
              <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
            {/if}
            <span class="opacity-50">{$t('research.decomposing')}</span>
          </div>

        {:else if step.phase === 'searching'}
          {#if step.sub_queries?.length}
            {#each step.sub_queries as query}
              <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
                {#if isActive}
                  <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
                {:else}
                  <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
                {/if}
                <span class="opacity-50 truncate">{query}</span>
              </div>
            {/each}
          {:else}
            <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
              <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
              <span class="opacity-50">{$t('research.searching')}...</span>
            </div>
          {/if}

        {:else if step.phase === 'search_complete'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
            <span class="opacity-40">{$t('research.sourcesFound', { values: { count: step.sources_found ?? 0 } })}</span>
          </div>

        {:else if step.phase === 'reading'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if isActive}
              <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
            {:else}
              <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
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
            <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
            <span class="opacity-40">{$t('research.pagesRead', { values: { count: step.urls_read ?? 0 } })}</span>
          </div>

        {:else if step.phase === 'synthesizing'}
          <div class="flex items-center gap-1.5 text-[11px]" style="color: var(--quip-text-muted)">
            {#if $isStreaming}
              <span class="spinner-ring flex-shrink-0" style="width: 9px; height: 9px; border-width: 1.5px"></span>
            {:else}
              <svg class="w-2.5 h-2.5 flex-shrink-0 opacity-50" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
            {/if}
            <span class="opacity-50">{$t('research.synthesizing')}</span>
          </div>
        {/if}
      {/each}
    </div>
  {/if}
</div>
