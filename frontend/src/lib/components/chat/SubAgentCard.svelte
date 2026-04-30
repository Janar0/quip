<script lang="ts">
  import type { SubAgentHandle } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';

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
</script>

<div class="rounded-xl p-3 transition-colors" style="background: var(--quip-input-bg); border: 1px solid var(--quip-border)">
  <div class="flex items-start gap-2.5">
    <!-- Type icon -->
    <div class="w-7 h-7 rounded-lg flex items-center justify-center flex-shrink-0" style="background: {statusColor}15">
      {#if agent.type === 'search'}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke={statusColor} stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
      {:else if agent.type === 'sandbox'}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke={statusColor} stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
      {:else}
        <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke={statusColor} stroke-width="2"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
      {/if}
    </div>

    <div class="min-w-0 flex-1">
      <div class="flex items-center gap-2">
        <span class="text-[11px] font-semibold" style="color: var(--quip-text)">{typeLabel}</span>
        <span class="text-[10px] px-1.5 py-0.5 rounded-full" style="background: {statusColor}15; color: {statusColor}">{statusLabel}</span>
      </div>

      {#if agent.goal}
        <p class="text-[12px] mt-0.5 truncate" style="color: var(--quip-text-dim)">{agent.goal}</p>
      {/if}

      {#if agent.status === 'running' && agent.detail}
        <p class="text-[11px] mt-0.5 truncate opacity-50" style="color: var(--quip-text-muted)">{agent.detail}</p>
      {/if}

      {#if agent.status === 'done' && agent.result}
        <details class="mt-1.5">
          <summary class="text-[10px] cursor-pointer opacity-40 hover:opacity-70" style="color: var(--quip-text-muted)">{$t('research.subAgentShowResult')}</summary>
          <pre class="mt-1 text-[11px] p-2 rounded-lg overflow-x-auto max-h-40" style="background: var(--quip-bg); color: var(--quip-text-dim); white-space: pre-wrap;">{agent.result}</pre>
        </details>
      {/if}

      {#if agent.status === 'error' && agent.error}
        <p class="text-[11px] mt-0.5" style="color: #ef4444">{agent.error}</p>
      {/if}
    </div>

    {#if agent.status === 'running'}
      <span class="spinner-ring flex-shrink-0" style="width: 14px; height: 14px; border-width: 1.5px"></span>
    {:else if agent.status === 'done'}
      <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>
    {:else}
      <svg class="w-4 h-4 flex-shrink-0" viewBox="0 0 24 24" fill="none" stroke="#ef4444" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
    {/if}
  </div>
</div>
