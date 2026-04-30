<script lang="ts">
  import { subAgents } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';
  import SubAgentCard from './SubAgentCard.svelte';

  let { onClose }: { onClose?: () => void } = $props();

  let entries = $derived(Object.values($subAgents));
  let hasAgents = $derived(entries.length > 0);
  let runningCount = $derived(entries.filter((a) => a.status === 'running').length);
</script>

<div class="flex flex-col h-full">
  <!-- Header -->
  <div class="flex items-center justify-between px-4 py-3 border-b" style="border-color: var(--quip-glass-border)">
    <div class="flex items-center gap-2">
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color: #a78bfa">
        <circle cx="12" cy="12" r="10"/>
        <path d="M12 6v6l4 2"/>
      </svg>
      <span class="text-sm font-semibold" style="color: var(--quip-text)">{$t('research.subAgents')}</span>
      {#if runningCount > 0}
        <span class="text-[10px] px-1.5 py-0.5 rounded-full" style="background: #f59e0b15; color: #f59e0b">{$t('research.subAgentRunningCount', { values: { count: runningCount } })}</span>
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
      <p class="text-xs text-center py-8 opacity-30" style="color: var(--quip-text-muted)">{$t('research.subAgentsWaiting')}</p>
    {/if}
  </div>
</div>
