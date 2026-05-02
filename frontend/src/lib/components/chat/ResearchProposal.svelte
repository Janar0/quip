<script lang="ts">
  import { t } from 'svelte-i18n';
  import { isStreaming } from '$lib/stores/chat';

  let {
    plan,
    onStart,
    onDecline,
  }: {
    plan: { title: string; questions: string[]; approach?: string };
    onStart: () => void;
    onDecline: () => void;
  } = $props();
</script>

<div class="my-3 rounded-2xl p-4" style="background: var(--quip-glass-bg); border: 1px solid var(--quip-glass-border-strong)">
  <div class="flex items-center gap-2 mb-3">
    <div class="w-6 h-6 rounded-lg flex items-center justify-center flex-shrink-0" style="background: rgba(167,139,250,0.15)">
      <svg class="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2">
        <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        <path d="M9 12l2 2 4-4" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <span class="text-sm font-semibold" style="color: var(--quip-text)">{$t('research.proposalTitle')}</span>
  </div>

  {#if plan.title}
    <p class="text-[13px] mb-2" style="color: var(--quip-text-dim)">{plan.title}</p>
  {/if}

  {#if plan.questions?.length}
    <p class="text-[11px] mb-2 opacity-50" style="color: var(--quip-text-muted)">{$t('research.proposalWillStudy')}</p>
    <ul class="space-y-1 mb-3">
      {#each plan.questions as q}
        <li class="flex items-start gap-2 text-[12px]" style="color: var(--quip-text-dim)">
          <span class="mt-1.5 w-1.5 h-1.5 flex-shrink-0 rounded-full" style="background: currentColor; opacity: 0.4"></span>
          <span>{q}</span>
        </li>
      {/each}
    </ul>
  {/if}

  {#if plan.approach}
    <p class="text-[12px] mb-3 opacity-50" style="color: var(--quip-text-muted)">{plan.approach}</p>
  {/if}

  <div class="flex items-center gap-2">
    <button
      class="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed"
      style="background: #a78bfa; color: #fff"
      onclick={onStart}
      disabled={$isStreaming}
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"/>
      </svg>
      {$t('research.proposalStart')}
    </button>
    <button
      class="px-4 py-2 rounded-xl text-sm font-medium transition-all active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed"
      style="background: transparent; color: var(--quip-text-muted); border: 1px solid var(--quip-border)"
      onclick={onDecline}
      disabled={$isStreaming}
    >
      {$t('research.proposalDecline')}
    </button>
  </div>
</div>
