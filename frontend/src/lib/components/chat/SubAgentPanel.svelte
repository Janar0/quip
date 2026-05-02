<script lang="ts">
  import { subAgents } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';
  import { fade } from 'svelte/transition';
  import { D2 } from '$lib/motion';
  import SubAgentCard from './SubAgentCard.svelte';

  let { onClose }: { onClose?: () => void } = $props();

  let entries = $derived(Object.values($subAgents));
  let hasAgents = $derived(entries.length > 0);
  let runningCount = $derived(entries.filter((a) => a.status === 'running').length);
</script>

<div class="flex flex-col h-full" style="background: var(--quip-bg)">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-3 border-b" style="background: var(--quip-glass-bg); border-color: var(--quip-glass-border)">
    <div>
      <div class="flex items-center gap-2">
        <div class="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0" style="background: rgba(167,139,250,0.15)">
          <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <path d="M12 6v6l4 2"/>
          </svg>
        </div>
        <span class="text-sm font-semibold" style="color: var(--quip-text)">{$t('research.subAgents')}</span>
      </div>
      {#if runningCount > 0}
        <div class="flex items-center gap-1 mt-0.5">
          <span class="spinner-ring inline-block" style="width: 10px; height: 10px; border-width: 1.5px"></span>
          <span class="text-[10px]" style="color: #f59e0b">{$t('research.subAgentRunningCount', { values: { count: runningCount } })}</span>
        </div>
      {:else if hasAgents}
        <div class="flex items-center gap-1 mt-0.5">
          <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
          <span class="text-[10px]" style="color: #34d399">{entries.length} {$t('research.subAgents')}</span>
        </div>
      {/if}
    </div>
    {#if onClose}
      <button
        class="p-1.5 rounded-lg hover:bg-slate-800/50 transition-colors"
        onclick={onClose}
        aria-label={$t('common.close')}
      >
        <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--quip-text-muted)"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    {/if}
  </div>

  <!-- Agent list -->
  <div class="flex-1 overflow-y-auto p-3 space-y-2">
    {#if hasAgents}
      {#each entries as agent (agent.task_id)}
        <SubAgentCard {agent} />
      {/each}
    {:else}
      <div class="flex flex-col items-center gap-2 py-8" transition:fade={{ duration: D2 }}>
        <svg class="w-5 h-5 opacity-30" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: var(--quip-text-muted)">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
        <p class="text-xs opacity-30" style="color: var(--quip-text-muted)">{$t('research.subAgentsWaiting')}</p>
      </div>
    {/if}
  </div>
</div>
