<script lang="ts">
  import type { ResearchRunStatus, ResearchStatusInfo } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';

  let {
    history,
    current,
    status = 'running',
    errors = [],
    truncated = false,
    onStop,
  }: {
    history: ResearchStatusInfo[];
    current: ResearchStatusInfo;
    status?: ResearchRunStatus;
    errors?: { message: string }[];
    truncated?: boolean;
    onStop?: () => void;
  } = $props();

  let manualToggle = $state<boolean | null>(null);
  let isRunning = $derived(status === 'queued' || status === 'running' || status === 'cancelling');
  let isDone = $derived(!isRunning);
  let isSynthesizing = $derived(current.phase === 'synthesizing');
  let expanded = $derived(manualToggle !== null ? manualToggle : isRunning);
  let showTimeline = $derived(expanded || isRunning);
  const statusLabels: Record<ResearchRunStatus, string> = {
    queued: 'research.status.queued',
    running: 'research.status.running',
    cancelling: 'research.status.cancelling',
    completed: 'research.status.completed',
    partial: 'research.status.partial',
    failed: 'research.status.failed',
    cancelled: 'research.status.cancelled',
    interrupted: 'research.status.interrupted',
  };

  function domainFromUrl(url: string): string {
    try {
      return new URL(url).hostname.replace(/^www\./, '');
    } catch {
      return url.slice(0, 40);
    }
  }
</script>

<div class="pl-3 mb-3 space-y-1" style="border-left: 2px solid var(--quip-glass-border-strong)">
  <button
    class="flex items-center gap-2 text-xs w-full text-left cursor-pointer"
    style="color: var(--quip-text-muted)"
    onclick={() => (manualToggle = manualToggle === null ? isRunning : !manualToggle)}
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
        {$t(statusLabels[status])}
      {:else}
        {$t(statusLabels[status])}{#if current.detail} — {current.detail}{/if}
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

  {#if isRunning && onStop}
    <button type="button" class="ml-5 text-[11px] underline underline-offset-2 opacity-70 hover:opacity-100" onclick={onStop}>
      {$t(status === 'cancelling' ? 'research.stopRequested' : 'chat.stopGeneration')}
    </button>
  {/if}

  {#if showTimeline}
    <div class="space-y-0.5">
      {#each history as step, i}
        {@const isActive = i === history.length - 1 && isRunning && step.phase !== 'synthesizing'}

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
            {#if isRunning}
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

  {#if errors.length > 0}
    <ul class="mt-1 pl-4 list-disc text-[11px] space-y-0.5" style="color: #f59e0b">
      {#each errors as item, i}<li>{item.message}</li>{/each}
    </ul>
  {/if}
  {#if truncated}
    <p class="mt-1 text-[11px] opacity-50" style="color: var(--quip-text-muted)">{$t('research.snapshotTruncated')}</p>
  {/if}
</div>
