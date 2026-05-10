<script lang="ts">
  import { messages, isStreaming, branchSelections, activeChat, persistBranchSelections } from '$lib/stores/chat';
  import { t } from 'svelte-i18n';
  import { buildThread, type ThreadMessage } from '$lib/utils/thread';
  import MessageBubble from './MessageBubble.svelte';
  import { fly } from 'svelte/transition';
  import { D2 } from '$lib/motion';
  import { tick } from 'svelte';

  let {
    onRegenerate,
    onEdit,
    onStartResearch,
    onDeclineResearch,
  }: {
    onRegenerate?: (messageId: string) => void;
    onEdit?: (messageId: string, content: string) => void;
    onStartResearch?: (query: string) => void;
    onDeclineResearch?: (messageId: string) => void;
  } = $props();

  let container: HTMLDivElement;
  let isAtBottom = $state(true);
  let userSentMessage = $state(false);

  // Build thread from messages + selections (selections in store, shared with streamChat)
  let thread = $derived(buildThread($messages, $branchSelections));

  function selectSibling(parentId: string | null | undefined, siblingId: string) {
    const key = parentId ?? '__root__';
    branchSelections.update((s) => ({ ...s, [key]: siblingId }));
    // Persist to localStorage so chosen branches survive page refresh
    const cid = $activeChat?.id;
    if (cid) persistBranchSelections(cid);
  }

  function checkScroll() {
    if (!container) return;
    isAtBottom = container.scrollTop + container.clientHeight >= container.scrollHeight - 80;
  }

  function scrollToBottom() {
    if (container) {
      container.scrollTo({ top: container.scrollHeight, behavior: 'smooth' });
    }
  }

  // Auto-scroll only if user was at bottom or just sent a message
  $effect(() => {
    if ($messages.length > 0 && (isAtBottom || userSentMessage)) {
      tick().then(() => {
        if (container) {
          container.scrollTop = container.scrollHeight;
        }
        userSentMessage = false;
      });
    }
  });

  // Detect when user sends a message (temp-user appears)
  $effect(() => {
    if ($messages.some((m) => m.id === 'temp-user')) {
      userSentMessage = true;
    }
  });
</script>

<div bind:this={container} class="flex-1 overflow-y-auto pt-20 pb-44 relative" onscroll={checkScroll}>
  <div class="max-w-4xl mx-auto w-full space-y-8">
    {#each thread as message, i (message.id)}
      <!--suppress svelte-garden/derived-var-used-in-key: branchDepth is stable per message id -->
      {@const depthHue = message.branchDepth > 0 ? [30, 345, 260, 150][(message.branchDepth - 1) % 4] : 0}
      <div in:fly={{ y: 10, duration: D2, delay: Math.min(i, 4) * 40 }}>
        <div
          class="{message.branchDepth > 0 ? 'border-l-2' : ''}"
          style={message.branchDepth > 0
            ? `border-left-color: hsl(${depthHue}, 40%, 35%); padding-left: ${Math.min(8 + message.branchDepth * 4, 24)}px`
            : ''}
        >
          <MessageBubble {message} {onRegenerate} {onEdit} {onStartResearch} {onDeclineResearch} />
        </div>
        {#if message.siblingCount > 1}
          <div
            class="flex items-center justify-center gap-3 mt-2 group select-none"
            title={$t('chat.branchAlt', { values: { count: message.siblingCount } })}
          >
            <!-- Prev button -->
            <button
              class="p-1 rounded-lg hover:bg-slate-800 disabled:opacity-20 disabled:cursor-default transition-all active:scale-[0.90]"
              disabled={message.siblingIndex <= 1}
              onclick={() => selectSibling(message.parent_id, message.siblingIds[message.siblingIndex - 2])}
              aria-label={$t('chat.prevBranch')}
            >
              <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 18l-6-6 6-6"/></svg>
            </button>

            <!-- Branch indicator -->
            <div class="flex items-center gap-1.5 text-xs text-slate-500">
              <svg class="w-3.5 h-3.5 text-slate-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <line x1="6" y1="3" x2="6" y2="15"/>
                <circle cx="6" cy="18" r="3"/>
                <path d="M18 9a9 9 0 01-9 9"/>
                <circle cx="18" cy="6" r="3"/>
              </svg>
              <span class="tabular-nums">{$t('chat.branchOf', { values: { current: message.siblingIndex, total: message.siblingCount } })}</span>
            </div>

            <!-- Next button -->
            <button
              class="p-1 rounded-lg hover:bg-slate-800 disabled:opacity-20 disabled:cursor-default transition-all active:scale-[0.90]"
              disabled={message.siblingIndex >= message.siblingCount}
              onclick={() => selectSibling(message.parent_id, message.siblingIds[message.siblingIndex])}
              aria-label={$t('chat.nextBranch')}
            >
              <svg class="w-4 h-4 text-slate-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
            </button>
          </div>
        {/if}
      </div>
    {/each}
  </div>

  {#if !isAtBottom}
    <button
      class="sticky bottom-4 left-1/2 -translate-x-1/2 z-10 p-1.5 rounded-full transition-all text-slate-400 hover:text-slate-200"
      style="background: rgba(22,22,26,0.5); border: 1px solid var(--quip-glass-border); backdrop-filter: blur(12px) saturate(1.4); -webkit-backdrop-filter: blur(12px) saturate(1.4);"
      onclick={scrollToBottom}
      title={$t('chat.scrollToBottom')}
      aria-label={$t('chat.scrollToBottom')}
    >
      <svg class="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M7 13l5 5 5-5M7 6l5 5 5-5"/></svg>
    </button>
  {/if}
</div>
