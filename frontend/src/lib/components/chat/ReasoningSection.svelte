<script lang="ts">
  import { t } from 'svelte-i18n';
  import { isStreaming } from '$lib/stores/chat';

  let { reasoning, html }: { reasoning: string; html: string } = $props();
  let open = $state(false);

  let isThinking = $derived($isStreaming && reasoning.length > 0);
</script>

<div class="mb-3">
  <button
    type="button"
    class="text-xs select-none flex items-center gap-1.5 transition-colors cursor-pointer"
    style="color: var(--quip-text-muted)"
    aria-expanded={open}
    onclick={() => (open = !open)}
    onmouseenter={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-dim)' }}
    onmouseleave={(e) => { (e.currentTarget as HTMLElement).style.color = 'var(--quip-text-muted)' }}
  >
    <!-- SVG chevron -->
    <svg
      class="w-3 h-3 flex-shrink-0 opacity-60"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2.5"
      stroke-linecap="round"
      stroke-linejoin="round"
      style="transition: transform var(--quip-d-2) var(--quip-ease-out); transform: rotate({open ? 90 : 0}deg)"
    >
      <path d="M9 5l7 7-7 7" />
    </svg>

    <span class="truncate">{open ? $t('chat.hideThinking') : $t('chat.showThinking')}</span>
    <span class="opacity-40">({reasoning.length} {$t('chat.chars')})</span>

    <!-- Animated thinking dots while streaming -->
    {#if isThinking && !open}
      <span class="typing-dots text-[8px] flex items-center ml-1">
        <span></span><span></span><span></span>
      </span>
    {/if}
  </button>

  <div
    class="grid"
    style:grid-template-rows={open ? '1fr' : '0fr'}
    style:transition="grid-template-rows var(--quip-d-2) var(--quip-ease-out)"
  >
    <div class="overflow-hidden">
      <div class="mt-2 rounded-xl p-3 text-sm break-words prose prose-invert prose-sm max-w-none" style="background: var(--quip-glass-bg); border: 1px solid var(--quip-glass-border); color: var(--quip-text-dim)">
        {@html html}
      </div>
    </div>
  </div>
</div>
