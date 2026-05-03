<script lang="ts">
  import type { SubAgentHandle } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';
  import { tick } from 'svelte';

  let { agent }: { agent: SubAgentHandle } = $props();

  let typeLabel = $derived(
    agent.type === 'search' ? $t('research.subAgentSearch')
    : agent.type === 'sandbox' ? $t('research.subAgentSandbox')
    : $t('research.subAgentArtifact')
  );

  let statusLabel = $derived(
    agent.status === 'running' ? $t('research.subAgentRunning')
    : agent.status === 'done' ? $t('research.subAgentDone')
    : $t('research.subAgentError')
  );

  let statusColor = $derived(
    agent.status === 'running' ? '#f59e0b'
    : agent.status === 'done' ? '#34d399'
    : '#ef4444'
  );

  let expanded = $state(false);
  let detailEl = $state<HTMLPreElement | undefined>(undefined);

  // Auto-scroll detail area as new content streams in
  $effect(() => {
    if (expanded && detailEl && agent.detail) {
      tick().then(() => {
        if (detailEl) detailEl.scrollTop = detailEl.scrollHeight;
      });
    }
  });
</script>

<button
  class="rounded-xl p-3 transition-colors text-left w-full"
  style="background: var(--quip-glass-bg); border: 1px solid var(--quip-glass-border)"
  onclick={() => (expanded = !expanded)}
>
  <div class="flex items-start gap-2.5">
    <!-- Status indicator -->
    <div class="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0 mt-0.5" style="background: {statusColor}15">
      {#if agent.status === 'running'}
        <span class="spinner-ring" style="width: 10px; height: 10px; border-width: 1.5px"></span>
      {:else if agent.status === 'done'}
        <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke={statusColor} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
      {:else}
        <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke={statusColor} stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
      {/if}
    </div>

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <span class="text-[11px] font-semibold" style="color: var(--quip-text)">{typeLabel}</span>
        <span class="text-[9px] px-1.5 py-0.5 rounded-full font-medium" style="background: {statusColor}12; color: {statusColor}">{statusLabel}</span>
      </div>

      {#if agent.goal}
        <p class="text-[12px] mt-0.5" class:truncate={!expanded} class:break-words={expanded} style="color: var(--quip-text-dim)">{agent.goal}</p>
      {/if}

      {#if !expanded && agent.status === 'running' && agent.detail}
        <p class="text-[10px] mt-1 leading-relaxed opacity-50 line-clamp-2" style="color: var(--quip-text-muted)">
          {agent.detail.slice(-120)}
        </p>
      {/if}

      {#if !expanded && agent.status === 'done' && agent.result}
        <p class="text-[10px] mt-1 leading-relaxed opacity-50 line-clamp-1" style="color: var(--quip-text-muted)">
          {agent.result.slice(0, 120)}
        </p>
      {:else if !expanded && agent.status === 'error' && agent.error}
        <p class="text-[11px] mt-0.5" style="color: #ef4444">{agent.error}</p>
      {/if}
    </div>

    <!-- Chevron / spinner -->
    {#if agent.status === 'running'}
      <span class="spinner-ring flex-shrink-0 mt-1" style="width: 14px; height: 14px; border-width: 1.5px"></span>
    {:else}
      <svg
        class="w-3.5 h-3.5 flex-shrink-0 mt-1 opacity-30"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"
        style="transition: transform var(--quip-d-2) ease; transform: rotate({expanded ? 180 : 0}deg); color: var(--quip-text-muted)"
      >
        <path d="M19 9l-7 7-7-7"/>
      </svg>
    {/if}
  </div>

  <!-- Expanded detail area -->
  {#if expanded}
    <div class="mt-3 pl-8">
      {#if agent.status === 'running' && agent.detail}
        <pre
          bind:this={detailEl}
          class="text-[10px] p-2.5 rounded-lg overflow-y-auto max-h-48 leading-relaxed"
          style="background: var(--quip-bg); color: var(--quip-text-dim); white-space: pre-wrap; word-break: break-word; border: 1px solid var(--quip-border)"
        >{agent.detail}</pre>
      {/if}

      {#if agent.status === 'done' && agent.result}
        <pre class="text-[10px] p-2.5 rounded-lg overflow-x-auto max-h-48 leading-relaxed" style="background: var(--quip-bg); color: var(--quip-text-dim); white-space: pre-wrap; word-break: break-word; border: 1px solid var(--quip-border)">{agent.result}</pre>
      {/if}
    </div>
  {/if}
</button>
